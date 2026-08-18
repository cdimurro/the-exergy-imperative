# Changelog

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
