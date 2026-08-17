# Data, defaults, and Fidelity Tiers

## Resolution order

The intended precedence is:

1. Explicit user override
2. Measured value in the current record
3. Site or organization profile
4. Dataset-derived value
5. Country or industry profile
6. Equipment or service profile
7. Global fallback

The library records the chosen value, basis, source, and warning. It does not
silently treat a default as a measurement.

## Fidelity

- **F0**: insufficient or untyped data; no factor is silently invented.
- **F1**: a declared carrier, technology, service, or process uses a profile.
- **F2**: asset-specific values replace the material assumptions.
- **F3**: synchronized interval telemetry produces dynamic results.
- **F4**: a full state-vector engineering analysis uses exact formulas or a
  property-provider integration.

The overall tier never hides field-level provenance. A result can mix a measured
temperature, a country/year electricity factor, and a profile efficiency.

## Bundled knowledge packs

The wheel includes four small, versioned resources:

- equipment, carrier, service, and reference profiles;
- 12 cross-industry process templates;
- IPCC AR6 20-year and 100-year warming potentials, combustion factors,
  pollutant ranges, and concise pollutant-health profiles;
- six recent years of electricity carbon-intensity data for 213 countries plus
  a world aggregate, derived from Ember data distributed through Our World in
  Data.

Grid lookup accepts common country names and ISO-like codes. A requested missing
year falls back explicitly to the closest earlier year, or the earliest year if
none is earlier, and records that choice. No location match falls back to the
world value only when a location was not supplied; an unknown supplied location
raises an error.

The generated grid pack records upstream source names, URLs, licenses, year, and
data version. Rebuild it with `scripts/update_global_electricity.py`; normal
library use is offline and deterministic.

## Important boundaries

- Grid intensity is aggregate lifecycle kg CO2e/MWh. The library carries it to
  both horizons because the underlying gas composition is not available.
- Fuel factors declare HHV or LHV basis. Do not mix bases without conversion.
- Typed units such as `MWh_LHV` and `MWh_HHV_CH4` select that basis; an
  inconsistent explicit `basis` is rejected.
- Default pollutant factors are broad stationary-combustion screening ranges,
  not permit-grade or stack-test emissions.
- Health text describes pollutant hazards. It does not calculate ambient
  concentration, dispersion, intake, population exposure, dose-response, cases,
  or individual clinical risk.
- Economic defaults such as a 7% discount rate and 20-year project life are
  editable scenario assumptions, not universal recommendations.

## Custom packs and overrides

Organizations can overlay thermodynamic profiles:

```python
registry = xi.load_registry_pack("my_profiles.json")
result = xi.assess(technology="my boiler", registry=registry)
```

They can also replace or extend environmental factors:

```python
factors = xi.load_impact_factor_pack("my_impact_factors.json")
impact = xi.assess_impacts(
    900,
    carrier="electricity",
    country="my-site-grid",
    factor_library=factors,
)
```

Explicit function arguments remain the final override. This is the preferred
path for supplier-specific electricity, stack testing, fuel composition,
refrigerant inventories, local damage costs, and organization-specific finance.

## Public datasets

`xi.list_datasets()` exposes source, geography, license, and capability metadata.
XAI4Heat files are processed locally. NASA POWER requests are explicit and may
be cached at a caller-selected path. Large external datasets are not silently
downloaded during an assessment.

Licensed datasets, including user-downloaded IEA workbooks, are not bundled,
mirrored, or automatically fetched. A user may extract values they are entitled
to use into ordinary mappings, JSON, or CSV and pass those values to the generic
weather, GHG, methane, impact, and technology-cost APIs. The user remains
responsible for complying with the source terms. Reports retain user-declared
source labels but do not imply that the upstream publisher endorsed the result.

## Reproducibility checklist

Retain:

- package, registry, factor, template, and schema versions;
- requested and resolved geography/year;
- method ID, boundary, energy unit, and HHV/LHV basis;
- field-level provenance and user overrides;
- uncertainty distributions, seed, and sample count;
- missing-data, interpolation, clipping, and filtering rules;
- currency, price year, discount rate, project life, and included externalities.
