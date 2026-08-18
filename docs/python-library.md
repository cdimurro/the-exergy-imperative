# The `exergy-imperative` Python library

`exergy-imperative` turns incomplete energy information into transparent,
progressive-fidelity exergy assessments. It is useful with only an equipment,
service, or carrier name; every default remains visible and every parameter can
be replaced with measured or site-specific data later.

> Status: alpha — the released version is shown on
> [PyPI](https://pypi.org/project/exergy-imperative/). Results based on
> bundled profiles are screening
> estimates, not substitutes for a site-specific thermodynamic audit.

### Install

```bash
python -m pip install exergy-imperative
```

The base package is pure Python. On Windows, installation also supplies the
small IANA `tzdata` package needed for reliable worldwide timezone handling.
Install optional readers and PDF support only when needed:

```bash
python -m pip install "exergy-imperative[data,reports]"
```

Authenticated ERA5-Land retrieval is isolated in its own small extra:

```bash
python -m pip install "exergy-imperative[climate]"
```

Install the optional MCP server for direct use by coding agents and other MCP
hosts:

```bash
python -m pip install "exergy-imperative[mcp]"
exergy-mcp
```

### Agent-native recipes, discovery, and MCP

Agents can discover the library instead of guessing function signatures:

```bash
exergy capabilities --json
exergy describe process-assessment --kind workflow --json
exergy schema agent-recipe --json
```

One versioned recipe dispatcher covers exergy, integrated processes, impacts,
GHG boundaries, methane, economics, engineering, waste heat, balances, weather
normalization, record normalization, and reference validation:

```python
import exergy_imperative as xi

recipe = {
    "schema_version": "1.0",
    "workflow": "assessment",
    "inputs": {"technology": "air-source heat pump"},
}

preflight = xi.run_recipe(recipe, mode="validate-only")
screen = xi.run_recipe(recipe, mode="dry-run")
```

`validate-only` performs contract checks without calculations or writes.
`dry-run` calculates the result but suppresses every output path. `execute`
writes only explicitly requested JSON, HTML, PDF, XLSX, or Excel-compatible
outputs. Errors use stable codes, corrective hints, and suggested fields.

The optional `exergy-mcp` server uses local stdio by default and exposes tools
for workflow discovery, exergy calculation, integrated process assessment,
impact screening, economics, dataset normalization, and reporting. See the
[agent integration guide](agent-integration.md).

Capability search also covers generic components and data-only domain packs:

```python
xi.search_capabilities("ground source heat pump")
xi.list_bundled_technology_packs()
xi.technology_pack_coverage("emerging-energy")
```

The seven packs contain 80 technology profiles and 50 sourced automatic
screening paths. Use an energy-performance result when efficiency or COP is
known but heat or fuel exergy quality is not:

```python
performance = xi.assess_performance_with_pack(
    "emerging-energy",
    "concentrating-solar-power-block",
    input_energy=100,
)

intensity = xi.assess_intensity_with_pack(
    "advanced-materials",
    "hall-heroult-electrolysis",
    output_mass=10,
    output_unit="t",
)
```

These APIs deliberately omit exergy, emissions, hazards, and economics rather
than fill missing ledgers with unrelated defaults. All priors are replaceable,
and `strict=True` requires the caller to supply the performance or intensity.

### One call from sparse process data

```python
import exergy_imperative as xi

case = xi.assess_process(
    "steam",
    energy=10_000,
    unit="MWh",
    country="USA",
    annualization_factor=1.0,  # the input period is one year
    economics_options={
        "capital_cost": 250_000,
        "energy_price_per_mwh": 45,
        "carbon_price_per_tonne": 50,
    },
)

print(case.summary())
case.export_html("steam-report.html")
case.export_pdf("steam-report.pdf")       # requires the reports extra
case.export_excel_compatible("steam-data")
case.export_xlsx("steam-report.xlsx")     # requires the data extra
```

When process economics derive annual savings from the supplied reporting period,
set `annualization_factor` explicitly (`1.0` means the input already represents a
full year; `12.0` annualizes a representative month). You can instead provide all
annual savings values directly in `economics_options`.

This combines a progressive-fidelity exergy assessment, country/year grid
factors, fuel greenhouse gases, combustion-pollutant screening, a bounded
improvement opportunity, and project economics. Every default is identified;
the same call accepts measured temperatures, efficiency, gas inventories,
pollutant factors, damage costs, and financial assumptions as overrides.

Twelve starting templates cover steam, furnaces, compressed air,
refrigeration, drying, desalination, electrolysis, data centers, cement, steel,
food processing, and district energy. Run `exergy processes` to list them.

### Start with what you know

```python
import exergy_imperative as xi

result = xi.assess(
    technology="natural-gas boiler",
    service="space heating",
    energy=1_000,
    unit="MWh",
    location="Denver, US",
)

print(result.summary())
```

The output reports the exergy estimate and screening range, its F0-F4 Fidelity
Tier, every assumed value and source, warnings, and the measurements most likely
to improve the answer.

If energy is unknown, omit it. The result is normalized per 1 MWh of input:

```python
screen = xi.assess(technology="air-source heat pump")
```

Normalized environmental calculations accept `gas_factors_kg_per_mwh` and
`pollutant_factors_kg_per_mwh`. Absolute gas, pollutant, and refrigerant masses
require an explicit energy quantity so an inventory cannot be mislabeled as a
per-MWh intensity.

Refine any result without rebuilding the case:

```python
refined = result.refine(
    efficiency=0.93,
    source_temperature="65 C",
    return_temperature="45 C",
    ambient_temperature="5 C",
)
```

### Use a known carrier or service

```python
electricity = xi.assess(carrier="electricity", energy=500, unit="kWh")
district_heat = xi.assess(service="district heating", energy=2.5, unit="GJ")
```

For exact engineering inputs, the lower-level formula API is independent of
all profiles:

```python
fx = xi.sensible_heat_exergy_factor_c(
    supply_c=80,
    return_c=50,
    reference_c=20,
)
```

### Enrich XAI4Heat-compatible telemetry

```bash
exergy enrich telemetry.csv --output enriched.csv --profile xai4heat
exergy xai-summary telemetry.csv
```

The preprocessor recognizes common aliases for timestamps, ambient temperature,
primary and secondary supply/return temperatures, and thermal delivery. It
calculates all supported constant-temperature, integrated-stream, fixed-sink,
and operational-sink models without requiring every column.
Explicit `energy_kwh` and `energy_mwh` delivery columns are normalized to MWh;
unitless delivery aliases retain their source unit for within-series weighting.

### Normalize energy or exergy for weather

```python
records = xi.nasa_power_weather_records(weather_payload)
climate = xi.monthly_weather_climatology(records, source="NASA POWER")
normalized = xi.normalize_weather_performance(
    plant_daily_records,
    value_field="energy_mwh",
    unit="MWh",
    climatology=climate,
)
```

The dependency-free weather layer calculates heating and cooling degree days,
monthly climatologies, observation anomalies, and a transparent degree-day
regression. The dependent value can be energy, exergy, production, cost, or any
other nonnegative additive daily metric. NASA POWER access remains explicit;
local CSV records work without a network connection.

### Keep GHG boundaries and methane projects explicit

```python
inventory = xi.assess_ghg_boundaries(
    combustion_gases_kg={"CO2": 25_000},
    process_gases_kg={"N2O": 4},
    fugitive_gases_kg={"CH4-fossil": 120},
    purchased_energy_co2e_kg=8_000,
)

methane = xi.assess_methane_project(
    annual_methane_mass_kg=10_000,
    methane_origin="biogenic",
    baseline_mode="vented",
    project_mode="recovered",
    project_efficiency=0.92,
    recovered_gas_price_per_mwh=35,
    capital_cost=75_000,
)
```

Combustion, process, fugitive, purchased-energy, and contextual allocated
electricity/heat values remain separate. Methane projects compare venting,
flaring, oxidation, and recovery using both 20- and 100-year warming potentials,
recovered energy, product revenue, and standard project economics.

### Evaluate user-supplied technology costs

```python
cost = xi.evaluate_technology_cost_scenario(
    xi.TechnologyCostScenario(
        name="industrial heat pump",
        capital_cost=1_200_000,
        annual_output_mwh=9_000,
        output_name="useful heat",
        annual_fixed_opex=30_000,
        annual_fuel_use_mwh=3_000,
        annual_fuel_prices_per_mwh=(70,) * 20,
        annual_carbon_prices_per_tonne=(50,) * 20,
        source="user-owned source file",
    )
)
print(cost.levelized_cost_per_mwh)
```

No IEA dataset or scenario value is shipped or downloaded by these functions.
Users can manually obtain data they are entitled to use, copy the relevant
values into their own records or scenario objects, and remain responsible for
the source licence and permitted use.

For less structured files, the universal ingestion layer reads CSV, TSV, JSON,
JSONL, Excel, XLSB, Parquet, SQLite, and DB-API query results. It infers common
industrial column aliases, converts units, preserves raw records, records data
quality issues, and can write an Excel-compatible folder of UTF-8 CSV and JSON
files.

### Use editable Excel templates or local publisher files

```bash
exergy excel-template heat-pump heat-pump-input.xlsx
exergy excel-run heat-pump-input.xlsx --output heat-pump-report.xlsx
exergy adapt-local my-workbook.xlsx iea-ghg-energy \
  --output normalized.xlsx
```

Ten native input templates cover the integrated, environmental, economic,
weather, and detailed engineering workflows. Native output workbooks include
basic Excel charts, tables, sources, warnings, and a machine-readable payload.

Local dataset adapters contain only schemas and field mappings—never the
publisher's values. The source file stays on the user's machine, its fingerprint
and data-quality issues remain in the audit trail, and the user controls every
override. Field-only adapters are installed under the stable names
`ei-total-energy-supply` and `iea-ghg-energy`; users remain responsible for their
workbook licences and permitted derived uses. Python users can inspect them with
`list_bundled_adapters()` and `load_bundled_adapter()` before use.

### Add optional public context without bundling large datasets

The optional integration layer provides explicit, cacheable World Bank WDI
economic context and authenticated ERA5-Land retrieval. Publisher-aware local
normalizers handle EDGAR country-sector emissions, EPA eGRID electricity
factors, DOE ITAC/IAC recommendations and economics, and FIED unit-level energy
and GHG estimates.

No raw EDGAR, eGRID, ITAC/IAC, FIED, or ERA5 data is bundled. Local results
retain a source-file hash, publisher attribution, unit basis, configuration,
and scope warnings. Python arguments can override publisher-shaped defaults,
and CLI `--output` paths can produce CSV, JSON, JSONL, TSV, or XLSX records. See
the [external-data integration guide](https://github.com/cdimurro/the-exergy-imperative/blob/main/docs/external-data-integrations.md).

### Run detailed engineering and waste-heat screens

```python
heat_pump = xi.analyze_heat_pump(
    delivered_heat_mwh=1_000,
    source_temperature_c=10,
    sink_temperature_c=60,
    cop=3.2,
)

matches = xi.match_waste_heat(sources=[...], demands=[...])
```

Dedicated models cover steam, heat pumps, furnaces, refrigeration, compressed
air, and multi-source waste-heat matching. They expose first- and second-law
efficiency, recoverable energy, quality mismatch, assumptions, warnings, and
primary method references. They are screening models with explicit boundaries,
not equipment design tools.

### Reproduce reference calculations

```bash
exergy validate
exergy validate --xai4heat path/to/user-owned-telemetry.csv
```

The bundled suite checks published temperature examples, a heat-pump example,
and the Petela radiation factor. The optional XAI4Heat path compares a local
dataset with the five portfolio results reported in the paper without bundling
the underlying telemetry.

### Analyze a process boundary

```python
from exergy_imperative import ExergyStream, analyze_balance

balance = analyze_balance(
    "Heating plant",
    inputs=[ExergyStream("fuel", 930)],
    products=[ExergyStream("useful heat", 75)],
    losses=[ExergyStream("stack", 40)],
)
```

### Compose an unfamiliar technology or connected system

```python
result = xi.analyze_system(
    "custom converter",
    components=[{"id": "converter", "kind": "converter"}],
    flows=[
        {"id": "input", "energy": 10, "target": "converter", "carrier": "electricity"},
        {"id": "product", "energy": 8, "source": "converter", "carrier": "shaft-work"},
        {"id": "loss", "energy": 2, "exergy": 0, "source": "converter", "role": "loss"},
    ],
)
```

For named extensions, `load_technology_pack()` overlays a local or bundled pack
without mutating the default registry. `analyze_system_timeseries()` adds
chronological records, representative-period weights, and signed storage
changes. See [Connected systems and technology packs](systems-and-packs.md).

### Close material and constituent balances

```python
materials = xi.analyze_material_system(
    "separator",
    components=[{"id": "separator", "kind": "reactor-separator"}],
    streams=[
        {
            "id": "feed",
            "mass": 100,
            "target": "separator",
            "composition": {"product": 0.8, "gangue": 0.2},
        },
        {"id": "product", "mass": 80, "source": "separator", "material": "product"},
        {"id": "tailings", "mass": 20, "source": "separator", "role": "loss", "material": "gangue"},
    ],
)
```

Material balances normalize supported mass units to kilograms and report both
total and constituent closure. Chemical exergy is optional and remains
unreconciled unless every participating stream has an explicit specific factor.

### Commands

```text
exergy assess       Screen a stream or technology
exergy capabilities Discover agent workflows, schemas, and safety behavior
exergy search       Search named options, generic components, packs, and schemas
exergy describe     Describe a workflow, process template, or profile
exergy packs        List or inspect bundled data-only technology packs
exergy pack-coverage Show defaults and explicit-input gaps for every technology
exergy performance  Estimate energy output from a sourced efficiency or COP
exergy intensity    Estimate input energy from a sourced mass-normalized prior
exergy models       List registered technology-model contracts
exergy model-evaluate Evaluate an explicit-performance model from JSON
exergy pack-validate Validate a local or bundled technology pack
exergy pack-scaffold Write a safe local technology-pack scaffold
exergy schema       List or read packaged JSON Schemas
exergy run          Validate, dry-run, or execute an agent recipe
exergy profiles     Inspect bundled defaults and sources
exergy processes    List industry process templates
exergy process      Run an integrated process, impact, and economic screen
exergy factors      Inspect grid, fuel, GWP, and health-screening factors
exergy impacts      Screen greenhouse gases and air pollutants
exergy ghg-boundaries Evaluate a JSON inventory with explicit GHG boundaries
exergy methane      Evaluate a JSON venting, flaring, or recovery project
exergy economics    Evaluate a JSON investment case
exergy technology-cost Evaluate a user-supplied technology cost scenario
exergy weather-normalize Normalize a daily CSV metric for weather
exergy ingest       Normalize tabular or record-oriented data
exergy report       Export a process case to HTML, PDF, or tabular files
exergy excel-template Create an editable native Excel input workbook
exergy excel-run     Run an Excel input workbook and optionally export results
exergy adapt-local   Normalize a user-owned dataset through a JSON adapter
exergy engineering   Run a detailed industrial engineering model from JSON
exergy waste-heat    Match waste-heat sources and demands from JSON
exergy validate      Run bundled or local XAI4Heat validation cases
exergy enrich       Enrich a telemetry CSV
exergy xai-summary  Summarize XAI4Heat-compatible data
exergy balance      Analyze a JSON process balance
exergy system       Analyze a connected component system from JSON
exergy system-timeseries Aggregate chronological system records from JSON
exergy material-balance Analyze mass, composition, inventory, and chemical exergy
exergy datasets     List public-data integrations
exergy weather      Explicitly fetch NASA POWER temperature data
exergy world-bank   Explicitly fetch WDI economic context
exergy era5-land    Explicitly retrieve authenticated ERA5-Land files
exergy edgar        Normalize a local EDGAR workbook or export
exergy egrid        Normalize a local EPA eGRID workbook or export
exergy iac          Normalize a local DOE ITAC/IAC database
exergy fied         Normalize a local FIED unit-level export
```

See the [quickstart](https://github.com/cdimurro/the-exergy-imperative/blob/main/docs/quickstart.md),
[data and fidelity guide](https://github.com/cdimurro/the-exergy-imperative/blob/main/docs/data-and-fidelity.md),
[environment, health, and economics guide](https://github.com/cdimurro/the-exergy-imperative/blob/main/docs/environment-health-economics.md),
[ingestion guide](https://github.com/cdimurro/the-exergy-imperative/blob/main/docs/ingestion.md),
[Excel and local-data guide](https://github.com/cdimurro/the-exergy-imperative/blob/main/docs/excel-and-local-data.md),
[engineering-model guide](https://github.com/cdimurro/the-exergy-imperative/blob/main/docs/engineering-models.md),
[validation guide](https://github.com/cdimurro/the-exergy-imperative/blob/main/docs/validation.md), and
[architecture guide](https://github.com/cdimurro/the-exergy-imperative/blob/main/docs/architecture.md).
Optional public-data workflows are documented in the
[external-data integration guide](https://github.com/cdimurro/the-exergy-imperative/blob/main/docs/external-data-integrations.md).
Coding-agent and MCP integrations are documented in the
[agent integration guide](https://github.com/cdimurro/the-exergy-imperative/blob/main/docs/agent-integration.md).

Air-pollutant results are inventory and hazard screens. They do not model
dispersion, population exposure, dose-response relationships, or clinical risk.
The library never assigns a universal monetary health cost: supply a locally
appropriate damage-cost factor when that comparison is justified.

The Python source is Apache-2.0 licensed. This guide and the bundled reference
profiles remain CC BY 4.0; see the licensing and attribution details in
[NOTICE](https://github.com/cdimurro/the-exergy-imperative/blob/main/NOTICE).
