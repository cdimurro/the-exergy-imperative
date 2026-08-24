# The Exergy Imperative

[![CI](https://github.com/cdimurro/the-exergy-imperative/actions/workflows/ci.yml/badge.svg)](https://github.com/cdimurro/the-exergy-imperative/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/exergy-imperative.svg)](https://pypi.org/project/exergy-imperative/)
[![Python](https://img.shields.io/pypi/pyversions/exergy-imperative.svg)](https://pypi.org/project/exergy-imperative/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

**A Python Library and Guide for analyzing exergy, emissions, health, and economics using the data that you already have.** Give it as little as an equipment
name and a country; every default it fills in stays visible, sourced, and is replaceable with your own data or measurements.

## One product stack

The shared path is: **discover the missing quality field, standardize the
record, then turn it into an auditable decision.**

| Product | Use it when |
|---|---|
| **[Exergy Factor](https://exergyfactor.com)** | You need a free, no-install calculator for one or a few energy records. |
| **[Quantity and Quality](https://github.com/cdimurro/quantity-and-quality)** | You need the canonical calculation kernel, CLI, schemas, API, or batch reporting standard. |
| **The Exergy Imperative** | You need to turn utility or telemetry data into prioritized losses, emissions, public-health benefit screening, economics, and reports. |

## Why this library

Energy is never created or destroyed — but its capacity to do useful work is.
Every joule can be split into **exergy**, the part that has capacity to perform useful work, and
**anergy**, the part that does not. Across the entire universe there are two things that
are happening: useful work is being performed, and exergy is being
destroyed. That one-way flow drives every engine, grid, reactor, and star,
yet almost all of our energy accounting ignores it. This library makes it easily visible
for any energy carrier, technology, or process, and meets you at whatever level of detail
you have. [The Exergy Imperative](THE_EXERGY_IMPERATIVE.md), the guide this
library grew out of, tells the full story.

Most exergy tools ([TESPy](https://github.com/oemof/tespy),
[ExerPy](https://github.com/oemof/exerpy), Aspen Plus) start from a fully
specified plant simulation. Most real decisions start earlier — with a
utility bill, a telemetry export, or a one-line description of whatever
system you are working on. `exergy-imperative` works at that end of the
funnel:

- **Sparse input, transparent output.** Progressive-fidelity assessments (F0
  upward) from a bare technology name to measured site data. Every number
  carries provenance, a range, and warnings — screening defaults are never
  passed off as measurements.
- **The whole business case, not just thermodynamics.** Exergetic efficiency
  and destruction, AR6 20/100-year climate impact, pollutant inventories,
  sourced EPA public-health benefit ranges, and project economics (NPV, IRR,
  payback, levelized cost,
  marginal abatement cost) in one result.
- **Data plumbing built in.** Auditable ingestion from CSV, Excel,
  Parquet, JSON, and SQL with unit conversion and mapping inference; native
  Excel input templates and workbook reports; weather normalization from NASA
  POWER; connectors for World Bank, ERA5-Land, EDGAR, eGRID, and DOE IAC data.
- **Agent-native.** Versioned JSON recipes with validate-only / dry-run /
  execute modes, stable error codes, capability discovery, and an optional
  [MCP server](docs/agent-integration.md) so AI assistants can drive full
  assessments safely.
- **Open-ended by design.** Validated local technology packs and connected
  component graphs cover unfamiliar equipment, multi-output processes, and
  chronological storage without pretending the library is a design simulator.
- **Zero required dependencies.** The core is pure Python (3.11–3.14); pandas,
  CoolProp, PDF, and MCP support are opt-in extras.

## Install

```bash
python -m pip install exergy-imperative
```

Optional extras, only if you need them:

```bash
python -m pip install "exergy-imperative[data]"     # Excel / Parquet readers
python -m pip install "exergy-imperative[reports]"  # PDF reports
python -m pip install "exergy-imperative[mcp]"      # MCP server for agents
python -m pip install "exergy-imperative[all]"      # everything
```

## Start from the physics

The same few questions apply to every energy system, from a kettle to a
national grid — and each is one line:

```python
import exergy_imperative as xi

# How much of a heat flow could still become useful work?
xi.thermal_exergy_factor_c(80, 20)     # 0.17 — hot water at 80 °C in a 20 °C world
xi.thermal_exergy_factor_c(1500, 20)   # 0.83 — furnace heat is nearly pure work potential
xi.petela_exergy_factor()              # 0.93 — sunlight is very high-quality energy

# How much quality does a technology preserve? Ask by name.
xi.assess("air-source-heat-pump").exergetic_efficiency.value        # 0.32
xi.assess("natural-gas-boiler").exergetic_efficiency.value          # 0.11
xi.assess("electric-resistance-heater").exergetic_efficiency.value  # 0.10
xi.assess("lithium-ion-battery").exergetic_efficiency.value         # 0.93
```

Three ways to warm the same room, and the heat pump preserves three times
more work potential than the boiler advertising "95 % efficiency" — the kind
of difference energy accounting cannot see and exergy accounting can.
`xi.list_profiles("technology")` lists everything assessable by name —
electrolyzers, fuel cells, chillers, desalination, data centers, batteries —
and every profile value can be replaced with your own temperatures, COPs,
and efficiencies.

## Sixty seconds to a result

```python
import exergy_imperative as xi

case = xi.assess_process("compressed air", energy=2_500, country="DEU")
print(case.summary())
```

```text
Compressed-air system
Fidelity: F1
Exergetic efficiency: 0.15 dimensionless (screening range 0.08-0.25)
Climate impact: 8.24e+05 kg CO2e (100-year)
Screening energy opportunity: 500 MWh (screening range 125-875)
Warnings and limitations:
  - The improvement opportunity uses a broad template screening prior; ...
```

Add whatever data you have — efficiency, temperatures, energy prices, capital cost,
lifespan, location, and then analyze the results. 

For U.S. efficiency, renewable-energy, and PV-plus-storage projects, the
library can estimate monetized outdoor-air public-health benefits even when a
user has no exposure model. This example applies EPA's published Rocky
Mountains screening range to 1,000 MWh/year of uniform energy savings:

```python
health = xi.estimate_health_benefits(
    region="Rocky Mountains",
    project_type="Uniform EE",
    energy=1_000,
)

health.monetized_benefit.low   # 18,000 (2023 USD/year)
health.monetized_benefit.high  # 27,300 (2023 USD/year)
```

Every result retains the source table, model versions, 2023 currency basis,
2% discount rate, geography and pathway boundaries, F1 fidelity, and explicit
warnings. Both rate bounds can be overridden. It is a regional screening
estimate, not a prediction of local exposure, cases, deaths, or individual
risk.

Export deliverables at any time:

```python
case.export_html("compressed-air.html")
case.export_pdf("compressed-air.pdf")              # [reports] extra
case.export_excel_compatible("compressed-air-data")
```

The same works from the command line, from JSON recipes, and from Excel
templates:

```bash
exergy report examples/process_report_recipe.json --html output/report.html
exergy capabilities --json     # discovery for scripts and agents
exergy validate                # run the bundled reference checks
```

See the [quickstart](docs/quickstart.md) for the full tour.

For the complete product journey, run the
[industrial data pilot](docs/case-study-industrial-data-pilot.md): an existing
meter export is mapped and quality-checked, assessed by process, ranked by
thermodynamic loss and screening NPV, and exported as an auditable report.

## Model a technology that is not in the catalog

Use a bundled domain pack, create your own pack, or describe an arbitrary
connected system. Where an official source matches the modeled boundary, a
pack can supply a bounded F1 `published_estimate`; otherwise it still requires
project performance. Every prior remains visible and replaceable:

```python
import exergy_imperative as xi

gshp = xi.assess_with_pack(
    "buildings",
    technology="ground-source heat pump",
    energy=100,
    source_temperature="45 C",
    ambient_temperature="20 C",
)

print(gshp.parameters["cop"].to_dict())
site_result = gshp.refine(cop=4.2)

system = xi.analyze_system(
    "custom converter",
    components=[{"id": "converter", "kind": "converter"}],
    flows=[
        {"id": "input", "energy": 10, "target": "converter", "carrier": "electricity"},
        {"id": "product", "energy": 8, "source": "converter", "carrier": "shaft-work"},
        {"id": "loss", "energy": 2, "exergy": 0, "source": "converter", "role": "loss"},
    ],
)
```

`exergy search "ground source" --json` finds named and generic options.
`exergy pack-scaffold my_pack.json` creates a sourced, versioned extension
template. See [connected systems and technology packs](docs/systems-and-packs.md).

The seven domain packs cover 80 technologies from buildings, mobility, power,
water, oil and gas, and refining through hydrogen, geothermal, advanced
nuclear, carbon management, long-duration storage, metals, cement, chemicals,
critical minerals, and recycling. Fifty technologies now have at least one
official-source screening path: 48 efficiency/COP priors and three
mass-normalized steel/aluminum intensity priors, with one technology in both
groups. Every remaining entry reports why explicit data are still required:

```python
xi.search_capabilities("pipeline compressor")
xi.search_capabilities("cement clinker", kind="material")
xi.technology_pack_coverage("oil-gas")

csp = xi.assess_performance_with_pack(
    "emerging-energy",
    "concentrating-solar-power-block",
    input_energy=100,
)

steel = xi.assess_intensity_with_pack(
    "advanced-materials",
    "electric-arc-furnace-melting",
    output_mass=100,
)

balance = xi.analyze_material_system(
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
        {"id": "loss", "mass": 20, "source": "separator", "role": "loss", "material": "gangue"},
    ],
)
```

Mass, constituent, energy, exergy, emissions, public-health screening, and
economics remain
separate ledgers. Chemical exergy is calculated only from explicitly supplied
factors and is not silently double-counted as an energy flow.

## What's inside

- Twelve ready-made process templates spanning the energy landscape: steam,
  furnaces, compressed air,
  refrigeration, drying, desalination, hydrogen electrolysis, data centers,
  cement, steel reheat, food processing, district energy.
- Engineering screens for steam systems, heat pumps, furnaces, refrigeration,
  compressed air, and waste-heat matching.
- Generic connected-system accounting with eleven component primitives,
  multi-input/multi-output boundaries, explicit storage change, and weighted
  chronological records.
- Versioned custom technology/process packs plus data-only starter packs for
  buildings, power, mobility, water, oil and gas, emerging energy, advanced
  materials, and manufacturing.
- First-class mass/composition balances, material inventory accumulation,
  material-boundary templates, and an extensible technology-model registry.
- Explicit GHG boundaries (combustion, process, fugitive, purchased energy),
  methane vent/flare/recovery project analysis, and grid intensities for 213
  countries (Ember / Our World in Data, 2020–2025).
- EPA AVERT/COBRA regional public-health benefit ranges for 14 contiguous-U.S.
  grid regions and eight efficiency, solar, storage, and wind interventions.
- Monte Carlo uncertainty propagation, sensitivity ranking, and value of
  perfect information.
- Dependency-free SVG/HTML reports, optional PDF, and auditable
  Excel-compatible bundles with complete source payloads.
- Optional real-fluid physical exergy via [CoolProp](http://www.coolprop.org/)
  (`[properties]` extra).

## When to use it — and when not to

| Your situation | Use |
|---|---|
| Screening any energy technology, site, or portfolio from bills, telemetry, or one-line descriptions | **exergy-imperative** |
| Building the emissions + health + economics case around an efficiency project | **exergy-imperative** |
| Letting an AI assistant run auditable energy assessments (MCP / JSON recipes) | **exergy-imperative** |
| Component-level exergy analysis of a fully specified thermodynamic cycle | [TESPy](https://github.com/oemof/tespy) |
| Exergy analysis on top of an existing Aspen Plus or Ebsilon simulation | [ExerPy](https://github.com/oemof/exerpy) |
| Detailed process simulation, equipment design, or guarantee calculations | Aspen Plus, gPROMS, EBSILON, EES |

This library is deliberately a **screening tool**: its thermodynamics are
closed-form (Carnot factors, Gouy–Stodola, Petela, ideal-mixture separation)
plus optional CoolProp real-fluid properties. Results based on bundled
profiles are screening estimates with declared ranges — a triage and
business-case layer that tells you where a detailed simulation or site audit
is worth the money, not a substitute for one.

## Data, provenance, and validation

Bundled reference data ships with sources, versions, licenses, and confidence
labels: Ember/OWID electricity intensities, IPCC AR6 warming potentials, IPCC
2006 fuel factors, EPA regional public-health benefit ranges, and EPA/EMEP/EEA
pollutant context profiles. No
restricted publisher data (IEA, Energy Institute) is redistributed — local
adapters map *your* licensed copies with SHA-256 fingerprinting. Run
`exergy validate` to execute the bundled reference calculations and see every
expected value, tolerance, and citation. Run `exergy validate --coverage` to
inspect the assurance level and unresolved limitations for every scientific
capability. Screening profiles and discovery-only technology packs are never
included in a blanket “validated” claim.

## Documentation

| Guide | What it covers |
|---|---|
| [Quickstart](docs/quickstart.md) | Install to first report |
| [Python library](docs/python-library.md) | Full API tour |
| [Engineering models](docs/engineering-models.md) | Equipment screens and their assumptions |
| [Connected systems & packs](docs/systems-and-packs.md) | Arbitrary systems, storage, and custom technologies |
| [Environment, health, economics](docs/environment-health-economics.md) | Impacts and project finance |
| [Data & fidelity](docs/data-and-fidelity.md) | Fidelity tiers, units, boundaries |
| [Ingestion](docs/ingestion.md) · [Excel & local data](docs/excel-and-local-data.md) | Getting your data in |
| [External data integrations](docs/external-data-integrations.md) | World Bank, ERA5-Land, EDGAR, eGRID, IAC |
| [Agent integration](docs/agent-integration.md) | JSON recipes, discovery, MCP server |
| [Validation](docs/validation.md) | Reference checks and their scope |
| [Industrial data pilot](docs/case-study-industrial-data-pilot.md) | Meter export to prioritized business-case report |
| [Architecture](docs/architecture.md) | How the modules fit together |
| [Changelog](docs/changelog.md) | Release history |
| [**The Exergy Imperative**](THE_EXERGY_IMPERATIVE.md) | The complete guide to exergy and the energy transition |

## Status

Alpha — the released version is shown in the PyPI badge above. The public
Python API, CLI commands, recipe contract `1.0`,
packaged JSON Schemas, and MCP tools are stable surfaces within a minor
version (see [AGENTS.md](AGENTS.md)). Release history lives in the
[changelog](docs/changelog.md). Contributions are welcome — especially
reviewed profiles, validation cases against published literature, and dataset
adapters.

## License and citation

Code is [Apache-2.0](LICENSE). The guide, explanatory documentation, and
bundled profile data are CC BY 4.0; licensing details and third-party data
attributions are in [NOTICE](NOTICE). To cite this project, reference *The
Exergy Imperative* (Exergy Lab, 2026),
https://github.com/cdimurro/the-exergy-imperative.

---

Published by **[Exergy Lab](https://exergy-lab.com)** — a platform for
accelerating scientific discovery and technological innovation, purpose-built
for energy and deep-tech industries. Free for anyone to use.
