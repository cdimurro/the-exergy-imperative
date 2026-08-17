import pytest

import exergy_imperative as xi


def test_process_catalog_covers_requested_industries():
    ids = {item.id for item in xi.list_process_templates()}
    assert ids >= {
        "steam-system",
        "industrial-furnace",
        "compressed-air",
        "industrial-refrigeration",
        "industrial-drying",
        "desalination",
        "hydrogen-electrolysis",
        "data-center",
        "cement",
        "steel-reheating",
        "food-processing",
        "district-energy",
    }


def test_process_alias_and_unknown_template():
    assert xi.get_process_template("steam boiler").id == "steam-system"
    with pytest.raises(xi.ProcessTemplateNotFoundError):
        xi.get_process_template("warp drive")


def test_steam_template_integrates_exergy_environment_and_opportunity():
    result = xi.assess_process("steam", 1000, country="USA", year=2025)
    assert result.assessment.exergetic_efficiency.value < 0.5
    assert result.environmental.co2e100_kg > 180_000
    assert result.opportunity.energy_savings.value == pytest.approx(100)
    assert result.opportunity.exergy_destruction_reduction.value > 0
    assert result.economics is None
    assert "screening prior" in result.warnings[0]


def test_process_explicit_improvement_and_economics():
    result = xi.assess_process(
        "compressed air",
        1000,
        country="Germany",
        improvement_fraction=0.25,
        annualization_factor=1.0,
        economics_options={
            "capital_cost": 50_000,
            "energy_price_per_mwh": 100,
            "project_life_years": 10,
        },
    )
    assert result.opportunity.energy_savings.value == pytest.approx(250)
    assert result.opportunity.energy_savings.low == pytest.approx(250)
    assert result.economics is not None
    assert result.economics.npv > 0


@pytest.mark.parametrize(
    "override",
    [
        {"energy": 1000},
        {"unit": "GJ"},
        {"carrier": "coal"},
        {"country": "France"},
        {"assessment": xi.assess(carrier="electricity", energy=1)},
    ],
)
def test_process_rejects_impact_boundary_overrides(override):
    with pytest.raises(ValueError, match="cannot override"):
        xi.assess_process("steam", 100, impact_options=override)


@pytest.mark.parametrize(
    ("top_level", "assessment_options", "conflict"),
    [
        ({"energy": 100}, {"energy": 1_000}, "energy"),
        ({"energy": 100, "unit": "MWh"}, {"unit": "GJ"}, "unit"),
        ({"energy": 100, "country": "USA"}, {"location": "France"}, "country"),
    ],
)
def test_process_rejects_conflicting_assessment_boundaries(
    top_level, assessment_options, conflict
):
    with pytest.raises(ValueError, match=conflict):
        xi.assess_process("steam", assessment_options=assessment_options, **top_level)


def test_process_template_technology_cannot_be_replaced_by_nested_options():
    with pytest.raises(ValueError, match="cannot override.*technology"):
        xi.assess_process(
            "steam", 100, assessment_options={"technology": "electric chiller"}
        )


def test_process_rejects_conflicting_impact_defaults():
    with pytest.raises(ValueError, match="year"):
        xi.assess_process("steam", 100, year=2025, impact_options={"year": 2024})
    with pytest.raises(ValueError, match="factor_library"):
        xi.assess_process(
            "steam",
            100,
            factor_library=xi.DEFAULT_IMPACT_FACTORS,
            impact_options={"factor_library": object()},
        )


def test_refrigeration_template_accepts_refrigerant_leakage():
    result = xi.assess_process(
        "refrigeration",
        100,
        country="France",
        impact_options={"refrigerant_leakage_kg": {"R134a": 5}},
    )
    assert result.environmental.warming_horizon_gap_kg_co2e > 10_000
    assert result.opportunity.co2e100_reduction.value == pytest.approx(
        result.environmental.aggregate_grid_co2e_kg
        * result.opportunity.improvement_fraction.value
    )
    assert any("held constant" in warning for warning in result.warnings)


def test_process_opportunity_combines_source_and_fraction_ranges():
    result = xi.assess_process("steam", 1_000, country="USA")
    destroyed = result.assessment.exergy_destroyed_or_lost
    fraction = result.opportunity.improvement_fraction
    reduction = result.opportunity.exergy_destruction_reduction
    assert reduction.low == pytest.approx(destroyed.low * fraction.low)
    assert reduction.high == pytest.approx(destroyed.high * fraction.high)

    nox = next(
        item for item in result.environmental.pollutants if item.pollutant == "NOx"
    )
    nox_reduction = result.opportunity.pollutant_reductions_kg["NOx"]
    assert nox_reduction.low == pytest.approx(nox.mass.low * fraction.low)
    assert nox_reduction.high == pytest.approx(nox.mass.high * fraction.high)


def test_scenario_comparison_and_avoided_destruction():
    baseline = xi.assess_process("steam", 1000, assessment_options={"efficiency": 0.75})
    improved = xi.assess_process("steam", 1000, assessment_options={"efficiency": 0.90})
    comparison = xi.compare_scenarios(
        {"baseline": baseline, "improved": improved}, baseline="baseline"
    )
    assert comparison.deltas_from_baseline["improved"]["exergetic_efficiency"] > 0
    assert xi.avoided_exergy_destruction(baseline, improved) > 0


def test_scenario_mapping_support():
    result = xi.compare_scenarios(
        {
            "old": {"co2e100_kg": 100, "npv": 0},
            "new": {"co2e100_kg": 50, "npv": 20},
        }
    )
    assert result.deltas_from_baseline["new"]["co2e100_kg"] == pytest.approx(-50)


def test_scenario_mapping_rejects_unknown_metric_names():
    with pytest.raises(ValueError, match="unknown scenario metric.*co2e_100_kg"):
        xi.compare_scenarios(
            {
                "old": {"co2e100_kg": 100},
                "new": {"co2e_100_kg": 50},
            }
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_scenario_mapping_rejects_nonfinite_metrics(value):
    with pytest.raises(ValueError, match="must be finite"):
        xi.compare_scenarios(
            {
                "old": {"co2e100_kg": 100},
                "new": {"co2e100_kg": value},
            }
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_preconstructed_scenario_metrics_reject_nonfinite_values(value):
    with pytest.raises(ValueError, match="scenario metric 'npv' must be finite"):
        xi.compare_scenarios(
            {
                "old": xi.ScenarioMetrics(npv=1),
                "new": xi.ScenarioMetrics(npv=value),
            }
        )


def test_scenario_currency_comparison_is_case_and_whitespace_insensitive():
    result = xi.compare_scenarios(
        {
            "old": {
                "npv": 1,
                "currency": "USD",
                "health_externality_cost": 10,
                "health_cost_currency": " EUR ",
            },
            "new": {
                "npv": 2,
                "currency": " usd ",
                "health_externality_cost": 5,
                "health_cost_currency": "eur",
            },
        }
    )
    assert result.deltas_from_baseline["new"]["npv"] == pytest.approx(1)
    assert result.deltas_from_baseline["new"][
        "health_externality_cost"
    ] == pytest.approx(-5)


def test_scenario_comparison_rejects_mixed_normalization_bases():
    normalized = xi.assess(technology="gas boiler")
    absolute = xi.assess(technology="gas boiler", energy=100)
    with pytest.raises(ValueError, match="normalized per-MWh and absolute"):
        xi.compare_scenarios({"normalized": normalized, "absolute": absolute})


def test_scenario_comparison_rejects_known_and_unknown_normalization_bases():
    normalized = xi.assess(technology="gas boiler")
    with pytest.raises(ValueError, match="known and unknown normalization bases"):
        xi.compare_scenarios(
            {
                "normalized": normalized,
                "unknown": {"input_energy_mwh": 100},
            }
        )

    explicit = xi.compare_scenarios(
        {
            "normalized": normalized,
            "mapping": {"input_energy_mwh": 1, "normalized": True},
        }
    )
    assert explicit.scenarios["mapping"].normalized is True


def test_scenario_comparison_rejects_mixed_currencies():
    usd = xi.assess_process(
        "steam",
        100,
        annualization_factor=1,
        economics_options={"capital_cost": 1000, "currency": "USD"},
    )
    jpy = xi.assess_process(
        "steam",
        100,
        annualization_factor=1,
        economics_options={"capital_cost": 1000, "currency": "JPY"},
    )
    with pytest.raises(ValueError, match="different currencies"):
        xi.compare_scenarios({"usd": usd, "jpy": jpy})


def test_process_economics_rejects_derived_health_currency_mismatch():
    with pytest.raises(ValueError, match="damage-cost currency"):
        xi.assess_process(
            "steam",
            100,
            annualization_factor=1,
            impact_options={
                "damage_costs_per_kg": {"NOx": 10},
                "currency": "EUR",
            },
            economics_options={"capital_cost": 1000, "currency": "USD"},
        )

    explicit = xi.assess_process(
        "steam",
        100,
        impact_options={
            "damage_costs_per_kg": {"NOx": 10},
            "currency": "EUR",
        },
        economics_options={
            "capital_cost": 1000,
            "currency": "USD",
            "annual_energy_savings_mwh": 1,
            "annual_exergy_savings_mwh": 1,
            "annual_co2e_reduction_kg": 1,
            "annual_health_externality_reduction": 25,
        },
    )
    assert explicit.economics is not None
    assert explicit.economics.annual_benefits["health_externality"] == pytest.approx(25)


def test_process_normalizes_equivalent_impact_and_economics_currencies():
    result = xi.assess_process(
        "steam",
        100,
        annualization_factor=1,
        impact_options={
            "damage_costs_per_kg": {"NOx": 10},
            "currency": " usd ",
        },
        economics_options={"capital_cost": 1000, "currency": " usd "},
    )
    assert result.environmental.health_externality_currency == "USD"
    assert result.economics is not None
    assert result.economics.currency == "USD"


def test_scenario_comparison_tracks_health_cost_currency_without_economics():
    eur = xi.assess_process(
        "steam",
        100,
        impact_options={
            "damage_costs_per_kg": {"NOx": 10},
            "currency": "EUR",
        },
    )
    jpy = xi.assess_process(
        "steam",
        100,
        impact_options={
            "damage_costs_per_kg": {"NOx": 10},
            "currency": "JPY",
        },
    )
    with pytest.raises(ValueError, match="health externality costs"):
        xi.compare_scenarios({"eur": eur, "jpy": jpy})


def test_scenario_comparison_rejects_mixed_health_valuation_coverage():
    unvalued = xi.assess_process("steam", 100)
    valued = xi.assess_process(
        "steam",
        100,
        impact_options={
            "damage_costs_per_kg": {"NOx": 10},
            "currency": "USD",
        },
    )

    with pytest.raises(ValueError, match="valued and unvalued health"):
        xi.compare_scenarios({"unvalued": unvalued, "valued": valued})


def test_process_requires_capital_cost_for_economics():
    with pytest.raises(ValueError, match="capital_cost"):
        xi.assess_process("steam", 100, economics_options={})


def test_process_economics_requires_and_applies_explicit_annualization():
    with pytest.raises(ValueError, match="annualization_factor"):
        xi.assess_process("steam", 100, economics_options={"capital_cost": 1000})

    result = xi.assess_process(
        "steam",
        100,
        annualization_factor=12,
        economics_options={"capital_cost": 1000, "energy_price_per_mwh": 1},
    )
    assert result.economics is not None
    assert result.annualization_factor == pytest.approx(12)
    assert result.economics.annual_benefits["energy_first_year"] == pytest.approx(
        result.opportunity.energy_savings.value * 12
    )


def test_normalized_process_cannot_be_annualized_from_arbitrary_one_mwh_basis():
    with pytest.raises(ValueError, match="cannot annualize.*normalized"):
        xi.assess_process(
            "steam",
            annualization_factor=8760,
            economics_options={"capital_cost": 1000},
        )


def test_process_summary_and_reports_include_thermodynamic_warnings():
    result = xi.assess_process("refrigeration", 100, country="France")
    warning = next(item for item in result.assessment.warnings if "unphysical" in item)
    assert warning in result.warnings
    assert warning in result.summary()
