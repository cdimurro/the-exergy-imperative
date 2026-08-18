"""Golden-value tests anchored to independent published results.

Unlike the formula unit tests, which check internal consistency, every
expectation in this module comes from a source outside this codebase: a
published steam table, a published paper, a standard textbook result, or a
defined physical constant. A regression here means the package disagrees
with the literature, not merely with itself.

Sources:

- Steam and saturated-liquid water properties: standard steam-table values
  (IAPWS formulations), as tabulated in Cengel & Boles, "Thermodynamics: An
  Engineering Approach" (Tables A-4 and A-6) and equivalent references.
- Radiative exergy: Petela (2003), "Exergy of undiluted thermal radiation,"
  Solar Energy 74, doi:10.1016/S0038-092X(03)00226-3.
- Minimum work of separation: standard result for an ideal equimolar binary
  mixture, R*T0*ln(2) per mole of mixture (e.g. Bejan, "Advanced Engineering
  Thermodynamics"; Moran & Shapiro, "Fundamentals of Engineering
  Thermodynamics").
- Standard gravity: 9.80665 m/s^2 (ISO 80000-3).
"""

import math

import pytest

import exergy_imperative as xi

# Published superheated-steam values at 8 MPa, 500 C (steam tables):
#   h = 3398.3 kJ/kg, s = 6.7240 kJ/kg-K
# Published saturated-liquid values at the 25 C dead state:
#   h0 = 104.89 kJ/kg, s0 = 0.3674 kJ/kg-K
# Specific flow exergy = (h - h0) - T0*(s - s0) with T0 = 298.15 K:
STEAM_8MPA_500C_EXERGY_KJ_PER_KG = (3398.3 - 104.89) - 298.15 * (6.7240 - 0.3674)


def test_flow_exergy_of_steam_matches_steam_tables():
    """CoolProp-backed physical exergy agrees with published steam tables."""
    if not xi.coolprop_available():
        pytest.skip("CoolProp optional dependency is not installed")
    result = xi.coolprop_physical_exergy("Water", "500 C", 8000)
    assert result.physical_exergy_j_per_kg / 1000 == pytest.approx(
        STEAM_8MPA_500C_EXERGY_KJ_PER_KG, rel=5e-3
    )


def test_physical_flow_exergy_formula_reproduces_steam_table_case():
    """The dependency-free formula reproduces the same steam-table case."""
    exergy_kj_per_kg = xi.physical_flow_exergy(3398.3, 104.89, 6.7240, 0.3674, 298.15)
    assert exergy_kj_per_kg == pytest.approx(STEAM_8MPA_500C_EXERGY_KJ_PER_KG, rel=1e-9)


def test_compressed_air_real_fluid_agrees_with_ideal_gas_expression():
    """Two independent code paths agree: real-fluid air versus R*T0*ln(P/P0).

    At 1 MPa and 25 C the real-gas correction for air is well under one
    percent, so the CoolProp-backed result and the closed-form ideal-gas
    pressure exergy must coincide closely.
    """
    if not xi.coolprop_available():
        pytest.skip("CoolProp optional dependency is not installed")
    molar_mass_air_kg_per_mol = 0.0289647
    ideal_j_per_kg = (
        xi.ideal_gas_pressure_exergy(1.0, 1000.0, 101.325, 298.15)
        / molar_mass_air_kg_per_mol
    )
    real = xi.coolprop_physical_exergy("Air", "25 C", 1000)
    assert real.physical_exergy_j_per_kg == pytest.approx(ideal_j_per_kg, rel=1e-2)


def test_petela_factor_matches_published_value_for_6000_k_sun():
    """Petela (2003): psi = 1 - (4/3)(T0/Ts) + (1/3)(T0/Ts)^4.

    For Ts = 6000 K and T0 = 300 K the widely quoted value is 0.9333.
    """
    assert xi.petela_exergy_factor(300.0, 6000.0) == pytest.approx(0.93334, abs=1e-4)


@pytest.mark.parametrize(
    ("source_k", "reference_k", "expected"),
    [
        # Carnot factors from the defining relation 1 - T0/T, matching the
        # benchmark temperatures published in The Exergy Imperative guide.
        (1773.15, 293.15, 0.83467),  # 1500 C furnace heat vs 20 C ambient
        (353.15, 293.15, 0.16990),  # 80 C hot water vs 20 C ambient
        (313.15, 293.15, 0.06387),  # 40 C space heat vs 20 C ambient
    ],
)
def test_carnot_factors_match_hand_computed_benchmarks(source_k, reference_k, expected):
    assert xi.thermal_exergy_factor(source_k, reference_k) == pytest.approx(
        expected, abs=1e-5
    )


def test_equimolar_separation_work_is_rt0_ln2():
    """Textbook minimum work to separate an ideal equimolar binary mixture."""
    expected_j = xi.UNIVERSAL_GAS_CONSTANT * 298.15 * math.log(2.0)
    assert xi.ideal_mixture_separation_exergy(1.0, [0.5, 0.5], 298.15) == pytest.approx(
        expected_j, rel=1e-9
    )
    # Published value quoted to four significant figures: 1.718 kJ/mol.
    assert expected_j / 1000 == pytest.approx(1.718, abs=5e-4)


def test_kinetic_and_potential_exergy_equal_mechanical_energy():
    """Kinetic and potential exergy equal their energy exactly.

    0.5*m*v^2 and m*g*z with standard gravity 9.80665 m/s^2 (ISO 80000-3).
    """
    assert xi.kinetic_exergy(1.0, 50.0) == pytest.approx(1250.0, rel=1e-12)
    assert xi.potential_exergy(1.0, 100.0) == pytest.approx(980.665, rel=1e-12)
