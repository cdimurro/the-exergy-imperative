import json
from datetime import datetime, time, timedelta, timezone

import pytest

import exergy_imperative as xi

openpyxl = pytest.importorskip("openpyxl")


def test_native_excel_template_roundtrip_and_report(tmp_path):
    template = xi.create_excel_template("heat-pump", tmp_path / "heat-pump.xlsx")
    payload = xi.read_excel_template(template)
    assert payload.kind == "heat-pump"
    assert payload.options["cop"] == pytest.approx(3)
    result = xi.run_excel_template(template)
    report = result.export_xlsx(tmp_path / "result.xlsx")

    workbook = openpyxl.load_workbook(report, data_only=False)
    assert {"Summary", "Model metrics", "Assumptions", "Chart Data", "Metadata"} <= set(
        workbook.sheetnames
    )
    assert workbook["Chart Data"].sheet_state == "hidden"
    assert len(workbook["Summary"]._charts) == 2
    assert workbook["Metadata"]["B4"].value
    workbook.close()


@pytest.mark.parametrize("invalid_header", ["date", None])
def test_editable_excel_data_headers_must_be_unique_and_nonblank(
    tmp_path, invalid_header
):
    template = xi.create_excel_template(
        "weather-normalize", tmp_path / f"invalid-{invalid_header}.xlsx"
    )
    workbook = openpyxl.load_workbook(template)
    workbook["Data"]["B1"] = invalid_header
    workbook.save(template)
    workbook.close()

    with pytest.raises(ValueError, match="headers|header names"):
        xi.read_excel_template(template)
    template.unlink()
    assert not template.exists()


def test_ingestion_xlsx_serializes_offset_aware_raw_datetimes(tmp_path):
    aware = datetime(2026, 1, 2, 3, 4, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    mapping = xi.MappingPlan(fields=(xi.FieldMapping("when", "timestamp"),))
    result = xi.normalize_records([{"when": aware}], mapping=mapping)
    output = result.export_xlsx(tmp_path / "aware-datetime.xlsx")
    workbook = openpyxl.load_workbook(output, data_only=True)
    assert workbook["Raw Data"]["A2"].value == aware.isoformat()
    assert workbook["Normalized Data"]["A2"].value == aware.isoformat()
    workbook.close()


def test_ingestion_xlsx_serializes_offset_aware_time_values(tmp_path):
    aware = time(12, 34, tzinfo=timezone(timedelta(hours=-7)))
    result = xi.normalize_records([{"clock": aware}])
    output = result.export_xlsx(tmp_path / "aware-time.xlsx")
    workbook = openpyxl.load_workbook(output, data_only=True)
    assert workbook["Raw Data"]["A2"].value == aware.isoformat()
    assert workbook["Normalized Data"]["A2"].value == aware.isoformat()
    workbook.close()


def test_ingestion_xlsx_retains_complete_preprocessing_plan(tmp_path):
    mapping = xi.MappingPlan(
        fields=(xi.FieldMapping("when", "timestamp"),),
        defaults={"country": "USA"},
        required=("timestamp",),
        timezone="America/Denver",
        preserve_unmapped=False,
    )
    result = xi.normalize_records(
        [{"when": "2026-01-01T12:00:00"}],
        mapping=mapping,
        missing_policy="drop",
    )
    output = result.export_xlsx(tmp_path / "complete-plan.xlsx")
    workbook = openpyxl.load_workbook(output, data_only=True)
    settings = dict(workbook["Mapping Plan"].iter_rows(min_row=2, values_only=True))
    assert json.loads(settings["fields"]) == [
        {"source": "when", "target": "timestamp", "multiplier": 1.0}
    ]
    assert json.loads(settings["defaults"]) == {"country": "USA"}
    assert json.loads(settings["required"]) == ["timestamp"]
    assert settings["timezone"] == "America/Denver"
    assert settings["preserve_unmapped"] is False
    assert settings["missing_policy"] == "drop"
    workbook.close()


def test_native_and_csv_reports_neutralize_user_formula_text(tmp_path):
    result = xi.evaluate_technology_cost_scenario(
        {
            "name": '=WEBSERVICE("https://example.com")',
            "capital_cost": 100,
            "annual_output_mwh": 10,
            "project_life_years": 1,
            "source": "+untrusted source",
        }
    )
    xlsx_path = result.export_xlsx(tmp_path / "safe-report.xlsx")
    workbook = openpyxl.load_workbook(xlsx_path, data_only=False)
    assert workbook["Summary"]["A1"].data_type == "s"
    assert workbook["Summary"]["A1"].value.startswith("'=")
    assert workbook["Scenario assumptions"]["A2"].value.startswith("'=")
    workbook.close()

    outputs = result.export_excel_compatible(tmp_path / "safe-csv")
    scenario_csv = next(path for path in outputs if "scenario-assumptions" in path.name)
    text = scenario_csv.read_text(encoding="utf-8-sig")
    assert "'=WEBSERVICE" in text
    assert "'+untrusted source" in text


def test_all_native_excel_templates_are_creatable(tmp_path):
    expected = {
        "compressed-air",
        "furnace",
        "ghg-boundaries",
        "heat-pump",
        "methane",
        "process",
        "refrigeration",
        "steam",
        "technology-cost",
        "weather-normalize",
    }
    assert set(xi.list_excel_templates()) == expected
    for kind in expected:
        path = xi.create_excel_template(kind, tmp_path / f"{kind}.xlsx")
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
        assert workbook["README"]["B3"].value == kind
        assert workbook["Inputs"]["A4"].value == "Field"
        workbook.close()


def test_weather_excel_template_runs_after_user_adds_data(tmp_path):
    path = xi.create_excel_template("weather-normalize", tmp_path / "weather.xlsx")
    workbook = openpyxl.load_workbook(path)
    data = workbook["Data"]
    data.append(["2026-01-01", 0, 20])
    data.append(["2026-01-02", 10, 10])
    workbook.save(path)
    workbook.close()

    result = xi.run_excel_template(path)
    assert result.observations == 2
    assert result.actual_total == pytest.approx(30)


def test_local_adapter_reshapes_integer_year_headers_and_writes_xlsx(tmp_path):
    source = tmp_path / "publisher-file.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(["Country", 2024, 2025])
    sheet.append(["A", 10, 12])
    sheet.append(["B", "..", 5])
    workbook.save(source)

    adapter_payload = {
        "schema_version": "1.0",
        "id": "test-wide-years",
        "source_name": "User-owned test workbook",
        "license_notice": "Test data supplied by the user.",
        "sheet_name": "Data",
        "layout": "wide-years",
        "id_columns": ["Country"],
        "fields": [
            {"source": "Country", "target": "location", "data_type": "string"},
            {"source": "year", "target": "year", "data_type": "integer"},
            {"source": "value", "target": "value", "data_type": "number"},
        ],
        "required": ["location", "year", "value"],
        "preserve_unmapped": False,
    }
    result = xi.adapt_local_dataset(source, adapter_payload, missing_policy="drop")
    assert len(result.records) == 3
    assert result.records[0] == {"location": "A", "year": 2024, "value": 10.0}
    assert len(result.source_sha256) == 64
    assert result.ingestion.issue_counts["conversion_error"] == 1
    assert len(result.source_records) == 2
    assert 2024 in result.source_records[0]
    assert len(result.ingestion.raw_records) == 4
    assert result.ingestion.raw_records[2]["year"] == 2024
    issue = next(
        item for item in result.ingestion.issues if item.code == "conversion_error"
    )
    assert issue.row == 3

    output = result.export_xlsx(str(tmp_path / "normalized.xlsx"))
    exported = openpyxl.load_workbook(output, read_only=True)
    assert "Normalized Data" in exported.sheetnames
    assert "Source Data" in exported.sheetnames
    assert "Provenance" in exported.sheetnames
    provenance = dict(exported["Provenance"].iter_rows(min_row=2, values_only=True))
    assert provenance["adapter_id"] == "test-wide-years"
    assert provenance["license_notice"] == "Test data supplied by the user."
    assert provenance["source_sha256"] == result.source_sha256
    assert provenance["source_path"] == str(source.resolve())
    exported.close()

    definition = xi.LocalDatasetAdapter.from_dict(adapter_payload)
    adapter_path = xi.write_local_adapter(definition, tmp_path / "adapter.json")
    assert xi.load_local_adapter(adapter_path) == definition
    assert json.loads(adapter_path.read_text())["schema_version"] == "1.0"


@pytest.mark.parametrize("header_row", [True, float("nan"), float("inf"), 1.5])
def test_local_adapter_rejects_invalid_header_rows(header_row):
    with pytest.raises(ValueError, match="positive one-based"):
        xi.LocalDatasetAdapter(
            id="invalid-header",
            source_name="test",
            license_notice="user supplied",
            fields=(),
            header_row=header_row,
        )


def test_wide_year_adapter_rejects_missing_year_columns(tmp_path):
    source = tmp_path / "changed-layout.csv"
    source.write_text("Country,Value\nA,10\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no year columns matching"):
        xi.adapt_local_dataset(
            source,
            {
                "id": "changed-layout",
                "source_name": "test",
                "license_notice": "user supplied",
                "layout": "wide-years",
                "id_columns": ["Country"],
                "fields": [
                    {"source": "Country", "target": "location"},
                    {"source": "year", "target": "year", "data_type": "integer"},
                    {"source": "value", "target": "value", "data_type": "number"},
                ],
            },
        )


def test_local_adapter_preserves_source_and_transformed_rows(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("Country,value\nA,1\nB,2\n", encoding="utf-8")
    result = xi.adapt_local_dataset(
        source,
        {
            "id": "filter-audit",
            "source_name": "test",
            "license_notice": "user supplied",
            "filters": {"Country": ["A"]},
            "fields": [
                {"source": "Country", "target": "location"},
                {"source": "value", "target": "value", "data_type": "number"},
            ],
            "preserve_unmapped": False,
        },
    )
    assert len(result.records) == 1
    assert len(result.source_records) == 2
    assert result.source_records[1]["Country"] == "B"
    assert len(result.ingestion.raw_records) == 1
    assert result.ingestion.raw_records[0]["Country"] == "A"


def test_local_adapter_accepts_tuple_filter_values(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("Country,value\nA,1\nB,2\nC,3\n", encoding="utf-8")

    result = xi.adapt_local_dataset(
        source,
        {
            "id": "tuple-filter",
            "source_name": "test",
            "license_notice": "user supplied",
            "filters": {"Country": ("A", "B")},
            "fields": [
                {"source": "Country", "target": "location"},
                {"source": "value", "target": "value", "data_type": "number"},
            ],
            "preserve_unmapped": False,
        },
    )

    assert [row["location"] for row in result.records] == ["A", "B"]


def test_bundled_adapters_are_available_by_stable_installed_names():
    assert set(xi.list_bundled_adapters()) == {
        "ei-total-energy-supply",
        "iea-ghg-energy",
    }
    direct = xi.load_bundled_adapter("iea-ghg-energy")
    resolved = xi.load_local_adapter("iea_ghg_energy.json")
    assert direct == resolved
    assert direct.id == "iea-ghg-energy-highlights-long-v1"
    assert "records" not in direct.to_dict()
