# Quickstart

For coding agents, JSON recipes, structured errors, discovery commands, and MCP
host configuration, see [Agent integration](agent-integration.md).

## Installation

```bash
python -m pip install exergy-imperative
```

The base package is pure Python. On Windows it installs the small IANA `tzdata`
package for worldwide timezone handling. Add only the other features you need:

```bash
python -m pip install "exergy-imperative[data]"     # Excel and Parquet readers
python -m pip install "exergy-imperative[reports]"  # PDF reports
python -m pip install "exergy-imperative[all]"      # all optional features
```

For local development:

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

## Start with a process and one number

```python
import exergy_imperative as xi

case = xi.assess_process("compressed air", energy=2_500, country="DEU")
print(case.summary())
```

The result includes thermodynamic performance, exergy destruction, country
electricity emissions, a screening improvement range, likely pollutant
categories, warnings, sources, and the next measurements most likely to improve
the result. If energy is unknown, omit it for a result normalized per 1 MWh.

Add the project information you have:

```python
case = xi.assess_process(
    "steam",
    energy=10_000,
    country="USA",
    year=2025,
    annualization_factor=1.0,  # the input period is one year
    assessment_options={
        "efficiency": 0.88,
        "source_temperature": "180 C",
        "return_temperature": "90 C",
        "ambient_temperature": "20 C",
    },
    impact_options={
        "refrigerant_leakage_kg": {"HFC-134a": 3.0},
        "damage_costs_per_kg": {"NOx": 12.0, "SO2": 18.0},
        "currency": "USD",
    },
    economics_options={
        "capital_cost": 300_000,
        "energy_price_per_mwh": 42,
        "annual_maintenance_savings": 8_000,
        "carbon_price_per_tonne": 50,
        "project_life_years": 15,
        "discount_rate": 0.07,
    },
)
```

User values always take precedence over bundled screening priors.
`annualization_factor` is required whenever process economics fill annual values
from reporting-period results; use `1.0` only when that period is a full year.

## Export useful deliverables

```python
case.export_html("output/steam.html")
case.export_pdf("output/steam.pdf")
case.export_excel_compatible("output/steam-tables")
```

Reports use basic horizontal bar charts and traceable tables. The tabular export
uses UTF-8 CSV files that open in Excel, LibreOffice, and Google Sheets, plus a
JSON metadata file containing warnings and the complete source payload. It does
not include a Sankey or Grassmann diagram.

The same commands are available from a JSON process recipe:

```bash
exergy report examples/process_report_recipe.json \
  --html output/process.html \
  --pdf output/process.pdf \
  --excel-dir output/process-tables
```

## Screen climate gases and air pollutants directly

```python
impact = xi.assess_impacts(
    1_000,
    carrier="electricity",
    country="IND",
    year=2024,
    refrigerant_leakage_kg={"HFC-134a": 5.0},
    gases_kg={"CH4-fossil": 20.0},
    pollutant_masses_kg={"NOx": 8.0, "SO2": 2.0},
)

print(impact.co2e20_kg, impact.co2e100_kg)
print(impact.warming_horizon_gap_kg_co2e)
```

The 20-year and 100-year calculations expose the importance of short-lived
climate pollutants. Grid factors are aggregate lifecycle CO2e and therefore
cannot be decomposed into gases unless the user supplies a gas inventory.

Air-pollutant outputs report mass ranges and concise hazard information. They
are not exposure, epidemiological-risk, or health-impact assessments.
When energy is omitted, use `gas_factors_kg_per_mwh` and
`pollutant_factors_kg_per_mwh`; absolute gas, pollutant, and refrigerant masses
require an explicit energy quantity.

## Separate GHG boundaries and screen methane recovery

```python
inventory = xi.assess_ghg_boundaries(
    combustion_gases_kg={"CO2": 50_000},
    fugitive_gases_kg={"CH4-fossil": 250},
    purchased_energy_co2e_kg=12_000,
)

project = xi.assess_methane_project(
    annual_methane_mass_kg=25_000,
    methane_origin="biogenic",
    project_efficiency=0.9,
    recovered_gas_price_per_mwh=40,
    capital_cost=150_000,
)
project.export_excel_compatible("output/methane-project")
```

## Normalize a plant metric for weather

```python
normal = xi.monthly_weather_climatology(reference_weather_records)
adjusted = xi.normalize_weather_performance(
    plant_daily_records,
    value_field="input_exergy_mwh",
    metric="input exergy",
    unit="MWh_ex",
    climatology=normal,
)
```

Use `xi.fetch_nasa_power_weather()` when explicit access to open NASA POWER
weather is appropriate, or pass locally obtained weather records directly.

## Evaluate technology costs supplied by the user

```python
case = xi.evaluate_technology_cost_scenario(
    {
        "name": "high-temperature heat pump",
        "capital_cost": 1_200_000,
        "annual_output_mwh": 9_000,
        "output_name": "useful heat",
        "annual_fixed_opex": 30_000,
        "annual_fuel_use_mwh": 3_000,
        "annual_fuel_prices_per_mwh": [70] * 20,
        "annual_carbon_prices_per_tonne": [50] * 20,
        "source": "user-owned source file",
    }
)
```

The package does not ship or fetch IEA datasets. Users may enter values from
files they obtained separately when their licence and intended use permit it.

## Normalize operational data

```python
rows = xi.read_records("examples/telemetry_mixed_columns.csv")
mapping = xi.infer_mapping(rows[0], required=("timestamp", "energy"))
normalized = xi.normalize_records(rows, mapping=mapping, missing_policy="keep")
normalized.export_excel_compatible("output/normalized-telemetry")
```

Save and review an inferred mapping for a repeatable production workflow:

```bash
exergy ingest plant-export.xlsx --mapping-out mapping.json
exergy ingest plant-export.xlsx --mapping mapping.json \
  --excel-bundle output/plant-normalized --required timestamp --required energy
```

## Quantify uncertainty

```python
result = xi.monte_carlo(
    lambda efficiency, energy_price: {
        "annual_savings": 10_000 * (1 - efficiency) * energy_price
    },
    {
        "efficiency": xi.DistributionSpec.triangular(0.78, 0.85, 0.92),
        "energy_price": xi.DistributionSpec.uniform(35, 70),
    },
    samples=5_000,
    seed=42,
)

print(result.outputs["annual_savings"])
print(result.sensitivities)
```

Monte Carlo results include distributions and rank-based input importance.
One-at-a-time sensitivity and expected value of perfect information are also
available for deciding which missing input is worth measuring.

## Lower-level use

The original progressive-fidelity stream API remains available:

```python
result = xi.assess(
    technology="gas boiler",
    service="space heating",
    energy=1_000,
    unit="MWh",
)

refined = result.refine(
    efficiency=0.94,
    source_temperature="70 C",
    return_temperature="45 C",
    ambient_temperature="10 C",
)
```

Use `strict=True` to prohibit profiles. Exact formula functions such as
`physical_flow_exergy()` validate values but never look up or assume data.

`to_dict()` methods produce versioned JSON payloads. Bundled schemas are
available through `load_schema()`; quantity-and-quality records can be converted
with `from_quantity_quality()` and `to_quantity_quality()`.
