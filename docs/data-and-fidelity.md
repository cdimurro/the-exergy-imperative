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

## Bundled knowledge resources

The wheel includes these small, versioned resources:

- equipment, carrier, service, and reference profiles;
- 12 cross-industry process templates;
- IPCC AR6 20-year and 100-year warming potentials, combustion factors,
  pollutant ranges, and concise pollutant-health profiles;
- six recent years of electricity carbon-intensity data for 213 countries plus
  a world aggregate, derived from Ember data distributed through Our World in
  Data.
- seven technology packs for buildings, power, mobility, water/materials, oil
  and gas, emerging energy, and advanced materials. Across 80 technologies, 50
  have an official-source performance or mass-normalized intensity prior;
  profiles without a boundary-compatible source retain explicit input
  requirements and a machine-readable reason.

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
- Unit scaling between two explicitly conflicting HHV/LHV typed units is also
  rejected because the relationship is fuel- and composition-specific.
- Default pollutant factors are broad stationary-combustion screening ranges,
  not permit-grade or stack-test emissions.
- Pollutant health text provides qualitative context. It does not calculate ambient
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

For a single versioned extension containing technology profiles and process
templates, use `load_technology_pack()` and validate it against the packaged
`technology-pack` schema. Numeric screening defaults require units, confidence,
ranges, sources, licenses, and applicable boundaries. See
[Connected systems and technology packs](systems-and-packs.md).

Bundled estimates span building heat pumps and VRF; renewable, thermal, and
power-conversion equipment; electric, fuel-cell, gasoline, and diesel vehicle
drivetrains; pumps, blowers, and induction heating; oil-and-gas pumping,
compression, recovery, and fired heaters; electrolyzers, fuel cells,
geothermal and nuclear power blocks, solar-thermal and supercritical-CO2 power
cycles, and long-duration storage; plus selected steel and aluminum production
intensities. Each estimate records its statistic, range basis, technology,
boundary, geography, vintage, source version, and source license. These are F1
screening inputs, not fleet distributions, measurements, forecasts, or site
guarantees.

Performance and production intensity are intentionally separate models.
`assess_performance_with_pack()` reports energy input and output but does not
invent an exergy factor for an unspecified heat state or fuel composition.
`assess_intensity_with_pack()` reports energy per declared product mass but
does not label that ratio as efficiency. `technology_pack_coverage()` reports
the available path and override fields for every technology.

Profiles without a defensible default retain required-input prompts. No
composition, leak-rate, reaction-yield, degradation, capacity factor, or cost
values are inferred from a performance prior. Material templates identify the
inventory needed to close a boundary; they are not material-property databases.
`MaterialStream` values default to F2 because they are caller-provided. Use F3
or F4 only when the declared provenance supports those evidence levels.

## Public datasets

`xi.list_datasets()` exposes source, geography, license, and capability metadata.
XAI4Heat files are processed locally. NASA POWER requests are explicit and may
be cached at a caller-selected path. Large external datasets are not silently
downloaded during an assessment.

Optional World Bank WDI and ERA5-Land connectors make network access explicit.
Local EDGAR, EPA eGRID, DOE ITAC/IAC, and FIED normalizers contain publisher
schema knowledge but no publisher values. Each local result retains a file
hash, source terms, declared units, assumptions, and scope warnings. See the
[external-data integration guide](external-data-integrations.md) for install,
configuration, command-line, Python, and coding-agent workflows.

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
- missing-data, interpolation, truncation, and filtering rules;
- currency, price year, discount rate, project life, and included externalities.
