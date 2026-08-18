import json
import tomllib
from pathlib import Path

import pytest

import exergy_imperative as xi
from exergy_imperative.agent import LIBRARY_VERSION
from exergy_imperative.cli import main


def test_release_version_surfaces_are_consistent(capsys):
    project_root = Path(__file__).parents[1]
    pyproject = tomllib.loads(
        (project_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    expected = pyproject["project"]["version"]
    readme = (project_root / "README.md").read_text(encoding="utf-8")

    assert expected == "0.6.0"
    assert xi.__version__ == expected
    assert LIBRARY_VERSION == expected
    assert f"cacheSeconds=300&release={expected}" in readme

    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"exergy-imperative {expected}"


def test_registry_alias_lookup():
    registry = xi.get_default_registry()
    assert registry.get("technology", "gas boiler").id == "natural-gas-boiler"
    assert len(registry.list("service")) >= 5


def test_custom_profile_pack(tmp_path):
    pack = tmp_path / "pack.json"
    pack.write_text(
        json.dumps(
            {
                "data_version": "site-1",
                "sources": {
                    "site": {
                        "title": "Site heater performance study",
                        "url": "https://example.com/site-study",
                    }
                },
                "profiles": {
                    "technology": [
                        {
                            "id": "site-heater",
                            "label": "Site heater",
                            "aliases": ["heater 1"],
                            "model": "converter",
                            "input_carrier": "electricity",
                            "default_service": "space-heating",
                            "performance_parameter": "efficiency",
                            "source_id": "site",
                            "parameters": {
                                "efficiency": {
                                    "value": 0.99,
                                    "unit": "dimensionless",
                                    "low": 0.98,
                                    "high": 1.0,
                                }
                            },
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    registry = xi.load_registry_pack(pack)
    result = xi.assess(technology="heater 1", registry=registry)
    assert result.parameters["efficiency"].value == pytest.approx(0.99)
    assert "site-1" in result.registry_version
    assert result.carrier_id == "electricity"
    assert result.impacts().aggregate_grid_co2e_kg > 0
    report_source = next(
        item for item in xi.report_view(result).sources if item["source_id"] == "site"
    )
    assert report_source["title"] == "Site heater performance study"
    assert report_source["url"] == "https://example.com/site-study"


def test_dataset_catalog():
    assert xi.dataset_info("xai4heat").license == "CC-BY-4.0"
    assert {record.id for record in xi.list_datasets()} >= {
        "xai4heat",
        "fied",
        "nasa-power",
    }


def test_packaged_schema_and_profiles():
    schema = xi.load_assessment_schema()
    profiles = xi.load_bundled_profiles()
    assert schema["$id"] == xi.ASSESSMENT_SCHEMA_ID
    assert profiles["data_version"] == "2026.2"
    assert xi.load_schema("environmental")["$id"] == xi.ENVIRONMENTAL_SCHEMA_ID
    assert xi.load_schema("economic")["$id"] == xi.ECONOMIC_SCHEMA_ID
    assert xi.load_schema("process")["$id"] == xi.PROCESS_SCHEMA_ID
    assert xi.load_schema("ghg-boundary")["$id"] == xi.GHG_BOUNDARY_SCHEMA_ID
    assert xi.load_schema("methane-project")["$id"] == xi.METHANE_PROJECT_SCHEMA_ID
    assert (
        xi.load_schema("technology-economic")["$id"] == xi.TECHNOLOGY_ECONOMIC_SCHEMA_ID
    )
    assert (
        xi.load_schema("weather-normalization")["$id"]
        == xi.WEATHER_NORMALIZATION_SCHEMA_ID
    )
    assert len(xi.load_bundled_grid_factors()["records"]) >= 1200
    assert xi.load_bundled_impact_factors()["gwp_sets"]["AR6"]
    assert len(xi.load_bundled_process_templates()["templates"]) == 12


def test_cli_assess_json(capsys):
    code = main(["assess", "--carrier", "electricity", "--energy", "1", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"]["exergy_factor"]["value"] == pytest.approx(1)


def test_cli_strict_error(capsys):
    code = main(["assess", "--technology", "gas boiler", "--strict"])
    assert code == 2
    assert "strict mode" in capsys.readouterr().err


def test_cli_json_command_rejects_unknown_options_without_traceback(tmp_path, capsys):
    payload = tmp_path / "economics.json"
    payload.write_text(
        json.dumps({"capital_cost": 1, "misspelled_option": 2}), encoding="utf-8"
    )
    assert main(["economics", str(payload)]) == 2
    error = capsys.readouterr().err
    assert error.startswith("error:")
    assert "misspelled_option" in error


def test_cli_balance(tmp_path, capsys):
    path = tmp_path / "balance.json"
    path.write_text(
        json.dumps(
            {
                "name": "test",
                "inputs": [{"name": "input", "exergy": 100}],
                "products": [{"name": "product", "exergy": 40}],
            }
        ),
        encoding="utf-8",
    )
    assert main(["balance", str(path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["destruction_exergy"] == pytest.approx(60)


def test_cli_factors_impacts_and_process(capsys):
    assert main(["factors", "grid", "--location", "USA", "--year", "2025"]) == 0
    grid = json.loads(capsys.readouterr().out)
    assert grid["country"] == "United States"

    assert main(["factors", "grid", "--year", "2020"]) == 0
    all_grid = json.loads(capsys.readouterr().out)
    assert all(item["requested_year"] == 2020 for item in all_grid)
    assert all(item["year"] <= 2020 for item in all_grid)

    assert (
        main(
            [
                "impacts",
                "--energy",
                "10",
                "--carrier",
                "electricity",
                "--country",
                "France",
                "--refrigerant",
                "R134a=1",
            ]
        )
        == 0
    )
    impacts = json.loads(capsys.readouterr().out)
    assert impacts["climate"]["co2e100_kg"] > 1_500

    assert main(["process", "compressed air", "--energy", "100"]) == 0
    assert "Compressed-air system" in capsys.readouterr().out


def test_cli_impacts_without_energy_preserves_normalized_basis(capsys):
    assert main(["impacts", "--carrier", "electricity", "--country", "France"]) == 0
    impacts = json.loads(capsys.readouterr().out)

    assert impacts["normalized"] is True
    assert impacts["assumptions"]["energy"].startswith("normalized per 1 MWh")


def test_cli_process_economics_accepts_explicit_annualization(capsys):
    assert (
        main(
            [
                "process",
                "steam",
                "--energy",
                "100",
                "--capital-cost",
                "1000",
                "--annualization-factor",
                "1",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["annualization_factor"] == 1
    assert payload["economics"]["npv"] is not None


def test_cli_economics_rejects_boolean_project_life_without_traceback(tmp_path, capsys):
    path = tmp_path / "invalid-economics.json"
    path.write_text(
        json.dumps({"capital_cost": 100, "project_life_years": True}),
        encoding="utf-8",
    )

    assert main(["economics", str(path)]) == 2
    captured = capsys.readouterr()
    assert "project_life_years must be a finite integer" in captured.err
    assert "Traceback" not in captured.err


def test_cli_economics_ingestion_and_report(tmp_path, capsys):
    economics = tmp_path / "economics.json"
    economics.write_text(
        json.dumps(
            {
                "capital_cost": 1000,
                "annual_energy_savings_mwh": 10,
                "energy_price_per_mwh": 100,
                "project_life_years": 3,
            }
        )
    )
    assert main(["economics", str(economics)]) == 0
    assert json.loads(capsys.readouterr().out)["npv"] > 1_000

    data = tmp_path / "data.csv"
    data.write_text("Energy (kWh),Fuel\n1000,natural gas\n")
    normalized = tmp_path / "normalized.csv"
    bundle = tmp_path / "excel"
    assert (
        main(
            [
                "ingest",
                str(data),
                "--output",
                str(normalized),
                "--excel-bundle",
                str(bundle),
                "--required",
                "energy",
            ]
        )
        == 0
    )
    ingest_summary = json.loads(capsys.readouterr().out)
    assert ingest_summary["normalized_record_count"] == 1
    assert normalized.exists()

    recipe = tmp_path / "recipe.json"
    recipe.write_text(
        json.dumps(
            {
                "template": "steam",
                "energy": 100,
                "country": "USA",
            }
        )
    )
    html = tmp_path / "report.html"
    report_bundle = tmp_path / "report-data"
    assert (
        main(
            [
                "report",
                str(recipe),
                "--html",
                str(html),
                "--excel-dir",
                str(report_bundle),
            ]
        )
        == 0
    )
    outputs = json.loads(capsys.readouterr().out)["outputs"]
    assert str(html) in outputs
    assert html.exists()


def test_cli_user_supplied_ghg_methane_technology_and_weather(tmp_path, capsys):
    ghg = tmp_path / "ghg.json"
    ghg.write_text(json.dumps({"fugitive_gases_kg": {"CH4-fossil": 1}}))
    assert main(["ghg-boundaries", str(ghg)]) == 0
    assert json.loads(capsys.readouterr().out)["totals"]["co2e100_kg"] == pytest.approx(
        29.8
    )

    methane = tmp_path / "methane.json"
    methane.write_text(json.dumps({"annual_methane_mass_kg": 100}))
    assert main(["methane", str(methane)]) == 0
    assert json.loads(capsys.readouterr().out)["avoided"]["co2e100_kg"] > 0

    technology = tmp_path / "technology.json"
    technology.write_text(
        json.dumps(
            {
                "name": "user case",
                "capital_cost": 1000,
                "annual_output_mwh": 100,
                "project_life_years": 2,
            }
        )
    )
    assert main(["technology-cost", str(technology)]) == 0
    assert json.loads(capsys.readouterr().out)["levelized_cost_per_mwh"] > 0

    weather = tmp_path / "weather.csv"
    weather.write_text("date,temperature_c,energy\n2026-01-01,0,20\n2026-01-02,10,10\n")
    assert (
        main(
            [
                "weather-normalize",
                str(weather),
                "--value-field",
                "energy",
                "--normal-hdd",
                "20",
                "--normal-cdd",
                "0",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["normalized_total"] > 0


def test_cli_excel_engineering_waste_heat_adapter_and_validation(tmp_path, capsys):
    openpyxl = pytest.importorskip("openpyxl")
    template = tmp_path / "steam.xlsx"
    report = tmp_path / "steam-report.xlsx"
    assert main(["excel-template", "steam", str(template)]) == 0
    assert json.loads(capsys.readouterr().out)["output"] == str(template)
    assert main(["excel-run", str(template), "--output", str(report)]) == 0
    excel_run = json.loads(capsys.readouterr().out)
    assert excel_run["result"]["model_id"] == "industrial.steam-system.v1"
    assert report.exists()

    engineering = tmp_path / "engineering.json"
    engineering.write_text(
        json.dumps(
            {
                "delivered_heat_mwh": 100,
                "source_temperature_c": 10,
                "sink_temperature_c": 60,
                "cop": 3,
            }
        )
    )
    assert main(["engineering", "heat-pump", str(engineering)]) == 0
    assert json.loads(capsys.readouterr().out)["model_id"] == "industrial.heat-pump.v1"

    waste_heat = tmp_path / "waste-heat.json"
    waste_heat.write_text(
        json.dumps(
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
            }
        )
    )
    assert main(["waste-heat", str(waste_heat)]) == 0
    assert json.loads(capsys.readouterr().out)["totals"]["heat_recovered_mwh"] == 10

    source = tmp_path / "source.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(["Location", 2025])
    sheet.append(["A", 1.5])
    workbook.save(source)
    adapter = tmp_path / "adapter.json"
    adapter.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "id": "cli-test",
                "source_name": "test",
                "license_notice": "user supplied",
                "sheet_name": "Data",
                "layout": "wide-years",
                "id_columns": ["Location"],
                "fields": [
                    {"source": "Location", "target": "location"},
                    {"source": "year", "target": "year", "data_type": "integer"},
                    {"source": "value", "target": "value", "data_type": "number"},
                ],
                "required": ["location", "year", "value"],
                "preserve_unmapped": False,
            }
        )
    )
    output = tmp_path / "adapted.csv"
    assert (
        main(["adapt-local", str(source), str(adapter), "--output", str(output)]) == 0
    )
    adapted = json.loads(capsys.readouterr().out)
    assert adapted["ingestion"]["normalized_record_count"] == 1
    assert output.exists()

    assert main(["validate"]) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True

    assert main(["validate", "--coverage"]) == 0
    coverage = json.loads(capsys.readouterr().out)
    assert coverage["coverage_version"]
    assert any(item["level"] == "screening-only" for item in coverage["items"])


def test_cli_ingest_numeric_sheet_selector_uses_sheet_index(tmp_path, capsys):
    openpyxl = pytest.importorskip("openpyxl")
    source = tmp_path / "sheets.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.title = "First"
    second = workbook.create_sheet("Second")
    second.append(["Energy (MWh)"])
    second.append([2])
    workbook.save(source)
    workbook.close()

    output = tmp_path / "normalized.json"
    assert (
        main(
            [
                "ingest",
                str(source),
                "--sheet",
                "1",
                "--output",
                str(output),
                "--required",
                "energy",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["normalized_record_count"] == 1
    assert json.loads(output.read_text())[0]["energy"] == pytest.approx(2)


def test_cli_ingest_supports_mapping_review_only(tmp_path, capsys):
    source = tmp_path / "telemetry.csv"
    source.write_text("Energy (MWh)\n1\n", encoding="utf-8")
    mapping = tmp_path / "mapping.json"

    assert main(["ingest", str(source), "--mapping-out", str(mapping)]) == 0
    assert mapping.exists()
    assert (
        json.loads(mapping.read_text(encoding="utf-8"))["fields"][0]["target"]
        == "energy"
    )
    assert json.loads(capsys.readouterr().out)["normalized_record_count"] == 1


def test_cli_ingest_merges_requirements_into_loaded_mapping(tmp_path, capsys):
    source = tmp_path / "telemetry.csv"
    source.write_text("value,site\n,A\n", encoding="utf-8")
    mapping_path = tmp_path / "mapping.json"
    xi.write_mapping(
        xi.MappingPlan(fields=(xi.FieldMapping("value", "energy", "MWh"),)),
        mapping_path,
    )
    output = tmp_path / "normalized.json"

    assert (
        main(
            [
                "ingest",
                str(source),
                "--mapping",
                str(mapping_path),
                "--required",
                "energy",
                "--missing-policy",
                "drop",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    assert summary["dropped_rows"] == [1]
    assert json.loads(output.read_text(encoding="utf-8")) == []


def test_cli_ingest_uses_missing_policy_saved_in_mapping(tmp_path, capsys):
    source = tmp_path / "telemetry.csv"
    source.write_text("value,site\n,A\n", encoding="utf-8")
    mapping_path = tmp_path / "mapping.json"
    xi.write_mapping(
        xi.MappingPlan(
            fields=(xi.FieldMapping("value", "energy", "MWh"),),
            required=("energy",),
            missing_policy="drop",
        ),
        mapping_path,
    )
    output = tmp_path / "normalized.json"

    assert (
        main(
            [
                "ingest",
                str(source),
                "--mapping",
                str(mapping_path),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    assert summary["missing_policy"] == "drop"
    assert summary["dropped_rows"] == [1]
    assert json.loads(output.read_text(encoding="utf-8")) == []


def test_cli_ingest_timezone_overrides_loaded_mapping(tmp_path, capsys):
    source = tmp_path / "telemetry.csv"
    source.write_text("when\n2026-01-01T12:00:00\n", encoding="utf-8")
    mapping_path = tmp_path / "mapping.json"
    xi.write_mapping(
        xi.MappingPlan(fields=(xi.FieldMapping("when", "timestamp"),), timezone="UTC"),
        mapping_path,
    )
    output = tmp_path / "normalized.json"

    assert (
        main(
            [
                "ingest",
                str(source),
                "--mapping",
                str(mapping_path),
                "--timezone",
                "America/Denver",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert json.loads(output.read_text(encoding="utf-8"))[0]["timestamp"].endswith(
        "-07:00"
    )
