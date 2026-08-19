# Changelog

## 0.6.1 - 2026-08-18

- Added the versioned Quantity and Quality cross-product conformance contract,
  public loader, `exergy validate --conformance`, consumer CI drift checks, and
  valid/invalid regression cases for every shared kernel.
- Added a reproducible industrial-data pilot that maps a meter export, preserves
  its audit trail, separates energy/exergy/emissions/economics, ranks three
  opportunities, and writes a screening business-case report.
- Added the common three-product ecosystem map and linked the browser and
  canonical reporting layers directly from the project overview.

## 0.6.0 - 2026-08-18

- Expanded the bundled scientific suite from 5 to 31 reference, analytic,
  conservation, and structural cases spanning thermodynamics, unit
  conversions, engineering screens, emissions, methane chemistry, economics,
  weather, uncertainty, and connected energy/material balances.
- Added a machine-readable scientific coverage ledger and JSON Schema. Every
  exported scientific function must be classified as reference/analytic,
  cross-implementation, conservation, structural, screening-only,
  external-data-required, or interface-only. `exergy validate --coverage`
  exposes the classifications and limitations.
- Corrected furnace exhaust exergy to integrate a sensible stream cooling to
  the reference temperature; explicit HHV/LHV cross-basis conversion now
  fails; impossible reference environments fail early; and inconsistent
  balances no longer report negative inferred exergy destruction.
- Changed bounded normal sampling from clipping to rejection-sampled
  truncation and made methane density reference conditions and LHV basis
  explicit.
- Added full primary-source provenance checks, NIST/EPA/IPCC pinning,
  methane-combustion elemental closure, system unit invariance, and a rule
  preventing any project capability from being labeled decision-grade without
  site evidence.
- Added an explicit `published_estimate` contract and expanded the seven domain
  packs to 80 technology profiles. Fifty technologies have at least one sourced
  automatic screening path: 48 efficiency/COP priors and three
  mass-normalized steel/aluminum intensity priors, with one overlapping
  technology. Results expose source version, statistic, range basis,
  applicability, and an override warning; explicit inputs replace the prior,
  while strict mode rejects it.
- Added conditional prior selection for equipment class, capacity, phase,
  temperature, and other declared context. A family fallback remains visible
  when no variant matches; context never silently changes geography, year,
  profile, or units.
- Added separate `technology-performance` and `technology-intensity` results,
  schemas, CLI commands, agent workflows, and MCP tools. The performance path
  can estimate energy output without inventing heat/fuel exergy quality, while
  the intensity path preserves a product-mass functional unit and never labels
  energy intensity as conversion efficiency.
- Added per-technology coverage reporting through
  `technology_pack_coverage()`, `exergy pack-coverage`, and MCP. Every profile
  now reports either its sourced screening path or an explicit-input reason and
  checklist.

### Additional 0.6.0 changes

- Added first-class mass and constituent accounting with explicit material
  streams, signed inventory accumulation, mass-unit conversion, component and
  whole-system closure, and optional chemical-exergy reconciliation.
- Kept material, energy, and exergy ledgers separate. Incomplete chemical
  exergy is omitted, and a complete chemical residual is never labeled
  destruction without heat, work, and reaction accounting.
- Replaced the fixed three-name technology-model list with a validated,
  extensible registry. Added compressor/pump, turbine/expander, electrolyzer,
  fuel-cell, storage, heat-to-power, and separation contracts plus generic
  custom performance inputs.
- Added `oil-gas`, `emerging-energy`, and `advanced-materials` packs spanning
  upstream/midstream/LNG/refining equipment, hydrogen, geothermal, nuclear,
  carbon management, long-duration storage, marine energy, metals, cement,
  chemicals, critical minerals, batteries, and recycling.
- Added 20 material-boundary templates for petroleum processing, carbon
  capture, hydrogen storage, iron and steel, clinker, aluminum, glass,
  chemicals, mineral beneficiation, battery materials, and recycling. They
  require explicit inventories and contain no performance or composition
  defaults.
- Added material and model workflows across Python, CLI, agent recipes, and MCP,
  plus packaged schemas, examples, capability search, documentation, and
  regression tests. Agent recipe contract version remains `1.0`.

## 0.5.0 - 2026-08-18

- Added connected-system accounting with eleven generic component kinds,
  explicit internal/resource/product/loss flows, separate energy and exergy
  balances, component hotspots, storage accumulation, and whole-system
  reconciliation.
- Added chronological system records with representative-period weights,
  interval-quantity safeguards, per-snapshot results, and net-storage horizon
  aggregation that avoids double-counting charge/discharge turnover.
- Added the versioned `technology-pack` contract and public loaders for local
  carrier, service, technology, and process-template overlays. Pack validation
  requires source, license, applicable boundary, unit, confidence, and ranges
  for screening defaults.
- Added data-only `buildings`, `power`, `mobility`, and `water-materials`
  starter packs. They provide technology mappings but intentionally require
  explicit COP or efficiency inputs.
- Added capability search and richer unknown-profile/template suggestions,
  plus pack, system, and time-series workflows across Python, CLI, agent
  recipes, and MCP without changing recipe contract version `1.0`.
- Added packaged schemas, a safe pack scaffold command, connected-system
  examples, documentation, and regression coverage for custom packs, system
  boundaries, provenance, storage, and agent recovery.

- Added a release-specific cache key to the dynamic PyPI README badge so
  GitHub refreshes it promptly after publication.

## 0.4.3 - 2026-08-18

- Added literature-anchored golden-value tests: steam-table flow exergy
  (8 MPa / 500 °C) through both the CoolProp backend and the dependency-free
  formula, the Petela (2003) radiative factor, real-fluid versus ideal-gas
  compressed-air agreement, the textbook R·T₀·ln 2 separation minimum, and
  Carnot benchmarks from the guide. Documented in `docs/validation.md`.
- Standardized prose references as "The Exergy Imperative" while retaining
  `exergy-imperative` in package, CLI, MCP, and workbook contexts.
- Moved the guide's software pointer above its title so the repository and
  package entry point is visible immediately.
- Added a release-version consistency regression test and enforced Ruff
  formatting in CI.
- Version 0.4.2 was not published.

## 0.4.1 - 2026-08-17

- Republished so the PyPI project page renders the current README: The Exergy
  Imperative title, the version-agnostic status section, and the revised
  framing and wording. No functional code changes.
- Made the library documentation status line version-agnostic as well.

## 0.4.0 - 2026-08-17

- Retitled the README and widened it to any energy carrier, technology, or
  process: universal exergy/anergy framing and a "Start from the physics"
  section of verified one-line examples.
- Consolidated project meta files: the documentation license terms moved into
  `NOTICE`, the changelog into `docs/changelog.md`, and the contributing guide
  into `.github/CONTRIBUTING.md`; `CITATION.cff` was replaced by a citation
  note in the README.
- Updated the GitHub repository description to match the README language.

## 0.3.0 - 2026-08-17

- Rewrote the repository README as the library front door (install, quickstart,
  positioning versus TESPy/ExerPy/process simulators, data provenance, and
  documentation index). This is also the page PyPI renders.
- Moved the complete guide to `THE_EXERGY_IMPERATIVE.md` with unchanged
  CC BY 4.0 licensing and a pointer from the guide to the library.
- Added optional World Bank WDI and authenticated ERA5-Land connectors with
  explicit network access, local caching or manifests, offline request
  construction, and publisher attribution.
- Added publisher-aware local normalizers for EDGAR country-sector emissions,
  EPA eGRID electricity factors, DOE ITAC/IAC recommendations and economics,
  and FIED industrial unit estimates. No raw publisher datasets are bundled.
- Added Excel-compatible CLI outputs, source-file fingerprints, unit
  normalization, scope and health-screening warnings, column overrides, and
  agent/MCP discovery for every external-data integration.

## 0.2.0 - 2026-08-15

- Added versioned agent recipes with execute, dry-run, and validate-only modes;
  stable success/error envelopes; capability, schema, and target discovery;
  universal CLI JSON behavior; and an optional MCP v2 server with structured
  tools, resources, and a planning prompt.
- Added recent country electricity-intensity histories for 213 countries plus
  a world fallback, with location, year, unit, license, and source provenance.
- Added AR6 20-year and 100-year warming potentials, fuel combustion
  inventories, refrigerant leakage, and toxic-air-pollutant health screening.
- Added NPV, IRR, simple and discounted payback, capital recovery, levelized
  cost, benefit-cost, and marginal abatement cost calculations.
- Added auditable CSV, Excel, Parquet, JSON, JSONL, and database ingestion with
  mapping inference, unit conversion, time zones, and missing-data policies.
- Added twelve industry process templates spanning steam, furnaces, compressed
  air, refrigeration, drying, desalination, hydrogen, data centers, cement,
  steel, food processing, and district energy.
- Added Monte Carlo propagation, sensitivity ranking, value of perfect
  information, scenario comparison, and avoided-exergy-destruction tools.
- Added dependency-free SVG charts, HTML reports, optional PDF reports, and
  Excel-compatible auditable report bundles. No Grassmann or Sankey diagrams
  are included in this release.
- Added machine-readable environmental, economic, and process result schemas.
- Expanded the command-line interface for factors, impacts, process templates,
  economics, ingestion, and reports.
- Added NASA POWER multi-variable weather records, degree days, monthly
  climatologies, anomalies, and weather normalization for energy or exergy.
- Added explicit combustion, process, fugitive, purchased-energy, and allocated
  electricity/heat GHG boundaries plus methane venting, flaring, oxidation, and
  recovery project analysis.
- Added annual fuel/carbon price paths, generic user-supplied technology cost
  scenarios, levelized useful-output cost, scenario comparison, and stranded
  asset sensitivity. No IEA dataset values are bundled or fetched.
- Added native Excel input templates, charted `.xlsx` reports, and auditable
  normalized-data workbooks.
- Added schema-driven local-file adapters, including field-only examples for
  user-downloaded Energy Institute and IEA workbooks; no publisher values are
  redistributed.
- Added published reference cases and an optional local XAI4Heat portfolio
  reproduction with machine-readable validation outcomes.
- Added detailed steam, heat-pump, furnace, refrigeration, compressed-air, and
  waste-heat matching screens with HTML, PDF, CSV/JSON, and Excel exports.
- Added lint and coverage gates, clean-wheel testing, Dependabot configuration,
  issue templates, security and conduct policies, and trusted PyPI publishing.

## 0.1.0

- Added dependency-free exergy formulas and unit conversion.
- Added progressive F0-F4 assessments with transparent defaults and ranges.
- Added versioned carrier, service, technology, and reference profiles.
- Added immutable refinement, provenance, and next-measurement guidance.
- Added process exergy balances and hotspot reporting.
- Added XAI4Heat-compatible CSV enrichment and portfolio summaries.
- Added public dataset catalog and explicit NASA POWER connector.
- Added CLI, JSON result schema, examples, tests, and packaging metadata.
