import pytest

import exergy_imperative as xi


@pytest.mark.parametrize(
    ("value", "unit", "expected_mwh"),
    [
        (1, "MWh", 1),
        (1000, "kWh", 1),
        (3.6, "GJ", 1),
        (3_600_000_000, "J", 1),
        (1, "MWh_th", 1),
        (1, "MWh_HHV_CH4", 1),
        (1, "MMBtu", 0.2930710702),
    ],
)
def test_energy_conversion(value, unit, expected_mwh):
    assert xi.convert_energy(value, unit) == pytest.approx(expected_mwh)


def test_temperature_units_are_equivalent():
    assert xi.parse_temperature("20 C") == pytest.approx(20)
    assert xi.parse_temperature("68 F") == pytest.approx(20)
    assert xi.parse_temperature("293.15 K") == pytest.approx(20)


def test_temperature_below_absolute_zero_is_rejected():
    with pytest.raises(xi.UnitError, match="absolute zero"):
        xi.parse_temperature(-274, "C")


@pytest.mark.parametrize(
    ("value", "unit"),
    [("1e309 C", None), (1e308, "F")],
)
def test_nonfinite_temperature_results_are_rejected(value, unit):
    with pytest.raises(xi.UnitError, match="finite"):
        xi.parse_temperature(value, unit)


def test_invalid_energy_unit_is_rejected():
    with pytest.raises(xi.UnitError, match="unsupported"):
        xi.convert_energy(1, "bananas")


def test_typed_exergy_unit():
    assert xi.exergy_unit_for("GJ_th") == "GJ_ex"


def test_typed_energy_basis_is_exposed_and_validated():
    assert xi.energy_basis("MWh_LHV") == "LHV"
    assert xi.energy_basis("MWh_HHV_CH4") == "HHV"
    assert xi.energy_basis("MWh") is None
    with pytest.raises(xi.UnitError, match="conflicting"):
        xi.energy_basis("MWh_HHV_LHV")
    with pytest.raises(xi.UnitError, match="fuel-specific"):
        xi.convert_energy(1, "MWh_HHV", "MWh_LHV")
