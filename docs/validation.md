# Validation

Run the independent, bundled reference calculations:

```bash
exergy validate
```

The packaged suite checks three thermal exergy factors and the heat-pump example
published in *The Exergy Imperative: A Quantity-and-Quality Standard Reporting
Framework*, plus the Petela exergy factor for undiluted solar radiation. Every
case records its expected value, tolerance, method, inputs, and citation in
`validation_cases.json`.

Python users can inspect every outcome:

```python
suite = xi.run_bundled_validation_suite()
assert suite.passed
for outcome in suite.outcomes:
    print(outcome.case_id, outcome.actual, outcome.expected, outcome.citation)
```

## Literature-anchored regression tests

The repository test suite additionally pins package results to values from
independent published sources (`tests/test_literature_validation.py`):

- Specific flow exergy of superheated steam at 8 MPa and 500 °C against
  standard steam-table values (IAPWS formulations, as tabulated in Cengel &
  Boles and equivalent references), exercised through both the optional
  CoolProp backend and the dependency-free formula.
- The Petela (2003) radiative exergy factor at the published 6000 K example
  (doi:10.1016/S0038-092X(03)00226-3).
- Real-fluid compressed-air exergy against the closed-form ideal-gas
  expression, two independent code paths that must agree.
- The textbook minimum work of separation for an ideal equimolar binary
  mixture, R·T₀·ln 2.
- Carnot factors at the benchmark temperatures published in The Exergy
  Imperative guide, and exact kinetic/potential exergy under standard
  gravity.

A regression in these tests means the package disagrees with published
literature, not merely with itself. They run in continuous integration on
every change.

## Optional XAI4Heat portfolio reproduction

The package does not distribute the XAI4Heat telemetry used in the paper. After
obtaining a local copy, run:

```bash
exergy validate --xai4heat path/to/local-file.csv
```

The comparison evaluates the five Table 9 weighted factors and their valid
interval counts. A mismatch is reported case by case and returns a nonzero CLI
status. Column aliases are handled by the existing XAI4Heat preprocessor.

Passing these checks demonstrates consistency with the declared equations and
published reference outputs. It does not validate site boundaries, sensor
quality, cost assumptions, exposure pathways, or fitness for a specific
engineering or investment decision.
