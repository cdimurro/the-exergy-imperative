# Optional external-data integrations

The library ships configuration and normalization logic, not copies of the
publishers' raw datasets. This keeps installation small, makes network access
explicit, and lets users comply with the terms attached to the exact release
they choose.

Discover every integration and its machine-readable access instructions with:

```python
import exergy_imperative as xi

for dataset in xi.list_datasets():
    print(dataset.id, dataset.access_mode, dataset.python_api)
```

```bash
exergy datasets --json
```

Coding agents can obtain the same catalog from `list_capabilities()` under
`catalog.datasets`, the MCP `public_datasets` tool, or the
`exergy://datasets` resource. Recipe workflows still perform no implicit
network access.

## Installation choices

The World Bank connector, NASA POWER connector, offline ERA5 request builder,
and CSV/JSON local normalizers work with the base package. Add only what the
selected source format requires:

```bash
# Excel, XLSB, or Parquet source files
python -m pip install "exergy-imperative[data]"

# Authenticated ERA5-Land retrieval
python -m pip install "exergy-imperative[climate]"

# Every optional runtime feature
python -m pip install "exergy-imperative[all]"
```

## World Bank economic context

`fetch_world_bank_indicators()` uses the unauthenticated World Bank API and
defaults to CPI, GDP deflator, and official exchange-rate series. Supply only a
country code for a useful starting point, then select a time range or override
the indicator IDs when needed.

```python
context = xi.fetch_world_bank_indicators(
    "BRA",
    start_year=2015,
    end_year=2025,
    cache_dir=".cache/world-bank",
)
```

```bash
exergy world-bank BRA --start-year 2015 --end-year 2025 \
  --cache-dir .cache/world-bank --output brazil-context.xlsx
```

These are contextual national indicators. They do not replace site tariffs,
vendor quotations, organization-specific discount rates, or a declared price
year and currency-conversion method. The World Development Indicators catalog
is licensed under CC BY 4.0; retain attribution. See the
[World Bank API documentation](https://datahelpdesk.worldbank.org/knowledgebase/articles/889392)
and [WDI catalog](https://datacatalog.worldbank.org/search/dataset/0037712).

## ERA5-Land weather and solar context

Request construction is offline and deterministic:

```python
requests = xi.build_era5_land_requests(
    52.52,
    13.405,
    "2025-01-01",
    "2025-12-31",
    variables=("2m_temperature", "surface_solar_radiation_downwards"),
)
```

Retrieval is a separate explicit action. Before calling it, create a Climate
Data Store account, place the CDS credentials in the documented local config,
and accept the ERA5-Land dataset terms in the CDS interface.

```python
download = xi.retrieve_era5_land(
    52.52,
    13.405,
    "2025-01-01",
    "2025-12-31",
    "data/era5-berlin",
)
```

The connector creates monthly requests, preserves each request beside the
output path in its returned manifest, and treats existing files as a cache.
ERA5-Land is model/reanalysis output at a grid scale, not a site measurement.
See the [CDS API setup guide](https://cds.climate.copernicus.eu/how-to-api) and
[ERA5-Land catalog](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land).

## EDGAR greenhouse-gas and air-pollutant inventories

Download and extract the desired country/sector workbook from EDGAR. The
normalizer understands the current `IPCC 2006`, `IPCC 1996`, and country-total
wide-year layout, reads its compound, unit, and reference metadata, and
normalizes Gg/kt, tonnes, or kg to `emissions_kg_per_year`.

```python
nox = xi.load_edgar_inventory(
    "EDGAR_NOx_1970_2022.xlsx",
    start_year=2015,
    end_year=2022,
)
```

```bash
exergy edgar EDGAR_NOx_1970_2022.xlsx --start-year 2015 \
  --end-year 2022 --output nox-normalized.xlsx
```

For a CSV export, declare `source_unit`; for a revised layout, pass a `columns`
mapping to the Python API. EDGAR requires source acknowledgement and some
releases incorporate upstream data with additional conditions. Review the
terms for the exact selected release. Inventory mass supports emissions and
pollutant inventory context but is not ambient concentration, exposure, attributable
illness, or clinical risk. See the
[EDGAR air-pollutant dataset](https://edgar.jrc.ec.europa.eu/dataset_ap81).

## EPA eGRID electricity factors

The default configuration directly recognizes EPA's eGRID summary workbook.
It supports subregion or state total-output rates and subregion non-baseload
rates, retains the selected basis, and converts lb/MWh to kg/MWh. Custom CSV or
detailed-workbook exports may use automatic header matching, an explicit
`rate_unit`, and Python `columns` overrides.

```python
average = xi.load_egrid_emission_rates("summary_tables_rev2.xlsx")
screening_change = xi.load_egrid_emission_rates(
    "summary_tables_rev2.xlsx",
    basis="non-baseload",
)
```

```bash
exergy egrid summary_tables_rev2.xlsx --basis total \
  --output egrid-subregions.xlsx
```

CO2, CH4, N2O, CO2e, NOx, ozone-season NOx, and SO2 are supported in the
summary workbook. PM2.5, NH3, and VOC can be normalized when present in a local
supplemental export. Total output rates are attributional averages;
non-baseload rates are a screening proxy rather than a dispatch model. eGRID
is US-specific. See [EPA eGRID summary data](https://www.epa.gov/egrid/summary-data)
and [detailed data](https://www.epa.gov/egrid/detailed-data).

## DOE ITAC/IAC recommendations and economics

The normalizer recognizes the current public ITAC database workbook, joins the
`RECC` recommendation sheet to `ASSESS`, combines primary through quaternary
annual dollar savings, and retains implementation cost, status, simple
payback, resource codes, NAICS/SIC, state, and assessment fiscal year.

```python
implemented = xi.load_iac_recommendations(
    "ITAC_Database.xlsx",
    implemented_only=True,
)
```

```bash
exergy iac ITAC_Database.xlsx --implemented-only \
  --output implemented-recommendations.xlsx
```

Historical values are nominal US dollars in the assessment year. Use the WDI
connector or a user-approved price index and exchange-rate method before
cross-year or cross-country economic comparisons. The assessed US small and
medium manufacturer sample is not a representative global prior, and observed
implementation is not a causal guarantee. Download from the
[ITAC database](https://itac.university/download).

## FIED industrial units

`load_fied_units()` recognizes the published facility, unit, fuel, energy
estimate, and GHG range fields. It converts MJ to MWh and tonnes CO2e to kg
CO2e while retaining low, median, and upper estimates separately.

```python
units = xi.load_fied_units("fied_2020.parquet")
```

```bash
exergy fied fied_2020.parquet --output fied-normalized.xlsx
```

FIED estimates are useful for equipment and industry priors but do not replace
site measurements, temperature-grade information, or a declared process
boundary. FIED is US-specific and incorporates multiple upstream agency
sources. Review its release terms and lineage at the
[FIED repository](https://github.com/NatLabRockies/foundational-industry-energy-data)
and [OEDI release](https://doi.org/10.25984/2437657).

## Safe override pattern

Every local normalizer fingerprints the source file, returns source and license
metadata, and records limitations. Publisher-shaped defaults reduce setup;
function arguments remain the final override. Keep raw downloads outside the
package and version the following with each analysis:

- publisher release and download date;
- local file hash from `result.source_sha256`;
- sheet, header, unit, geography, and emissions basis;
- any column overrides, filters, currency conversions, and inflation method;
- whether a value is measured, modeled, estimated, or a screening default.
