import pytest

import exergy_imperative as xi


def test_ghg_boundaries_separate_direct_indirect_and_allocation_view():
    result = xi.assess_ghg_boundaries(
        combustion_gases_kg={"CO2": 100.0},
        fugitive_gases_kg={"CH4-fossil": 10.0},
        purchased_energy_co2e_kg=50.0,
        allocated_electricity_heat_co2e_kg=200.0,
    )
    assert result.direct_co2e100_kg == pytest.approx(100 + 10 * 29.8)
    assert result.direct_co2e20_kg == pytest.approx(100 + 10 * 82.5)
    assert result.indirect_co2e100_kg == pytest.approx(50.0)
    assert result.total_co2e100_kg == pytest.approx(448.0)
    allocated = next(
        item
        for item in result.boundaries
        if item.boundary == "electricity-and-heat-allocated"
    )
    assert not allocated.included_in_total
    assert any("double counting" in warning for warning in result.warnings)


def test_methane_recovery_reports_both_horizons_energy_revenue_and_economics():
    result = xi.assess_methane_project(
        annual_methane_mass_kg=1000.0,
        baseline_mode="vented",
        project_mode="recovered",
        project_efficiency=0.9,
        recovered_gas_price_per_mwh=40.0,
        capital_cost=1000.0,
        project_life_years=5,
    )
    assert result.project.methane_recovered_kg == pytest.approx(900.0)
    assert result.project.recovered_energy_mwh == pytest.approx(
        900.0 * xi.DEFAULT_METHANE_LHV_MWH_PER_KG
    )
    assert result.avoided_co2e20_kg == pytest.approx(900.0 * 82.5)
    assert result.avoided_co2e100_kg == pytest.approx(900.0 * 29.8)
    assert result.recovered_gas_revenue == pytest.approx(
        result.project.recovered_energy_mwh * 40.0
    )
    assert result.economics is not None
    assert result.economics.annual_benefits["product_revenue"] == pytest.approx(
        result.recovered_gas_revenue
    )
    assert result.baseline.effective_efficiency == pytest.approx(0)
    assert result.project.effective_efficiency == pytest.approx(0.9)
    assert result.assumptions["baseline_efficiency"] == pytest.approx(0)
    assert result.assumptions["baseline_efficiency_input"] == pytest.approx(0)
    assert result.assumptions["baseline_efficiency_defaulted"] is True
    assert result.assumptions["project_efficiency_defaulted"] is False
    assert result.assumptions["baseline_efficiency_input_used"] is False
    assert result.assumptions["project_efficiency_input_used"] is True
    assert not any("ignored for venting" in warning for warning in result.warnings)


def test_methane_project_currency_is_normalized_consistently():
    result = xi.assess_methane_project(
        annual_methane_mass_kg=100.0,
        recovered_gas_price_per_mwh=20.0,
        capital_cost=10.0,
        currency=" usd ",
    )
    assert result.currency == "USD"
    assert result.economics is not None
    assert result.economics.currency == "USD"

    with pytest.raises(ValueError, match="currency must be a non-empty string"):
        xi.assess_methane_project(
            annual_methane_mass_kg=100.0,
            currency=" ",
        )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("vented", 0.0),
        ("flared", xi.EPA_FLARE_DESTRUCTION_EFFICIENCY),
        ("oxidized", 1.0),
        ("recovered", 1.0),
    ],
)
def test_methane_efficiency_defaults_follow_each_selected_mode(mode, expected):
    project = xi.assess_methane_project(
        annual_methane_mass_kg=100.0,
        baseline_mode="vented",
        project_mode=mode,
    )
    baseline = xi.assess_methane_project(
        annual_methane_mass_kg=100.0,
        baseline_mode=mode,
        project_mode="vented",
    )

    assert project.project.effective_efficiency == pytest.approx(expected)
    assert baseline.baseline.effective_efficiency == pytest.approx(expected)
    assert project.assumptions["project_efficiency_defaulted"] is True
    assert baseline.assumptions["baseline_efficiency_defaulted"] is True


def test_explicit_nonzero_venting_efficiency_is_ignored_with_warning():
    result = xi.assess_methane_project(
        annual_methane_mass_kg=100.0,
        baseline_mode="vented",
        baseline_efficiency=0.5,
    )

    assert result.baseline.effective_efficiency == 0.0
    assert any("ignored for venting" in warning for warning in result.warnings)


def test_methane_recovery_revenue_is_incremental_to_recovered_baseline():
    result = xi.assess_methane_project(
        annual_methane_mass_kg=1000.0,
        baseline_mode="recovered",
        baseline_efficiency=0.5,
        project_mode="recovered",
        project_efficiency=0.9,
        recovered_gas_price_per_mwh=100.0,
        capital_cost=0.0,
        project_life_years=1,
    )
    expected = (
        result.project.recovered_energy_mwh - result.baseline.recovered_energy_mwh
    ) * 100.0
    assert result.recovered_gas_revenue == pytest.approx(expected)
    assert result.economics is not None
    assert result.economics.annual_benefits["product_revenue"] == pytest.approx(
        expected
    )


def test_flare_converts_destroyed_methane_to_combustion_co2():
    result = xi.assess_methane_project(
        annual_methane_mass_kg=100.0,
        baseline_mode="vented",
        project_mode="flared",
        project_efficiency=0.98,
    )
    assert result.project.methane_released_kg == pytest.approx(2.0)
    assert result.project.combustion_co2_kg == pytest.approx(98.0 * (44.0095 / 16.0425))
    assert result.avoided_co2e100_kg > 0.0


def test_biogenic_methane_uses_nonfossil_gwp_and_excludes_biogenic_co2():
    result = xi.assess_methane_project(
        annual_methane_mass_kg=100.0,
        methane_origin="biogenic",
        baseline_mode="vented",
        project_mode="flared",
        project_efficiency=1.0,
    )
    assert result.baseline.ghg.total_co2e100_kg == pytest.approx(100 * 27.0)
    fugitive = next(
        item for item in result.baseline.ghg.boundaries if item.boundary == "fugitive"
    )
    assert fugitive.gases_kg == {"CH4-biogenic": pytest.approx(100)}
    assert result.project.combustion_co2_kg == pytest.approx(100 * (44.0095 / 16.0425))
    assert result.project.ghg.total_co2e100_kg == pytest.approx(0)
    assert result.assumptions["methane_origin"] == "biogenic"


def test_methane_origin_is_validated():
    with pytest.raises(ValueError, match="fossil or biogenic"):
        xi.assess_methane_project(
            annual_methane_mass_kg=1,
            methane_origin="unknown",
        )


def test_methane_project_requires_exactly_one_quantity_basis():
    with pytest.raises(ValueError, match="exactly one"):
        xi.assess_methane_project()
    with pytest.raises(ValueError, match="exactly one"):
        xi.assess_methane_project(
            annual_methane_mass_kg=1,
            annual_methane_volume_m3=1,
        )
