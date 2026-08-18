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
independent published sources (`tests/test_literature_validation.py`). The
measured agreement:

| Check | Published anchor | Agreement |
|---|---|---|
| Flow exergy of superheated steam at 8 MPa / 500 °C (optional CoolProp backend) | Steam-table values (h = 3398.3 kJ/kg, s = 6.7240 kJ/kg·K; 25 °C dead state h₀ = 104.89, s₀ = 0.3674) → 1398.2 kJ/kg | within 0.02 % |
| Same steam case through the dependency-free `physical_flow_exergy` formula | Same steam-table values | exact |
| Compressed air at 1 MPa, 25 °C | Real-fluid backend versus closed-form R·T₀·ln(P/P₀) — two independent code paths | within 0.12 % |
| Radiative exergy factor at 6000 K / 300 K | Petela (2003), doi:10.1016/S0038-092X(03)00226-3 → 0.9333 | within 1×10⁻⁴ |
| Minimum work to separate an equimolar ideal binary mixture | R·T₀·ln 2 = 1.718 kJ/mol (Bejan; Moran & Shapiro) | exact |
| Carnot factors at 1500 °C, 80 °C, and 40 °C versus 20 °C ambient | Defining relation 1 − T₀/T, matching the benchmarks published in The Exergy Imperative guide | to five decimals |
| Kinetic and potential exergy | ½·m·v² and m·g·z with standard gravity 9.80665 m/s² (ISO 80000-3) | exact |

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
