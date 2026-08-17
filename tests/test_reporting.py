import csv
import json

import pytest

import exergy_imperative as xi


@pytest.fixture
def process_result():
    return xi.assess_process(
        "steam",
        1000,
        country="USA",
        annualization_factor=1.0,
        economics_options={
            "capital_cost": 100_000,
            "energy_price_per_mwh": 80,
            "project_life_years": 10,
        },
    )


def test_basic_svg_charts_are_accessible(process_result):
    view = xi.report_view(process_result)
    assert len(view.charts) >= 3
    svg = xi.svg_bar_chart(view.charts[0])
    assert svg.startswith("<svg")
    assert 'role="img"' in svg
    assert "<title" in svg
    assert "sankey" not in svg.lower()


def test_svg_chart_expands_view_box_for_many_bars():
    spec = xi.ChartSpec(
        "many-bars",
        "Many bars",
        "kg",
        tuple((f"Pollutant {index}", float(index)) for index in range(10)),
        "#0F766E",
    )
    svg = xi.svg_bar_chart(spec)
    assert 'viewBox="0 0 760 378"' in svg
    assert svg.count("<rect") == 11


def test_html_report_contains_charts_tables_sources_and_warnings(
    tmp_path, process_result
):
    path = xi.export_html(process_result, tmp_path / "report.html")
    text = path.read_text(encoding="utf-8")
    assert "Industrial steam system assessment" in text
    assert "Climate impact by warming horizon" in text
    assert "Air pollutant and health screening" in text
    assert "Limitations and warnings" in text
    assert "<!doctype html>" in text.lower()


def test_excel_compatible_report_has_traceable_tables(tmp_path, process_result):
    outputs = xi.export_excel_compatible_report(process_result, tmp_path / "excel")
    names = {path.name for path in outputs}
    assert "summary.csv" in names
    assert "report-metadata.json" in names
    assert "sources.csv" in names
    with (tmp_path / "excel" / "summary.csv").open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["metric"] for row in rows} >= {
        "Exergetic efficiency",
        "Climate impact - 100 year",
        "Net present value",
    }


def test_pdf_report_writes_valid_pdf(tmp_path, process_result):
    pytest.importorskip("reportlab")
    path = xi.export_pdf(process_result, tmp_path / "report.pdf")
    assert path.read_bytes().startswith(b"%PDF")
    assert path.stat().st_size > 5000


def test_normalized_assessment_reports_make_the_per_mwh_basis_explicit(tmp_path):
    result = xi.assess(technology="gas boiler")
    view = xi.report_view(result)
    assert "normalized per 1 MWh input" in view.subtitle
    assert view.charts[0].unit == "MWh per 1 MWh input"
    assert any("not absolute" in warning for warning in view.warnings)
    assert any("per 1 MWh input" in unit for _, _, unit in view.key_metrics)
    html = xi.export_html(result, tmp_path / "normalized.html").read_text(
        encoding="utf-8"
    )
    assert "normalized per 1 MWh input" in html


def test_normalized_environmental_reports_make_the_per_mwh_basis_explicit(tmp_path):
    result = xi.assess_impacts(carrier="electricity", country="USA")
    view = xi.report_view(result)
    assert "normalized per 1 MWh input" in view.subtitle
    assert all("MWh input" in unit and "per" in unit for _, _, unit in view.key_metrics)
    assert all("per MWh input" in chart.unit for chart in view.charts)
    assert any("not absolute" in warning for warning in view.warnings)
    html = xi.export_html(result, tmp_path / "normalized-impacts.html").read_text(
        encoding="utf-8"
    )
    assert "normalized per 1 MWh input" in html


def test_normalized_process_reports_make_every_quantity_basis_explicit(tmp_path):
    result = xi.assess_process("steam")
    assert result.normalized is True
    assert result.to_dict()["normalized"] is True
    assert "normalized per 1 MWh of input" in result.summary()
    assert result.opportunity.energy_savings.unit == "MWh per 1 MWh input"
    assert result.opportunity.co2e100_reduction.unit == "kg CO2e per 1 MWh input"

    view = xi.report_view(result)
    assert "normalized per 1 MWh input" in view.subtitle
    quantity_units = {
        unit
        for label, _, unit in view.key_metrics
        if label not in {"Fidelity", "Exergetic efficiency"}
    }
    assert quantity_units
    assert all("per 1 MWh input" in unit for unit in quantity_units)
    assert all("per 1 MWh input" in chart.unit for chart in view.charts)
    assert any("not absolute" in warning for warning in view.warnings)
    assert all(
        "per 1 MWh input" in table_name
        for table_name in view.tables
        if table_name
        in {
            "Climate contributions (per 1 MWh input)",
            "Air pollutant and health screening (per 1 MWh input)",
            "Improvement opportunity (per 1 MWh input)",
        }
    )

    html = xi.export_html(result, tmp_path / "normalized-process.html").read_text(
        encoding="utf-8"
    )
    assert "normalized per 1 MWh input" in html
    outputs = xi.export_excel_compatible_report(result, tmp_path / "normalized-process")
    assert outputs
    with (tmp_path / "normalized-process" / "summary.csv").open(
        encoding="utf-8-sig"
    ) as handle:
        rows = list(csv.DictReader(handle))
    quantity_rows = [
        row for row in rows if row["metric"] not in {"Fidelity", "Exergetic efficiency"}
    ]
    assert all("per 1 MWh input" in row["unit"] for row in quantity_rows)


def test_html_reports_do_not_link_user_controlled_unsafe_source_schemes(tmp_path):
    pack = tmp_path / "unsafe-source.json"
    pack.write_text(
        json.dumps(
            {
                "data_version": "unsafe-source-test",
                "sources": {
                    "unsafe": {
                        "title": "Untrusted source",
                        "url": "javascript:alert(1)",
                    }
                },
                "profiles": {
                    "carrier": [
                        {
                            "id": "test-carrier",
                            "label": "Test carrier",
                            "source_id": "unsafe",
                            "parameters": {
                                "exergy_factor": {
                                    "value": 1,
                                    "unit": "MWh_ex/MWh",
                                }
                            },
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    result = xi.assess(carrier="test-carrier", registry=xi.load_registry_pack(pack))
    html = xi.export_html(result, tmp_path / "unsafe.html").read_text(encoding="utf-8")
    assert "javascript:alert(1)" in html
    assert "href='javascript:" not in html


def test_new_weather_methane_and_technology_results_use_common_exports(tmp_path):
    ghg = xi.assess_ghg_boundaries(fugitive_gases_kg={"CH4-fossil": 100})
    ghg_html = ghg.export_html(tmp_path / "ghg.html")
    assert "Greenhouse-gas boundary assessment" in ghg_html.read_text(encoding="utf-8")

    weather = xi.normalize_weather_performance(
        [
            {"date": "2026-01-01", "temperature_c": 0, "energy": 20},
            {"date": "2026-01-02", "temperature_c": 10, "energy": 10},
        ],
        value_field="energy",
        unit="MWh",
        normal_heating_degree_days=20,
        normal_cooling_degree_days=0,
    )
    weather_html = weather.export_html(tmp_path / "weather.html")
    assert "Weather-normalized energy" in weather_html.read_text(encoding="utf-8")

    methane = xi.assess_methane_project(
        annual_methane_mass_kg=100,
        project_efficiency=0.9,
    )
    methane_outputs = methane.export_excel_compatible(tmp_path / "methane")
    assert {path.name for path in methane_outputs} >= {
        "summary.csv",
        "01-disposition-comparison.csv",
    }

    technology = xi.evaluate_technology_cost_scenario(
        {
            "name": "heat pump",
            "capital_cost": 1000,
            "annual_output_mwh": 100,
            "output_name": "useful heat",
            "project_life_years": 2,
        }
    )
    technology_view = xi.report_view(technology)
    assert technology_view.title == "heat pump economics"
    assert "Annual economics" in technology_view.tables

    for name, result in (
        ("ghg", ghg),
        ("weather", weather),
        ("methane", methane),
        ("technology", technology),
    ):
        pdf_path = result.export_pdf(tmp_path / f"{name}.pdf")
        assert pdf_path.read_bytes().startswith(b"%PDF")


def test_long_xlsx_metadata_chunks_neutralize_formula_prefixes(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")

    def scenario(padding_length):
        return xi.evaluate_technology_cost_scenario(
            {
                "name": "safe metadata",
                "capital_cost": 1,
                "annual_output_mwh": 1,
                "metadata": {"padding": "A" * padding_length, "zzz": "=1+1"},
            }
        )

    base = scenario(0)
    payload = json.dumps(
        xi.report_view(base).payload, ensure_ascii=False, sort_keys=True
    )
    padding_length = 30000 - payload.find("=1+1")
    result = scenario(padding_length)
    payload = json.dumps(
        xi.report_view(result).payload, ensure_ascii=False, sort_keys=True
    )
    assert payload.find("=1+1") == 30000

    path = result.export_xlsx(tmp_path / "safe-metadata.xlsx")
    workbook = openpyxl.load_workbook(path, data_only=False)
    metadata = workbook["Metadata"]
    chunks = {
        metadata.cell(row, 1).value: metadata.cell(row, 2)
        for row in range(2, metadata.max_row + 1)
    }
    assert chunks["source_payload_2"].data_type == "s"
    assert chunks["source_payload_2"].value.startswith("'=1+1")
    workbook.close()


def test_process_report_resolves_registry_source_metadata(process_result):
    source = next(
        item
        for item in xi.report_view(process_result).sources
        if item["source_id"] == "exergy-imperative-guide-2026"
    )
    assert source["title"] == "The Exergy Imperative"
    assert source["url"].startswith("https://github.com/")
    source_ids = {item["source_id"] for item in xi.report_view(process_result).sources}
    assert "quantity-quality-framework-2026" in source_ids
