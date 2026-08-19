import json

import jsonschema
import pytest

import exergy_imperative as xi
from exergy_imperative.cli import main


def test_agent_capabilities_and_contract_schemas_are_machine_readable():
    capabilities = xi.list_capabilities()
    workflows = {item["id"] for item in capabilities["workflows"]}

    assert capabilities["contract"] == "exergy-agent-capabilities"
    assert workflows >= {
        "assessment",
        "process-assessment",
        "impacts",
        "health-benefits",
        "economics",
        "engineering",
        "normalize-records",
    }
    assert xi.describe_workflow("calculate_exergy")["id"] == "assessment"
    assert xi.describe_target("steam")["kind"] == "process"
    assert xi.describe_target("natural gas", kind="profile")["items"]
    jsonschema.validate(capabilities, xi.load_schema("agent-capabilities"))

    engineering = xi.describe_workflow("engineering")["input_schema"]
    heat_pump = engineering["x-model-parameter-schemas"]["heat-pump"]
    assert set(heat_pump["required"]) == {
        "delivered_heat_mwh",
        "source_temperature_c",
        "sink_temperature_c",
        "cop",
    }


def test_agent_recipe_validate_only_has_no_calculation_or_file_write(tmp_path):
    output = tmp_path / "must-not-exist.json"
    response = xi.run_recipe(
        {
            "workflow": "economics",
            "inputs": {"capital_cost": 100},
            "outputs": {"json": str(output)},
        },
        mode="validate-only",
    ).to_dict()

    assert response["ok"]
    assert response["mode"] == "validate-only"
    assert response["plan"]["will_execute_calculations"] is False
    assert response["plan"]["will_write_files"] is False
    assert "result" not in response
    assert not output.exists()
    jsonschema.validate(response, xi.load_schema("agent-response"))


def test_agent_recipe_dry_run_calculates_but_suppresses_outputs(tmp_path):
    output = tmp_path / "suppressed.json"
    response = xi.run_recipe(
        {
            "workflow": "assessment",
            "inputs": {"technology": "air-source heat pump"},
            "outputs": {"json": str(output)},
        },
        mode="dry-run",
    ).to_dict()

    assert response["result"]["tier"] == "F1"
    assert response["plan"]["suppressed_outputs"]["json"] == str(output)
    assert response["artifacts"] == []
    assert not output.exists()


def test_agent_recipe_execute_writes_only_requested_artifacts(tmp_path):
    json_path = tmp_path / "assessment.json"
    html_path = tmp_path / "assessment.html"
    response = xi.run_recipe(
        {
            "workflow": "assessment",
            "inputs": {
                "technology": "natural-gas boiler",
                "energy": 100,
            },
            "outputs": {"json": str(json_path), "html": str(html_path)},
        }
    ).to_dict()

    assert json_path.exists()
    assert html_path.exists()
    assert {item["format"] for item in response["artifacts"]} == {"json", "html"}
    assert json.loads(json_path.read_text(encoding="utf-8"))["tier"] == "F1"


def test_agent_economics_workflow_writes_advertised_reports(tmp_path):
    html_path = tmp_path / "economics.html"
    xlsx_path = tmp_path / "economics.xlsx"
    excel_directory = tmp_path / "economics-excel"
    response = xi.run_recipe(
        {
            "workflow": "economics",
            "inputs": {
                "capital_cost": 1000,
                "annual_energy_savings_mwh": 100,
                "energy_price_per_mwh": 50,
            },
            "outputs": {
                "html": str(html_path),
                "xlsx": str(xlsx_path),
                "excel_directory": str(excel_directory),
            },
        }
    ).to_dict()

    assert html_path.exists()
    assert xlsx_path.exists()
    assert (excel_directory / "summary.csv").exists()
    assert {artifact["format"] for artifact in response["artifacts"]} == {
        "html",
        "xlsx",
        "excel_directory",
    }


@pytest.mark.parametrize(
    ("workflow", "inputs", "result_key"),
    (
        ("assessment", {"carrier": "electricity"}, "tier"),
        ("process-assessment", {"template": "steam", "energy": 10}, "template"),
        ("impacts", {"carrier": "electricity", "country": "USA"}, "climate"),
        (
            "health-benefits",
            {"region": "Texas", "project_type": "Onshore wind"},
            "monetized_benefit",
        ),
        ("ghg-boundaries", {"fugitive_gases_kg": {"CH4-fossil": 1}}, "totals"),
        ("methane-project", {"annual_methane_mass_kg": 10}, "avoided"),
        ("economics", {"capital_cost": 100}, "npv"),
        (
            "technology-cost",
            {"name": "case", "capital_cost": 100, "annual_output_mwh": 10},
            "scenario",
        ),
        (
            "engineering",
            {
                "model": "heat-pump",
                "parameters": {
                    "delivered_heat_mwh": 100,
                    "source_temperature_c": 10,
                    "sink_temperature_c": 60,
                    "cop": 3,
                },
            },
            "model_id",
        ),
        (
            "waste-heat",
            {
                "sources": [
                    {
                        "name": "hot",
                        "available_heat_mwh": 20,
                        "supply_temperature_c": 120,
                        "minimum_outlet_temperature_c": 60,
                    }
                ],
                "demands": [
                    {
                        "name": "warm",
                        "required_heat_mwh": 10,
                        "supply_temperature_c": 80,
                        "return_temperature_c": 40,
                    }
                ],
            },
            "matches",
        ),
        (
            "exergy-balance",
            {
                "name": "plant",
                "inputs": [{"name": "fuel", "exergy": 10}],
                "products": [{"name": "product", "exergy": 4}],
            },
            "destruction_exergy",
        ),
        (
            "normalize-records",
            {"records": [{"Energy (kWh)": 1000, "Fuel": "natural gas"}]},
            "records",
        ),
        (
            "weather-normalization",
            {
                "records": [
                    {"date": "2026-01-01", "temperature_c": 0, "energy": 20},
                    {"date": "2026-01-02", "temperature_c": 10, "energy": 10},
                ],
                "value_field": "energy",
                "normal_heating_degree_days": 20,
                "normal_cooling_degree_days": 0,
            },
            "normalized_total",
        ),
        ("validation-suite", {}, "passed"),
    ),
)
def test_agent_recipe_dispatches_supported_workflows(workflow, inputs, result_key):
    response = xi.run_recipe({"workflow": workflow, "inputs": inputs}).to_dict()
    assert response["ok"]
    assert result_key in response["result"]


def test_agent_safe_errors_include_codes_hints_and_recovery_fields():
    missing = xi.safe_run_recipe(
        {"workflow": "economics", "inputs": {}}, mode="validate-only"
    )
    assert missing["error"]["code"] == "MISSING_INPUT"
    assert missing["error"]["suggested_fields"] == ["capital_cost"]

    basis = xi.safe_run_recipe(
        {"workflow": "impacts", "inputs": {"gases_kg": {"CO2": 1}}}
    )
    assert basis["error"]["code"] == "MISSING_ENERGY_BASIS"
    assert basis["error"]["suggested_fields"] == ["energy", "unit"]
    assert "gas_factors_kg_per_mwh" in basis["error"]["hint"]
    jsonschema.validate(basis, xi.load_schema("agent-response"))


def test_agent_recipe_rejects_unknown_root_and_input_fields():
    root = xi.safe_run_recipe(
        {"workflow": "assessment", "inputs": {}, "surprise": True}
    )
    assert root["error"]["code"] == "UNKNOWN_RECIPE_FIELD"

    field = xi.safe_run_recipe({"workflow": "assessment", "inputs": {"efficency": 0.9}})
    assert field["error"]["code"] == "UNKNOWN_INPUT_FIELD"

    missing_inputs = xi.safe_run_recipe({"workflow": "validation-suite"})
    assert missing_inputs["error"]["code"] == "MISSING_INPUT"


def test_agent_validate_only_checks_input_types_and_enum_values():
    wrong_type = xi.safe_run_recipe(
        {"workflow": "economics", "inputs": {"capital_cost": "expensive"}},
        mode="validate-only",
    )
    assert wrong_type["error"]["code"] == "INVALID_INPUT_TYPE"
    assert wrong_type["error"]["suggested_fields"] == ["capital_cost"]

    wrong_enum = xi.safe_run_recipe(
        {
            "workflow": "engineering",
            "inputs": {"model": "perpetual-motion", "parameters": {}},
        },
        mode="validate-only",
    )
    assert wrong_enum["error"]["code"] == "INVALID_INPUT_VALUE"

    temperature_string = xi.safe_run_recipe(
        {
            "workflow": "assessment",
            "inputs": {
                "technology": "natural-gas boiler",
                "source_temperature": "80 C",
            },
        },
        mode="validate-only",
    )
    assert temperature_string["ok"] is True


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_agent_recipe_rejects_nonfinite_numbers(value):
    response = xi.safe_run_recipe(
        {"workflow": "assessment", "inputs": {"energy": value}},
        mode="validate-only",
    )

    assert response["error"]["code"] == "NONFINITE_NUMBER"
    jsonschema.validate(response, xi.load_schema("agent-response"))


def test_agent_response_rejects_nonfinite_result_values():
    with pytest.raises(xi.AgentNativeError, match="strict JSON") as exc_info:
        xi.RecipeResult(
            workflow="assessment",
            mode="dry-run",
            result={"metric": float("nan")},
        ).to_dict()

    assert exc_info.value.code == "NONFINITE_RESULT"


def test_agent_validate_only_checks_nested_array_items():
    response = xi.safe_run_recipe(
        {"workflow": "normalize-records", "inputs": {"records": [1]}},
        mode="validate-only",
    )

    assert response["error"]["code"] == "INVALID_INPUT_TYPE"
    assert response["error"]["details"]["path"] == "records[0]"


def test_agent_validate_only_uses_selected_engineering_parameter_schema():
    response = xi.safe_run_recipe(
        {
            "workflow": "engineering",
            "inputs": {
                "model": "heat-pump",
                "parameters": {"delivered_heat_mwh": 100},
            },
        },
        mode="validate-only",
    )

    assert response["error"]["code"] == "MISSING_INPUT"
    assert response["error"]["suggested_fields"] == ["parameters"]
    assert "cop" in response["error"]["details"]["missing_fields"]


def test_agent_validate_only_checks_nested_domain_objects():
    response = xi.safe_run_recipe(
        {
            "workflow": "exergy-balance",
            "inputs": {
                "name": "plant",
                "inputs": [{"name": "fuel"}],
                "products": [{"name": "product", "exergy": 4}],
            },
        },
        mode="validate-only",
    )

    assert response["error"]["code"] == "MISSING_INPUT"
    assert response["error"]["details"]["path"] == "inputs[0]"
    assert response["error"]["details"]["missing_fields"] == ["exergy"]


def test_agent_invalid_mode_error_still_matches_response_schema():
    response = xi.safe_run_recipe(
        {"workflow": "assessment", "inputs": {}, "mode": "unsafe"}
    )

    assert response["error"]["code"] == "INVALID_RECIPE_MODE"
    assert "mode" not in response
    jsonschema.validate(response, xi.load_schema("agent-response"))


def test_agent_cli_discovery_recipe_modes_and_universal_json(tmp_path, capsys):
    assert main(["capabilities", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["workflows"]

    assert main(["--json", "schema", "agent-recipe"]) == 0
    assert json.loads(capsys.readouterr().out)["$id"] == xi.AGENT_RECIPE_SCHEMA_ID

    assert main(["describe", "steam", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "process"

    recipe = tmp_path / "recipe.json"
    recipe.write_text(
        json.dumps(
            {
                "workflow": "assessment",
                "inputs": {"technology": "air-source heat pump"},
            }
        ),
        encoding="utf-8",
    )
    assert main(["run", str(recipe), "--validate-only", "--json"]) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["mode"] == "validate-only"

    assert main(["run", str(recipe), "--dry-run", "--json"]) == 0
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["result"]["tier"] == "F1"


def test_agent_cli_json_errors_are_structured(tmp_path, capsys):
    recipe = tmp_path / "invalid.json"
    recipe.write_text(
        json.dumps({"workflow": "economics", "inputs": {}}), encoding="utf-8"
    )

    assert main(["run", str(recipe), "--validate-only", "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["ok"] is False
    assert error["error"]["code"] == "MISSING_INPUT"


def test_agent_cli_json_parse_errors_are_structured(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["assess", "--not-a-real-option", "--json"])
    assert exit_info.value.code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["code"] == "INVALID_INPUT"


def test_agent_cli_json_mode_converts_prose_only_command_output(tmp_path, capsys):
    source = tmp_path / "telemetry.csv"
    output = tmp_path / "enriched.csv"
    source.write_text(
        "timestamp,ambient_temperature,primary_supply_temperature,energy_mwh\n"
        "2026-01-01T00:00:00Z,10,80,1\n",
        encoding="utf-8",
    )

    assert main(["enrich", str(source), "--output", str(output), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"output": str(output), "record_count": 1}
