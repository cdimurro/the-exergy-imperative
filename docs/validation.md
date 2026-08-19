# Scientific validation

The project uses a coverage ledger instead of a blanket “validated” claim.
Every scientific capability is assigned one of these assurance levels:

The package also vendors Quantity and Quality's
`exergy_conformance_contract_v1` and runs every applicable valid and invalid
case in CI. The contract makes the shared reference temperature, solar source
temperature, formulas, numerical tolerances, and domain behavior explicit.
Both 20 °C and 25 °C Petela cases are tested: different user-facing defaults are
allowed only when the reference environment is declared, never as a silent
cross-product disagreement.

- `reference-validated`: pinned to values from an independent primary or
  authoritative source.
- `analytically-validated`: checked against an independently evaluated defining
  equation and limiting cases.
- `cross-implementation-validated`: compared with a separate property-model
  implementation.
- `conservation-validated`: checked for first-law, exergy, total-mass, and
  constituent closure.
- `structural-only`: the contract and arithmetic are tested, but the caller
  supplies the physical performance.
- `screening-only`: defaults are broad priors or approximations, never
  measurements or design values.
- `external-data-required`: code paths are tested locally, while scientific
  validity depends on publisher or site data not controlled by the package.
- `interface-only`: schemas, serialization, provenance, or transport are tested;
  the interface adds no scientific evidence to the calculation it carries.

No package capability is labeled decision-grade. That requires a verified site
boundary, calibrated measurements, decision-appropriate uncertainty, and
qualified engineering review.

## Run and inspect the checks

Run the 31 packaged scalar reference, analytic, conservation, and structural
cases:

```bash
exergy validate
```

Inspect the machine-readable coverage classification and its limitations:

```bash
exergy validate --coverage
```

Python exposes the same contracts:

```python
import exergy_imperative as xi

suite = xi.run_bundled_validation_suite()
assert suite.passed

coverage = xi.load_validation_coverage()
for item in coverage.items:
    print(item.id, item.level, item.decision_grade)
    for limitation in item.limitations:
        print("  -", limitation)
```

The source-controlled inputs are
`src/exergy_imperative/data/validation_cases.json` and
`src/exergy_imperative/data/validation_coverage.json`. Both results have
packaged JSON Schemas. Tests fail when a public scientific function lacks a
coverage classification, a case is orphaned, a cited test path disappears, or
a bundled numerical source lacks a license and applicable boundary.

## Current coverage summary

| Capability | Assurance | What is established | What remains external |
|---|---|---|---|
| Thermodynamic kernels | Reference / analytic | Carnot, cooling, sensible heat, Gouy–Stodola, physical flow, ideal gas, ideal mixture, mechanics, Petela | Boundary and state selection |
| Unit conversions and dead state | Reference | NIST energy conversions, temperature scale, physical environment checks, HHV/LHV conflict rejection | Fuel-specific HHV/LHV relationship |
| CoolProp property backend | Cross-implementation | Steam-table and ideal-gas comparison cases | Fluid model, mixture, and state-region suitability |
| Exergy, connected-system, and material ledgers | Conservation | Nonnegative destruction and energy/mass/constituent closure | Completeness of the user-declared boundary |
| Heat pump and refrigeration | Analytic | Carnot limits and exergetic efficiency | Measured COP and a valid environmental source/sink boundary |
| Furnace | Analytic screen | Isothermal process service and integrated sensible exhaust exergy | Material states, composition, excess air, radiation, and measured loss allocation |
| Steam and compressed air | Screening | Steam-table anchor and reversible pressure-exergy relation | Detailed steam states, humidity, transient storage, and measured equipment performance |
| IPCC/EPA factors and GHG arithmetic | Reference | AR6 GWP values, EPA/IPCC combustion conversions, methane oxidation stoichiometry | Site inventories, controls, lifecycle boundary, and gas composition |
| Economics | Analytic | NPV, capital recovery, payback, levelized-cost, and cash-flow arithmetic | Prices, taxes, financing, life, escalation, and decision assumptions |
| Uncertainty and EVPI | Analytic | Sampling contract, truncated bounded normal, statistics, ranks, paired-sample EVPI | Distribution validity, correlations, structural uncertainty |
| Weather | Analytic screen | Degree-day definitions and deterministic regression arithmetic | Baseline suitability, occupancy/production covariates, IPMVP compliance |
| Profile/process defaults | Screening only | Ranges, provenance, and warnings are enforced | Empirical site applicability and project savings |
| Technology and material packs | Screening/interface | All 48 performance and three intensity priors execute with bounded results; representative CSP and EAF source conversions are packaged validation cases; derived composite/conversion values are independently recomputed in tests; override/strict behavior, discovery, boundaries, coverage status, and provenance are enforced | Site applicability, fleet distributions, composition, yield, leakage, degradation, and cost |
| External publisher adapters | External data required | Field mapping, units, hashes, provenance, and failure behavior | Publisher revisions and scientific fitness of the retrieved data |

The complete, API-level matrix is returned by `load_validation_coverage()`.

## Independent anchors

The suite and repository tests use these authoritative anchors:

- [NIST CODATA 2022](https://physics.nist.gov/cuu/pdf/all.pdf) for physical
  constants and standard gravity.
- [NIST Guide to the SI, Appendix B](https://www.nist.gov/pml/special-publication-811/nist-guide-si-appendix-b-conversion-factors)
  for exact Btu and therm conversions.
- [IPCC AR6 WGI Chapter 7](https://www.ipcc.ch/report/ar6/wg1/chapter/chapter-7/)
  for 20- and 100-year global warming potentials.
- [US EPA GHG Emission Factors Hub 2025](https://www.epa.gov/system/files/documents/2025-01/ghg-emission-factors-hub-2025.pdf)
  for HHV stationary-combustion factors.
- [2006 IPCC Guidelines, Volume 2, Chapter 2](https://www.ipcc-nggip.iges.or.jp/public/2006gl/pdf/2_Volume2/V2_2_Ch2_Stationary_Combustion.pdf)
  for net-calorific-value stationary-combustion factors.
- [NIST Chemistry WebBook methane data](https://webbook.nist.gov/cgi/cbook.cgi?ID=C74828&Mask=629&Units=CAL)
  for methane molecular weight and thermochemistry.
- [US DOE Process Heating System Sourcebook](https://www1.eere.energy.gov/manufacturing/tech_assistance/pdfs/process_heating_sourcebook2.pdf)
  for the furnace exhaust sensible-heat boundary.
- [US DOE Technical Reference Manuals](https://www.energy.gov/sites/default/files/2021-07/technical-reference-manuals.pdf)
  for degree-day definitions.
- [NIST life-cycle costing methodology](https://nvlpubs.nist.gov/nistpubs/Legacy/BSS/nbsbuildingscience113.pdf)
  for discounted cash-flow conventions.
- Petela, “Exergy of undiluted thermal radiation,”
  [doi:10.1016/S0038-092X(03)00226-3](https://doi.org/10.1016/S0038-092X(03)00226-3).

The optional CoolProp test compares a real-fluid implementation with published
steam-table values and a separate ideal-gas calculation. This is stronger than
testing one code path against itself, but it still does not validate every
fluid or state.

## Corrections made by the project-wide audit

The expanded audit found and corrected several unsafe behaviors:

- Furnace exhaust exergy now integrates a constant-heat-capacity stream while
  cooling from exhaust temperature to the reference temperature. Treating the
  entire exhaust quantity as isothermal heat at its inlet temperature
  overstated the 300 °C / 25 °C factor from about 0.480 to 0.291.
- Explicit `HHV` to `LHV` unit conversions now fail unless the caller performs
  a fuel-specific conversion. Unit scaling alone cannot change calorific basis.
- Inconsistent exergy balances retain a negative closure residual and clamp
  inferred destruction at zero; negative destruction is never returned.
- Reference environments reject nonfinite temperatures and pressures,
  temperatures at or below absolute zero, and nonpositive pressure.
- Bounded normal uncertainty inputs are rejection-sampled as truncated normal
  distributions rather than clipped into artificial probability masses at the
  bounds.
- Methane volume conversion now reports the default reference conditions
  (pure methane at 0 °C and 101.325 kPa) and explicitly labels its energy
  content as LHV.

## Real-world data validation

Real-world operational validation is not the same as a golden equation test.
The package does not redistribute proprietary plant telemetry or claim that a
generic profile predicts a particular asset. The XAI4Heat portfolio
reproduction remains available when the user supplies the underlying records:

```bash
exergy validate --xai4heat path/to/local-file.csv
```

That check compares five published portfolio weighted factors and valid-interval
counts. The domain packs can additionally reproduce their declared published
source values and ranges, and every bundled prior is exercised through its
actual public calculation path. That validates transcription, unit conversion,
selection, arithmetic, range propagation, provenance, serialization, and
override behavior.

It does not establish that a family prior predicts a particular asset. Oil and
gas, advanced materials, electrolysis, carbon capture, nuclear, geothermal,
storage, and other technologies still need openly licensed operational data
with matching boundaries for empirical asset-level validation. Profiles with a
compatible public value therefore remain F1 screening estimates; profiles
without one remain explicit-input contracts.

Passing the suite means the package agrees with the declared equations,
constants, source values, conservation identities, and tolerances. It does not
validate site boundaries, sensor calibration, pollutant exposure, equipment
design, cost assumptions, or fitness for a particular decision.
