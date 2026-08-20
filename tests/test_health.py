import json

import jsonschema
import pytest

import exergy_imperative as xi
from exergy_imperative.cli import main


def test_bundled_epa_bpk_table_is_complete_sourced_and_well_formed():
    data = xi.load_bundled_health_benefit_factors()
    factors = xi.list_health_benefit_factors()

    assert data["data_version"] == "EPA-BPK-2024.12-third-edition"
    assert data["data_year"] == 2023
    assert data["currency_year"] == 2023
    assert data["discount_rate"] == pytest.approx(0.02)
    assert data["source"]["model_versions"] == {"AVERT": "4.3", "COBRA": "5.1"}
    assert data["source"]["source_sha256"] == (
        "db622f674a49aabbbc75366775f543e13cde18e9c2914ae98f4bcdc313c9707f"
    )
    assert data["source"]["license"]
    assert data["source"]["license_url"].startswith("https://www.epa.gov/")
    assert len(data["regions"]) == 14
    assert len(data["project_types"]) == 8
    assert len(factors) == 112
    assert sum(item.available for item in factors) == 104
    assert sum(not item.available for item in factors) == 8
    assert all(
        item.low_cents_per_kwh <= item.high_cents_per_kwh
        for item in factors
        if item.available
    )


def test_epa_reference_values_are_pinned_across_the_published_range():
    expected = {
        ("California", "Utility PV"): (0.69, 1.15),
        ("Carolinas", "Peak EE"): (5.99, 9.40),
        ("Mid-Atlantic", "Offshore wind"): (4.76, 8.11),
        ("Midwest", "Peak EE"): (6.73, 11.39),
        ("New England", "Onshore wind"): (0.92, 1.56),
        ("New York", "Distributed PV-plus-storage"): (4.81, 8.95),
        ("Northwest", "Utility PV-plus-storage"): (1.44, 2.13),
        ("Rocky Mountains", "Uniform EE"): (1.80, 2.73),
        ("Southeast", "Peak EE"): (4.59, 6.26),
        ("Southwest", "Onshore wind"): (0.77, 1.06),
        ("Tennessee", "Distributed PV"): (3.41, 5.94),
        ("Texas", "Utility PV"): (3.09, 4.85),
    }
    factors = {
        (item.region, item.project_type): (
            item.low_cents_per_kwh,
            item.high_cents_per_kwh,
        )
        for item in xi.list_health_benefit_factors()
    }
    for key, value in expected.items():
        assert factors[key] == value


def test_health_benefit_calculation_preserves_range_boundary_and_schema():
    result = xi.estimate_health_benefits(
        "Rocky Mountains", "Uniform EE", energy=1, unit="MWh"
    )
    payload = result.to_dict()

    assert result.tier == xi.FidelityTier.F1
    assert result.factor_origin == "EPA-published"
    assert result.benefit_rate.value == pytest.approx(2.265)
    assert result.benefit_rate.low == pytest.approx(1.80)
    assert result.benefit_rate.high == pytest.approx(2.73)
    assert result.monetized_benefit.value == pytest.approx(22.65)
    assert result.monetized_benefit.low == pytest.approx(18.0)
    assert result.monetized_benefit.high == pytest.approx(27.3)
    assert payload["boundaries"]["decision_grade"] is False
    assert payload["time_basis"] == "annual"
    assert payload["boundaries"]["valid_analysis_years"] == [2018, 2028]
    assert "midpoint" in payload["assumptions"]["central_value"]
    assert "not a site-specific exposure" in payload["warnings"][0]
    json.dumps(payload, allow_nan=False)
    jsonschema.validate(payload, xi.load_schema("health-benefit"))


def test_health_benefits_normalize_when_energy_is_omitted_and_convert_units():
    normalized = xi.estimate_health_benefits("ca", "utility solar")
    half_mwh = xi.estimate_health_benefits(
        "California", "Utility PV", energy=500, unit="kWh"
    )

    assert normalized.normalized is True
    assert normalized.energy.value == pytest.approx(1.0)
    assert normalized.assumptions["energy"].startswith("Normalized per 1 annual")
    assert half_mwh.normalized is False
    assert half_mwh.energy.value == pytest.approx(0.5)
    assert half_mwh.monetized_benefit.low == pytest.approx(3.45)
    assert half_mwh.monetized_benefit.high == pytest.approx(5.75)


def test_health_benefits_allow_explicit_range_override_without_claiming_epa_rate():
    result = xi.estimate_health_benefits(
        "Rocky Mountains",
        "Offshore wind",
        energy=10,
        low_cents_per_kwh=0.5,
        high_cents_per_kwh=1.5,
    )

    assert result.factor_origin == "user-provided"
    assert result.monetized_benefit.value == pytest.approx(100.0)
    assert result.monetized_benefit.low == pytest.approx(50.0)
    assert result.monetized_benefit.high == pytest.approx(150.0)
    assert "User-provided" in result.assumptions["benefit_rate"]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        (
            {"region": "Rocky Mountains", "project_type": "Offshore wind"},
            "did not publish",
        ),
        (
            {
                "region": "California",
                "project_type": "Utility PV",
                "low_cents_per_kwh": 1,
            },
            "must be supplied together",
        ),
        (
            {
                "region": "California",
                "project_type": "Utility PV",
                "low_cents_per_kwh": 2,
                "high_cents_per_kwh": 1,
            },
            "greater than or equal",
        ),
        (
            {"region": "Atlantis", "project_type": "Utility PV"},
            "unknown region",
        ),
        (
            {"region": "California", "project_type": "perpetual motion"},
            "unknown project_type",
        ),
        (
            {
                "region": "California",
                "project_type": "Utility PV",
                "energy": float("nan"),
            },
            "finite",
        ),
        (
            {
                "region": "California",
                "project_type": "Utility PV",
                "analysis_year": True,
            },
            "finite integer",
        ),
        (
            {
                "region": "California",
                "project_type": "Utility PV",
                "energy": True,
            },
            "must be numeric",
        ),
    ),
)
def test_health_benefits_reject_invalid_or_ambiguous_inputs(kwargs, message):
    with pytest.raises(ValueError, match=message):
        xi.estimate_health_benefits(**kwargs)


def test_health_benefits_warn_outside_epa_use_window_without_changing_source_year():
    result = xi.estimate_health_benefits("Texas", "Onshore wind", analysis_year=2035)

    assert result.source_data_year == 2023
    assert result.analysis_year == 2035
    assert any("outside EPA's suggested 2018-2028" in item for item in result.warnings)


def test_health_factor_filtering_never_substitutes_an_unavailable_combination():
    rocky_offshore = xi.list_health_benefit_factors(
        region="Rocky Mountains", project_type="Offshore wind"
    )
    available_only = xi.list_health_benefit_factors(
        region="Rocky Mountains",
        project_type="Offshore wind",
        include_unavailable=False,
    )

    assert len(rocky_offshore) == 1
    assert rocky_offshore[0].available is False
    assert available_only == ()


def test_health_cli_lists_factors_and_calculates_screening_result(capsys):
    assert main(["health-factors", "--region", "Texas", "--available-only"]) == 0
    factors = json.loads(capsys.readouterr().out)
    assert len(factors) == 7
    assert all(item["available"] for item in factors)

    assert (
        main(
            [
                "health-benefits",
                "--region",
                "Rocky Mountains",
                "--project-type",
                "Uniform EE",
                "--energy",
                "1",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["monetized_benefit"]["low"] == pytest.approx(18.0)
    assert result["monetized_benefit"]["high"] == pytest.approx(27.3)


def test_health_agent_contract_supports_validation_dry_run_and_execution():
    inputs = {"region": "Texas", "project_type": "Onshore wind", "energy": 2}
    validated = xi.run_recipe(
        {"workflow": "health-benefits", "inputs": inputs}, mode="validate-only"
    ).to_dict()
    dry_run = xi.run_recipe(
        {"workflow": "public-health", "inputs": inputs}, mode="dry-run"
    ).to_dict()
    executed = xi.run_recipe(
        {"workflow": "health-impact-benefits", "inputs": inputs}
    ).to_dict()

    assert validated["plan"]["will_execute_calculations"] is False
    assert "result" not in validated
    assert dry_run["result"]["tier"] == "F1"
    assert executed["result"]["method_id"] == xi.HEALTH_BENEFIT_METHOD_ID
    assert xi.describe_workflow("health-benefits")["output_schema"]["name"] == (
        "health-benefit"
    )
    workflow = xi.describe_workflow("health-benefits")
    assert (
        "rocky-mountains"
        in workflow["input_schema"]["properties"]["region"]["x-canonical-values"]
    )
    assert (
        "uniform-energy-efficiency"
        in workflow["input_schema"]["properties"]["project_type"]["x-canonical-values"]
    )
    assert xi.list_capabilities()["catalog"]["public_health_benefits"] == {
        "available_factor_count": 104,
        "region_count": 14,
        "project_type_count": 8,
    }
