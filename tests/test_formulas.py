import math

import pytest

import exergy_imperative as xi


def test_thermal_factor_matches_paper_example():
    assert xi.thermal_exergy_factor_c(80, 20) == pytest.approx(0.1698994761)


def test_thermal_factor_is_zero_at_dead_state():
    assert xi.thermal_exergy_factor_c(20, 20) == pytest.approx(0.0)


def test_heat_below_reference_is_rejected():
    with pytest.raises(ValueError, match="at least"):
        xi.thermal_exergy_factor_c(10, 20)


def test_cooling_factor_matches_paper_example():
    assert xi.cooling_exergy_factor_c(7, 30) == pytest.approx(0.0820988756)


def test_sensible_stream_factor_matches_closed_form():
    expected = 1 - 293.15 * math.log(353.15 / 323.15) / (353.15 - 323.15)
    assert xi.sensible_heat_exergy_factor_c(80, 50, 20) == pytest.approx(expected)


@pytest.mark.parametrize("lift", [1e-12, 1e-13])
def test_sensible_stream_factor_is_stable_for_close_temperatures(lift):
    factor = xi.sensible_heat_exergy_factor(300.0 + lift, 300.0, 298.15)
    assert factor == pytest.approx(1.0 - 298.15 / 300.0, rel=1e-10)


def test_sensible_stream_factor_resolves_tiny_lift_from_reference_state():
    supply = 300.0 + 1e-12
    factor = xi.sensible_heat_exergy_factor(supply, 300.0, 300.0)
    assert factor == pytest.approx((supply - 300.0) / 600.0, rel=1e-12)


def test_sensible_stream_requires_cooling_direction():
    with pytest.raises(ValueError, match="greater"):
        xi.sensible_heat_exergy_factor_c(50, 80, 20)


def test_physical_flow_exergy():
    value = xi.physical_flow_exergy(3100, 105, 6.6, 0.367, 298.15)
    assert value == pytest.approx((3100 - 105) - 298.15 * (6.6 - 0.367))


def test_gouy_stodola():
    assert xi.exergy_destruction(298.15, 2.5) == pytest.approx(745.375)
    with pytest.raises(ValueError, match="nonnegative"):
        xi.exergy_destruction(298.15, -1)


def test_kinetic_and_potential_exergy():
    assert xi.kinetic_exergy(2, 3) == pytest.approx(9)
    assert xi.potential_exergy(2, 10) == pytest.approx(196.133)


def test_ideal_gas_pressure_exergy_is_zero_at_reference():
    assert xi.ideal_gas_pressure_exergy(1, 101.325, 101.325, 298.15) == pytest.approx(0)


def test_binary_mixture_separation_exergy():
    expected = xi.UNIVERSAL_GAS_CONSTANT * 298.15 * math.log(2)
    assert xi.ideal_mixture_separation_exergy(1, [0.5, 0.5], 298.15) == pytest.approx(
        expected
    )


def test_mole_fractions_must_sum_to_one():
    with pytest.raises(ValueError, match="sum to one"):
        xi.ideal_mixture_separation_exergy(1, [0.6, 0.5], 298.15)


def test_petela_solar_factor():
    assert xi.petela_exergy_factor(293.15) == pytest.approx(0.93239, rel=1e-4)


def test_accessible_exergy_and_efficiency():
    assert xi.accessible_exergy(100, 0.17) == pytest.approx(17)
    assert xi.exergetic_efficiency(17, 100) == pytest.approx(0.17)
    with pytest.raises(ValueError, match="cannot exceed"):
        xi.exergetic_efficiency(101, 100)


def test_weighted_factor():
    assert xi.weighted_exergy_factor([(2, 0.1), (1, 0.4)]) == pytest.approx(0.2)
    with pytest.raises(ValueError, match="positive weight"):
        xi.weighted_exergy_factor([(0, 0.1)])
