import pytest

import exergy_imperative as xi


def test_npv_uses_time_zero_cash_flow():
    assert xi.net_present_value(0.10, [-100, 60, 60]) == pytest.approx(
        -100 + 60 / 1.1 + 60 / 1.1**2
    )


def test_capital_recovery_factor_handles_zero_rate():
    assert xi.capital_recovery_factor(0, 10) == pytest.approx(0.1)
    assert xi.capital_recovery_factor(1e-16, 20) == pytest.approx(0.05)
    assert xi.capital_recovery_factor(0.07, 20) > 0.09


@pytest.mark.parametrize("periods", [True, float("nan"), float("inf"), 1.5])
def test_period_based_economic_functions_reject_invalid_counts(periods):
    with pytest.raises(ValueError, match="periods must be a finite integer"):
        xi.capital_recovery_factor(0.07, periods)
    with pytest.raises(ValueError, match="periods must be a finite integer"):
        xi.price_trajectory(10, periods)


def test_payback_and_irr():
    cash_flows = [-100, 60, 60]
    assert xi.simple_payback_period(cash_flows) == pytest.approx(1 + 40 / 60)
    assert xi.discounted_payback_period(0.10, cash_flows) < 2
    assert xi.internal_rate_of_return(cash_flows) == pytest.approx(0.130662, rel=1e-5)
    assert xi.internal_rate_of_return([-1, 20]) == pytest.approx(19)


def test_irr_is_accurate_for_a_root_near_zero_discount_factor():
    assert xi.internal_rate_of_return([-1, 1e12]) == pytest.approx(1e12 - 1, rel=1e-12)


def test_irr_is_invariant_to_cash_flow_scale():
    expected = xi.internal_rate_of_return([-1, 1.1])
    assert expected == pytest.approx(0.1)
    assert xi.internal_rate_of_return([-1e-12, 1.1e-12]) == pytest.approx(expected)


def test_irr_rejects_nonunique_cash_flow_pattern():
    assert xi.internal_rate_of_return([-100, 230, -132]) is None


def test_levelized_cost():
    result = xi.levelized_cost([100, 10, 10], [0, 50, 50], 0.05)
    assert result is not None
    assert result > 1


def test_project_economics_integrates_energy_carbon_and_health_benefits():
    result = xi.evaluate_economics(
        capital_cost=100_000,
        annual_energy_savings_mwh=500,
        energy_price_per_mwh=60,
        annual_co2e_reduction_kg=100_000,
        carbon_price_per_tonne=50,
        annual_health_externality_reduction=1_000,
        project_life_years=10,
        discount_rate=0.07,
    )
    assert result.annual_benefits["energy_first_year"] == pytest.approx(30_000)
    assert result.annual_benefits["carbon"] == pytest.approx(5_000)
    assert result.npv > 100_000
    assert result.marginal_abatement_cost_per_tonne_co2e is not None
    assert any("scenario assumptions" in warning for warning in result.warnings)


@pytest.mark.parametrize("life", [True, float("nan"), float("inf"), 1.5])
def test_economic_evaluators_reject_invalid_project_lives(life):
    with pytest.raises(ValueError, match="project_life_years must be a finite integer"):
        xi.evaluate_economics(capital_cost=100, project_life_years=life)
    with pytest.raises(ValueError, match="project_life_years must be a finite integer"):
        xi.evaluate_technology_cost_scenario(
            {
                "name": "invalid life",
                "capital_cost": 100,
                "annual_output_mwh": 10,
                "project_life_years": life,
            }
        )


def test_marginal_abatement_cost_includes_private_revenue_and_residual_value():
    result = xi.evaluate_economics(
        capital_cost=100,
        annual_product_revenue=30,
        residual_value=20,
        annual_co2e_reduction_kg=1_000,
        project_life_years=2,
        discount_rate=0,
    )
    assert result.marginal_abatement_cost_per_tonne_co2e == pytest.approx(10)


def test_benefit_cost_uses_gross_flows_and_levelized_cost_credits_residual():
    result = xi.evaluate_economics(
        capital_cost=100,
        annual_other_benefits=100,
        annual_opex_increase=90,
        annual_energy_savings_mwh=1,
        residual_value=100,
        project_life_years=1,
        discount_rate=0,
    )
    assert result.benefit_cost_ratio == pytest.approx(200 / 190)
    assert result.levelized_cost_per_mwh_saved == pytest.approx(90)


def test_economics_validates_inputs():
    with pytest.raises(ValueError, match="capital_cost"):
        xi.evaluate_economics(capital_cost=-1)
    with pytest.raises(ValueError, match="positive integer"):
        xi.evaluate_economics(capital_cost=1, project_life_years=0)
    with pytest.raises(ValueError, match="currency must be a non-empty string"):
        xi.evaluate_economics(capital_cost=1, currency="   ")


def test_economic_currency_is_trimmed_and_usd_is_canonicalized():
    assert xi.evaluate_economics(capital_cost=1, currency=" usd ").currency == "USD"
    assert xi.evaluate_economics(capital_cost=1, currency=" eur ").currency == "EUR"


def test_other_monetary_models_reject_blank_currencies():
    with pytest.raises(ValueError, match="currency must be a non-empty string"):
        xi.evaluate_technology_cost_scenario(
            {
                "name": "blank currency",
                "capital_cost": 1,
                "annual_output_mwh": 1,
                "currency": "",
            }
        )
    with pytest.raises(ValueError, match="currency must be a non-empty string"):
        xi.stranded_asset_value(
            capital_cost=1,
            commissioning_year=2020,
            retirement_year=2021,
            planned_life_years=10,
            currency=" ",
        )


def test_explicit_energy_and_carbon_price_schedules_drive_cash_flows():
    result = xi.evaluate_economics(
        capital_cost=100,
        annual_energy_savings_mwh=1,
        annual_co2e_reduction_kg=1000,
        annual_energy_prices_per_mwh=[10, 20, 30],
        annual_carbon_prices_per_tonne=[0, 5, 10],
        project_life_years=3,
    )
    assert result.cash_flows == pytest.approx((-100, 10, 25, 40))
    assert result.annual_energy_prices_per_mwh == (10, 20, 30)
    assert result.annual_carbon_prices_per_tonne == (0, 5, 10)


def test_explicit_price_schedules_still_validate_declared_escalation():
    with pytest.raises(ValueError, match="carbon_price_escalation"):
        xi.evaluate_economics(
            capital_cost=100,
            project_life_years=2,
            annual_carbon_prices_per_tonne=[10, 20],
            carbon_price_escalation=float("nan"),
        )


def test_technology_cost_scenario_supports_levelized_heat_and_price_paths():
    scenario = xi.TechnologyCostScenario(
        name="industrial heat pump",
        capital_cost=1000,
        annual_output_mwh=100,
        output_name="useful heat",
        project_life_years=2,
        discount_rate=0.0,
        annual_fixed_opex=10,
        annual_fuel_use_mwh=50,
        annual_fuel_prices_per_mwh=(2, 4),
        annual_emissions_kg_co2e=1000,
        annual_carbon_prices_per_tonne=(0, 10),
        source="user-owned workbook",
    )
    result = xi.evaluate_technology_cost_scenario(scenario)
    assert result.annual_costs == pytest.approx((110, 220))
    assert result.levelized_cost_per_mwh == pytest.approx((1000 + 110 + 220) / 200)
    assert result.to_dict()["levelized_cost_unit"] == "USD/MWh useful heat"


def test_compare_technology_cost_scenarios_and_stranded_cost():
    comparison = xi.compare_technology_cost_scenarios(
        {
            "lower": {
                "name": "lower",
                "capital_cost": 100,
                "annual_output_mwh": 100,
                "project_life_years": 2,
                "discount_rate": 0,
            },
            "higher": {
                "name": "higher",
                "capital_cost": 200,
                "annual_output_mwh": 100,
                "project_life_years": 2,
                "discount_rate": 0,
            },
        }
    )
    assert comparison.lowest_levelized_cost == "lower"
    stranded = xi.stranded_asset_value(
        capital_cost=1000,
        commissioning_year=2020,
        retirement_year=2025,
        planned_life_years=10,
        recoverable_value=100,
        decommissioning_cost=50,
    )
    assert stranded.undepreciated_value == pytest.approx(500)
    assert stranded.net_stranded_cost == pytest.approx(450)

    immediate = xi.stranded_asset_value(
        capital_cost=1000,
        commissioning_year=2025,
        retirement_year=2025,
        planned_life_years=10,
        residual_value=100,
        recoverable_value=100,
    )
    assert immediate.undepreciated_value == pytest.approx(1000)
    assert immediate.net_stranded_cost == pytest.approx(900)
    with pytest.raises(ValueError, match="must not exceed"):
        xi.stranded_asset_value(
            capital_cost=100,
            commissioning_year=2025,
            retirement_year=2025,
            planned_life_years=10,
            residual_value=101,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("commissioning_year", float("nan")),
        ("commissioning_year", 2020.5),
        ("retirement_year", float("inf")),
        ("retirement_year", 2025.5),
    ],
)
def test_stranded_asset_value_rejects_invalid_calendar_years(field, value):
    options = {
        "capital_cost": 100,
        "commissioning_year": 2020,
        "retirement_year": 2025,
        "planned_life_years": 10,
    }
    options[field] = value
    with pytest.raises(ValueError, match=rf"{field} must be a finite integer"):
        xi.stranded_asset_value(**options)


@pytest.mark.parametrize("year", [2025.1, float("nan"), float("inf"), True])
def test_stranded_cost_sensitivity_rejects_invalid_years(year):
    with pytest.raises(ValueError, match="retirement_years.*finite integer"):
        xi.stranded_cost_sensitivity(
            [year],
            capital_cost=100,
            commissioning_year=2020,
            planned_life_years=10,
        )


def test_technology_cost_comparison_rejects_mixed_currencies():
    with pytest.raises(ValueError, match="one currency"):
        xi.compare_technology_cost_scenarios(
            {
                "usd": {
                    "name": "usd",
                    "capital_cost": 100,
                    "annual_output_mwh": 1,
                    "project_life_years": 1,
                    "discount_rate": 0,
                    "currency": "USD",
                },
                "jpy": {
                    "name": "jpy",
                    "capital_cost": 90,
                    "annual_output_mwh": 1,
                    "project_life_years": 1,
                    "discount_rate": 0,
                    "currency": "JPY",
                },
            }
        )


def test_technology_cost_comparison_rejects_mixed_output_bases():
    with pytest.raises(ValueError, match="one output basis"):
        xi.compare_technology_cost_scenarios(
            {
                "power": {
                    "name": "power",
                    "capital_cost": 100,
                    "annual_output_mwh": 1,
                    "output_name": "electricity",
                },
                "heat": {
                    "name": "heat",
                    "capital_cost": 90,
                    "annual_output_mwh": 1,
                    "output_name": "useful heat",
                },
            }
        )


@pytest.mark.parametrize("second_price_year", [2024, None])
def test_technology_cost_comparison_requires_common_price_year(second_price_year):
    with pytest.raises(ValueError, match="one declared price year"):
        xi.compare_technology_cost_scenarios(
            {
                "first": {
                    "name": "first",
                    "capital_cost": 100,
                    "annual_output_mwh": 1,
                    "price_year": 2020,
                },
                "second": {
                    "name": "second",
                    "capital_cost": 90,
                    "annual_output_mwh": 1,
                    "price_year": second_price_year,
                },
            }
        )


def test_technology_cost_accepts_integral_float_project_life():
    result = xi.evaluate_technology_cost_scenario(
        {
            "name": "json-loaded",
            "capital_cost": 100,
            "annual_output_mwh": 10,
            "project_life_years": 2.0,
            "discount_rate": 0,
        }
    )
    assert len(result.annual_outputs_mwh) == 2
    assert len(result.cash_flows) == 3


def test_technology_cost_normalizes_integral_price_year():
    result = xi.evaluate_technology_cost_scenario(
        {
            "name": "calendar metadata",
            "capital_cost": 100,
            "annual_output_mwh": 10,
            "price_year": 2024.0,
        }
    )
    assert result.scenario.price_year == 2024
    assert isinstance(result.scenario.price_year, int)


@pytest.mark.parametrize("price_year", [2024.5, float("nan"), float("inf"), True])
def test_technology_cost_rejects_invalid_price_year(price_year):
    with pytest.raises(ValueError, match="price_year must be a finite integer"):
        xi.evaluate_technology_cost_scenario(
            {
                "name": "invalid calendar metadata",
                "capital_cost": 100,
                "annual_output_mwh": 10,
                "price_year": price_year,
            }
        )


@pytest.mark.parametrize(
    ("schedule_name", "escalation_name"),
    [
        ("annual_fuel_prices_per_mwh", "fuel_price_escalation"),
        ("annual_carbon_prices_per_tonne", "carbon_price_escalation"),
        ("annual_output_values_per_mwh", "output_value_escalation"),
    ],
)
def test_technology_explicit_schedules_validate_escalation(
    schedule_name, escalation_name
):
    scenario = {
        "name": "invalid escalation",
        "capital_cost": 100,
        "annual_output_mwh": 10,
        "project_life_years": 1,
        schedule_name: [1],
        escalation_name: float("nan"),
    }

    with pytest.raises(ValueError, match="escalation.*finite"):
        xi.evaluate_technology_cost_scenario(scenario)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_technology_cost_rejects_nonfinite_output_degradation(value):
    with pytest.raises(ValueError, match="output_degradation must be finite"):
        xi.evaluate_technology_cost_scenario(
            {
                "name": "invalid degradation",
                "capital_cost": 100,
                "annual_output_mwh": 10,
                "project_life_years": 1,
                "output_degradation": value,
            }
        )
