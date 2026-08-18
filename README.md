# exergy-imperative

[![CI](https://github.com/cdimurro/the-exergy-imperative/actions/workflows/ci.yml/badge.svg)](https://github.com/cdimurro/the-exergy-imperative/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/exergy-imperative)](https://pypi.org/project/exergy-imperative/)
[![Python](https://img.shields.io/badge/python-3.11%E2%80%933.14-blue)](https://pypi.org/project/exergy-imperative/)
[![License](https://img.shields.io/badge/code-Apache--2.0-green)](LICENSE)
[![Guide](https://img.shields.io/badge/guide-CC%20BY%204.0-lightgrey)](THE_EXERGY_IMPERATIVE.md)

**Screening-grade exergy, emissions, health, and economic analysis from the
industrial energy data you actually have.** Give it as little as an equipment
name and a country; every default it fills in stays visible, sourced, and
replaceable with your own measurements.

> 📖 This project began as **[The Exergy Imperative](THE_EXERGY_IMPERATIVE.md)**
> — a complete, free guide to exergy analysis and its role in the energy
> transition. Read it to understand *why* energy quality matters; use this
> library to put it to work.

## Why this library

Most exergy tools ([TESPy](https://github.com/oemof/tespy),
[ExerPy](https://github.com/oemof/exerpy), Aspen Plus) start from a fully
specified plant simulation. Real industrial decisions usually start earlier,
with a utility bill, a telemetry export, or a one-line description of a steam
system. `exergy-imperative` works at that end of the funnel:

- **Sparse input, transparent output.** Progressive-fidelity assessments (F0
  upward) from a bare technology name to measured site data. Every number
  carries provenance, a range, and warnings — screening defaults are never
  passed off as measurements.
- **The whole business case, not just thermodynamics.** Exergetic efficiency
  and destruction, AR6 20/100-year climate impact, air-pollutant health
  screening, and project economics (NPV, IRR, payback, levelized cost,
  marginal abatement cost) in one result.
- **Industrial data plumbing built in.** Auditable ingestion from CSV, Excel,
  Parquet, JSON, and SQL with unit conversion and mapping inference; native
  Excel input templates and workbook reports; weather normalization from NASA
  POWER; connectors for World Bank, ERA5-Land, EDGAR, eGRID, and DOE IAC data.
- **Agent-native.** Versioned JSON recipes with validate-only / dry-run /
  execute modes, stable error codes, capability discovery, and an optional
  [MCP server](docs/agent-integration.md) so AI assistants can drive full
  assessments safely.
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

Add whatever you know — efficiency, temperatures, energy prices, capital cost,
refrigerant leakage — and the fidelity, ranges, and economics tighten
accordingly. Then export deliverables:

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

## What's inside

- Twelve industry process templates: steam, furnaces, compressed air,
  refrigeration, drying, desalination, hydrogen electrolysis, data centers,
  cement, steel reheat, food processing, district energy.
- Engineering screens for steam systems, heat pumps, furnaces, refrigeration,
  compressed air, and waste-heat matching.
- Explicit GHG boundaries (combustion, process, fugitive, purchased energy),
  methane vent/flare/recovery project analysis, and grid intensities for 213
  countries (Ember / Our World in Data, 2020–2025).
- Monte Carlo uncertainty propagation, sensitivity ranking, and value of
  perfect information.
- Dependency-free SVG/HTML reports, optional PDF, and auditable
  Excel-compatible bundles with complete source payloads.
- Optional real-fluid physical exergy via [CoolProp](http://www.coolprop.org/)
  (`[properties]` extra).

## When to use it — and when not to

| Your situation | Use |
|---|---|
| Screening a plant, portfolio, or project idea from bills, telemetry, or one-line descriptions | **exergy-imperative** |
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
2006 fuel factors, EPA and EMEP/EEA pollutant screening profiles. No
restricted publisher data (IEA, Energy Institute) is redistributed — local
adapters map *your* licensed copies with SHA-256 fingerprinting. Run
`exergy validate` to execute the bundled reference calculations and see every
expected value, tolerance, and citation.

## Documentation

| Guide | What it covers |
|---|---|
| [Quickstart](docs/quickstart.md) | Install to first report |
| [Python library](docs/python-library.md) | Full API tour |
| [Engineering models](docs/engineering-models.md) | Equipment screens and their assumptions |
| [Environment, health, economics](docs/environment-health-economics.md) | Impacts and project finance |
| [Data & fidelity](docs/data-and-fidelity.md) | Fidelity tiers, units, boundaries |
| [Ingestion](docs/ingestion.md) · [Excel & local data](docs/excel-and-local-data.md) | Getting your data in |
| [External data integrations](docs/external-data-integrations.md) | World Bank, ERA5-Land, EDGAR, eGRID, IAC |
| [Agent integration](docs/agent-integration.md) | JSON recipes, discovery, MCP server |
| [Validation](docs/validation.md) | Reference checks and their scope |
| [Architecture](docs/architecture.md) | How the modules fit together |
| [**The Exergy Imperative**](THE_EXERGY_IMPERATIVE.md) | The complete guide to exergy and the energy transition |

## Status

`0.3.0` alpha. The public Python API, CLI commands, recipe contract `1.0`,
packaged JSON Schemas, and MCP tools are stable surfaces within a minor
version (see [AGENTS.md](AGENTS.md)). Contributions are welcome — especially
reviewed profiles, validation cases against published literature, and dataset
adapters; see [CONTRIBUTING.md](CONTRIBUTING.md).

## License and citation

Code is [Apache-2.0](LICENSE). The guide, explanatory documentation, and
bundled profile data are [CC BY 4.0](DOCUMENTATION_LICENSE.md); third-party
data attributions are listed in [NOTICE](NOTICE). Cite via
[CITATION.cff](CITATION.cff).

---

Published by **[Exergy Lab](https://exergy-lab.com)** — a platform for
accelerating scientific discovery and technological innovation, purpose-built
for energy and deep-tech industries. Free for anyone to use.
