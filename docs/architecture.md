# Architecture

The package keeps physics, data, decisions, and presentation separate so a user
can replace any default without rewriting the workflow.

| Layer | Modules | Responsibility |
|---|---|---|
| Thermodynamics | `formulas.py`, `balance.py`, `properties.py` | Exact kernels and process balances |
| Progressive assessment | `registry.py`, `assessment.py`, `models.py` | Resolve sparse inputs, provenance, fidelity, refinement |
| Environmental | `factors.py`, `impacts.py`, `ghg.py` | Grid/fuel/GWP factors, explicit GHG boundaries, methane projects, pollutant and health screening |
| Industry workflows | `processes.py`, `engineering.py` | Ready-to-use process boundaries, detailed equipment screens, and waste-heat matching |
| Economics and decisions | `economics.py`, `decision.py`, `uncertainty.py` | Cash flow, user-supplied technology costs, price paths, stranded costs, scenarios, sensitivity, Monte Carlo, EVPI |
| Data interoperability | `ingestion.py`, `adapters.py`, `preprocess.py`, `weather.py`, `validation.py`, `interop.py`, `schema.py` | Local licensed-data adapters, source-preserving ingestion, XAI4Heat, validation, weather normalization, schemas, conversions |
| Presentation | `reporting.py`, `excel.py`, `cli.py` | Basic charts, native Excel, HTML/PDF/CSV-JSON exports, command line |
| Agent integration | `agent.py`, `mcp_server.py` | Versioned recipes, capability discovery, structured errors, side-effect controls, and optional MCP tools/resources/prompts |

Exact formula functions never know whether an input was measured, downloaded,
or assumed. Factor packs do not contain thermodynamic equations. Reports consume
public result objects, so calculations can be tested independently of layout.

## Public stability boundary

Names exported from `exergy_imperative.__init__` are the public API. Packaged
JSON internals may gain fields, but stable IDs are not repurposed. New scientific
methods receive new method IDs, and top-level result payloads carry schema
versions.

Agent recipes are an orchestration boundary, not a second calculation engine.
They dispatch to the same public functions used by Python and the CLI. Recipe
contract version `1.0` permits additive workflows and optional fields but does
not permit repurposing existing workflow names, fields, modes, or error codes.

## Extension paths

- Add a registry pack for equipment, service, carrier, or reference values.
- Add an impact-factor pack for a geography, supplier, fuel, or pollutant.
- Add a process template that composes existing public engines.
- Add an ingestion mapping or adapter while retaining raw records.
- Add a property provider for detailed state calculations.
- Add a report renderer that consumes `AssessmentResult`,
  `EnvironmentalResult`, or `ProcessAssessment`.

An extension must not replace an explicit value without surfacing the conflict.
Health-impact models must retain their spatial, temporal, population, and
valuation boundaries.
