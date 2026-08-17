import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

import exergy_imperative as xi
import exergy_imperative.external_data as external_data
from exergy_imperative.cli import main


def test_world_bank_fetch_defaults_are_normalized_and_cacheable(monkeypatch, tmp_path):
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(
                [
                    {"page": 1, "pages": 1},
                    [
                        {
                            "indicator": {"id": "FP.CPI.TOTL", "value": "CPI"},
                            "country": {"id": "US", "value": "United States"},
                            "countryiso3code": "USA",
                            "date": "2024",
                            "value": 135.2,
                            "unit": "index",
                            "obs_status": "",
                        }
                    ],
                ]
            ).encode()

    def request(request, **_kwargs):
        calls.append(request.full_url)
        return Response()

    monkeypatch.setattr(external_data, "urlopen", request)
    first = xi.fetch_world_bank_indicators(
        "usa",
        indicators=("FP.CPI.TOTL",),
        start_year=2024,
        end_year=2024,
        cache_dir=tmp_path,
    )
    second = xi.fetch_world_bank_indicators(
        "USA",
        indicators=("FP.CPI.TOTL",),
        start_year=2024,
        end_year=2024,
        cache_dir=tmp_path,
    )

    assert len(calls) == 1
    assert "date=2024%3A2024" in calls[0]
    assert first.records[0]["country_id"] == "USA"
    assert second.records == first.records
    assert second.to_dict()["source"]["license_notice"].startswith("CC BY")


def test_world_bank_rejects_invalid_inputs_without_network(monkeypatch):
    monkeypatch.setattr(
        external_data,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("network must not be used"),
    )
    with pytest.raises(ValueError, match="on or before"):
        xi.fetch_world_bank_indicators("USA", start_year=2025, end_year=2024)
    with pytest.raises(ValueError, match="unsupported characters"):
        xi.fetch_world_bank_indicators("USA", indicators=("bad/id",))


def test_world_bank_reports_transient_upstream_failure(monkeypatch):
    attempts = []

    def unavailable(request, **_kwargs):
        attempts.append(request.full_url)
        raise HTTPError(request.full_url, 502, "Bad Gateway", {}, None)

    monkeypatch.setattr(external_data, "urlopen", unavailable)
    monkeypatch.setattr(external_data.time, "sleep", lambda _seconds: None)
    with pytest.raises(ConnectionError, match="temporarily unavailable"):
        xi.fetch_world_bank_indicators("USA", indicators=("FP.CPI.TOTL",), retries=2)
    assert len(attempts) == 3


def test_era5_requests_are_monthly_and_retrieval_is_explicit(tmp_path):
    requests = xi.build_era5_land_requests(
        39.74,
        -104.99,
        "2025-01-31",
        "2025-02-02",
        variables=("2m_temperature",),
    )
    assert [item["request"]["day"] for item in requests] == [
        ["31"],
        ["01", "02"],
    ]
    assert requests[0]["request"]["area"] == [39.74, -104.99, 39.74, -104.99]

    class Client:
        def __init__(self):
            self.calls = []

        def retrieve(self, dataset, request, target):
            self.calls.append((dataset, request, target))
            Path(target).write_text("fixture", encoding="utf-8")

    client = Client()
    result = xi.retrieve_era5_land(
        39.74,
        -104.99,
        "2025-01-31",
        "2025-02-02",
        tmp_path,
        variables=("2m_temperature",),
        client=client,
    )
    cached = xi.retrieve_era5_land(
        39.74,
        -104.99,
        "2025-01-31",
        "2025-02-02",
        tmp_path,
        variables=("2m_temperature",),
        client=client,
    )

    assert len(client.calls) == 2
    assert {item["status"] for item in result["outputs"]} == {"downloaded"}
    assert {item["status"] for item in cached["outputs"]} == {"cached"}


def test_edgar_official_workbook_shape_infers_metadata(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    source = tmp_path / "EDGAR_NOx.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "IPCC 2006"
    metadata = [
        ("Content:", "Emissions by country and main source category"),
        ("Compound:", "NOx"),
        ("Start year:", "2020"),
        ("End year:", "2021"),
        ("Unit:", "Gg"),
        ("Reference:", "EDGAR fixture"),
        ("Users:", "acknowledge"),
        ("Data download:", "https://example.com"),
        (None, None),
    ]
    for row in metadata:
        sheet.append(row)
    sheet.append(
        [
            "Country_code_A3",
            "Name",
            "ipcc_code_2006_for_standard_report",
            "ipcc_code_2006_for_standard_report_name",
            "Substance",
            "fossil_bio",
            "Y_2020",
            "Y_2021",
        ]
    )
    sheet.append(
        ["USA", "United States", "1.A.2", "Industry", "NOx", "fossil", 1.5, 2.0]
    )
    workbook.save(source)

    result = xi.load_edgar_inventory(source, start_year=2021)

    assert result.metadata["source_unit"] == "Gg"
    assert result.metadata["reference"] == "EDGAR fixture"
    assert result.records == (
        {
            "country_iso3": "USA",
            "country_name": "United States",
            "sector_code": "1.A.2",
            "sector_name": "Industry",
            "fossil_or_biogenic": "fossil",
            "pollutant": "NOx",
            "year": 2021,
            "source_value": 2.0,
            "source_unit": "Gg",
            "emissions_kg_per_year": 2_000_000.0,
        },
    )
    assert result.source_sha256


def test_edgar_csv_supports_explicit_units_and_totals(tmp_path):
    source = tmp_path / "edgar.csv"
    source.write_text(
        "Country_code_A3,Name,Substance,Y_2020\nDEU,Germany,SO2,0.25\n",
        encoding="utf-8",
    )
    result = xi.load_edgar_inventory(
        source,
        pollutant="SO2",
        sheet_name=0,
        source_unit="kt/year",
    )
    assert result.records[0]["emissions_kg_per_year"] == pytest.approx(250_000)
    assert result.records[0]["sector_code"] is None


def test_egrid_official_summary_workbook_is_preconfigured(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    source = tmp_path / "summary_tables_rev2.xlsx"
    workbook = openpyxl.Workbook()
    table1 = workbook.active
    table1.title = "Table 1"
    table1.append([None, "1. Subregion Output Emission Rates (eGRID2023)"])
    table1.append([None, "eGRID subregion acronym"])
    table1.append([None, "", "", "lb/MWh"])
    table1.append(
        [
            None,
            "eGRID subregion acronym",
            "eGRID subregion name",
            "CO2",
            "CH4",
            "N2O",
            "CO2e",
            "Annual NOx",
            "Ozone Season NOx",
            "SO2",
            "CO2",
            "CH4",
            "N2O",
            "CO2e",
            "Annual NOx",
            "Ozone Season NOx",
            "SO2",
            "Grid Gross Loss (%)",
        ]
    )
    table1.append(
        [
            None,
            "RMPA",
            "Rockies",
            1000,
            0.1,
            0.01,
            1006,
            0.5,
            0.4,
            0.3,
            1500,
            0.2,
            0.02,
            1512,
            0.8,
            0.7,
            0.6,
            0.04,
        ]
    )
    table3 = workbook.create_sheet("Table 3")
    table3.append([None, "3. State Output Emission Rates (eGRID2023)"])
    table3.append([None, "State"])
    table3.append([None, "", "lb/MWh"])
    table3.append(
        [
            None,
            "State",
            "CO2",
            "CH4",
            "N2O",
            "CO2e",
            "Annual NOx",
            "Ozone Season NOx",
            "SO2",
        ]
    )
    table3.append([None, "CO", 900, 0.08, 0.01, 905, 0.4, 0.3, 0.2])
    workbook.save(source)

    total = xi.load_egrid_emission_rates(source)
    non_baseload = xi.load_egrid_emission_rates(source, basis="non-baseload")
    state = xi.load_egrid_emission_rates(source, geography="state")

    assert total.records[0]["CO2_kg_per_mwh"] == pytest.approx(453.59237)
    assert total.records[0]["grid_gross_loss_fraction"] == pytest.approx(0.04)
    assert non_baseload.records[0]["CO2_kg_per_mwh"] == pytest.approx(680.388555)
    assert state.records[0]["geography_code"] == "CO"
    assert total.metadata["year"] == 2023


def test_egrid_custom_export_requires_or_infers_units(tmp_path):
    source = tmp_path / "egrid.csv"
    source.write_text(
        "subregion,CO2 (kg/MWh),SO2 (kg/MWh)\nRMPA,500,0.2\n",
        encoding="utf-8",
    )
    result = xi.load_egrid_emission_rates(source)
    assert result.records[0]["CO2_kg_per_mwh"] == pytest.approx(500)
    assert result.records[0]["SO2_kg_per_mwh"] == pytest.approx(0.2)


def test_iac_workbook_joins_assessment_and_economic_fields(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    source = tmp_path / "ITAC_Database.xlsx"
    workbook = openpyxl.Workbook()
    assess = workbook.active
    assess.title = "ASSESS"
    assess.append(["ID", "FY", "SIC", "NAICS", "STATE", "SALES", "EMPLOYEES"])
    assess.append(["XX0001", 2024, 3311, 331110, "CO", 10_000_000, 80])
    recc = workbook.create_sheet("RECC")
    recc.append(
        [
            "SUPERID",
            "ID",
            "AR_NUMBER",
            "APPCODE",
            "ARC2",
            "IMPSTATUS",
            "IMPCOST",
            "PSOURCCODE",
            "PCONSERVED",
            "PSOURCONSV",
            "PSAVED",
            "SSOURCCODE",
            "SCONSERVED",
            "SSOURCONSV",
            "SSAVED",
            "TSOURCCODE",
            "TCONSERVED",
            "TSOURCONSV",
            "TSAVED",
            "QSOURCCODE",
            "QCONSERVED",
            "QSOURCONSV",
            "QSAVED",
            "FY",
            "PAYBACK",
        ]
    )
    recc.append(
        [
            "XX000101",
            "XX0001",
            1,
            None,
            2.71,
            "I",
            20_000,
            "E1",
            100_000,
            100_000,
            8_000,
            "E2",
            500,
            500,
            2_000,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            2024,
            None,
        ]
    )
    workbook.save(source)

    result = xi.load_iac_recommendations(source, implemented_only=True)

    record = result.records[0]
    assert record["annual_cost_savings_usd"] == pytest.approx(10_000)
    assert record["simple_payback_years"] == pytest.approx(2)
    assert record["naics"] == 331110
    assert record["implementation_status"] == "implemented"
    assert len(record["resource_streams"]) == 2


def test_fied_normalizes_energy_ranges_and_ghg(tmp_path):
    source = tmp_path / "fied.csv"
    source.write_text(
        "registryID,name,naicsCode,stateCode,eisUnitID,unitTypeStd,fuelTypeStd,energyMJq0,energyMJq2,energyMJq3,ghgsTonneCO2eQ2\n"
        "123,Plant,331110,CO,U1,furnace,naturalGas,3600,7200,10800,4.5\n",
        encoding="utf-8",
    )
    result = xi.load_fied_units(source)
    record = result.records[0]
    assert record["energy_mwh_low"] == pytest.approx(1)
    assert record["energy_mwh_median"] == pytest.approx(2)
    assert record["energy_mwh_high"] == pytest.approx(3)
    assert record["ghg_kg_co2e_median"] == pytest.approx(4500)


def test_catalog_agent_discovery_and_cli_local_output(tmp_path, capsys):
    dataset_ids = {item.id for item in xi.list_datasets()}
    assert dataset_ids >= {
        "world-bank-wdi",
        "era5-land",
        "edgar",
        "egrid",
        "doe-iac",
        "fied",
    }
    agent_ids = {item["id"] for item in xi.list_capabilities()["catalog"]["datasets"]}
    assert agent_ids == dataset_ids

    source = tmp_path / "fied.csv"
    output = tmp_path / "normalized.json"
    source.write_text("registryID,energyMJ\n1,3600\n", encoding="utf-8")
    assert main(["fied", str(source), "--output", str(output), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["record_count"] == 1
    assert payload["output"] == str(output)
    assert json.loads(output.read_text(encoding="utf-8"))[0]["energy_mwh"] == 1
