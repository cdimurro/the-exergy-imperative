# Connected systems and technology packs

Named profiles are convenient, but no finite built-in list can cover every
technology. Versions 0.5 and 0.6 add complementary extension paths:

- technology packs add data-only carriers, services, technologies, and process
  templates without changing package code;
- connected systems compose explicit flows around generic component boundaries.
- material balances close mass and named constituents without treating mass as
  energy or unexplained chemical exergy as destruction;
- registered technology-model contracts let packs name their performance
  parameter and valid range without embedding an opaque solver.

Neither path is an equipment-design solver. Performance is supplied by the
caller, a cited screening prior, or the output of another simulator.

## Bundled starter packs

The `buildings`, `power`, `mobility`, `water-materials`, `oil-gas`,
`emerging-energy`, and `advanced-materials` packs add common technology
mappings. The packs contain 80 technology profiles. Fifty have at least one
official-source screening path: 48 performance priors and three
mass-normalized energy-intensity priors, with secondary-metal remelting in both
groups. The remaining 30 stay discoverable with an explicit reason and input
checklist because a cross-technology default would misstate their boundary.

Use `technology_pack_coverage()` or `exergy pack-coverage` before selecting a
calculation path:

```python
coverage = xi.technology_pack_coverage("emerging-energy")
coverage["automatic_estimate_count"]  # 15 of 22
```

`assess_performance_with_pack()` calculates an energy output from a sourced
efficiency or COP without inventing the exergy quality of heat or fuel:

```python
csp = xi.assess_performance_with_pack(
    "emerging-energy",
    "concentrating-solar-power-block",
    input_energy=100,
)
csp.output_energy.formatted()  # 40 MWh (screening range 35-45)
```

For production technologies whose honest public basis is energy per product
mass, use the separate intensity model:

```python
steel = xi.assess_intensity_with_pack(
    "advanced-materials",
    "electric-arc-furnace-melting",
    output_mass=100,
    output_unit="t",
)
```

Neither result reports exergy efficiency, emissions, hazards, or economics.
Those ledgers require their own compatible inputs. Use `assess_with_pack()` for
a complete energy/exergy assessment when the relevant exergy factor or state
data are available:

```python
import exergy_imperative as xi

xi.list_bundled_technology_packs()

result = xi.assess_with_pack(
    "buildings",
    technology="ground-source heat pump",
    energy=100,
    source_temperature="45 C",
    ambient_temperature="20 C",
)

result.parameters["cop"].status       # ValueStatus.PUBLISHED_ESTIMATE
result.parameters["cop"].applicability
site_result = result.refine(cop=4.2)
```

Supplying a pack never changes the global default registry. The same pack works
through the CLI and recipe interfaces:

```bash
exergy assess --pack buildings --technology "ground-source heat pump" --cop 4.2
exergy performance emerging-energy concentrating-solar-power-block 100 --json
exergy intensity advanced-materials electric-arc-furnace-melting 100 --unit t --json
exergy packs --json
exergy pack-coverage emerging-energy --json
exergy pack-validate buildings --json
```

## Creating a pack

Generate a local scaffold and validate it before use:

```bash
exergy pack-scaffold my_pack.json
exergy pack-validate my_pack.json --json
```

The versioned `technology-pack` schema requires a license and a source with an
applicable boundary. Every numeric screening parameter requires a unit,
confidence label, and range. Exact values and declared conventions do not need
a range. A technology with no default must list its required performance input,
which keeps an unknown value from becoming an invented assumption.

A `published_estimate` additionally requires its own `source_id`,
`source_version`, `statistic`, `range_basis`, and applicability fields for
technology, boundary, geography, and vintage. Assessment results label these
values as F1 assumptions and warn that they are not measured site performance.
Pass `strict=True` to reject them, supply `efficiency=...`, `cop=...`, or
`performance=...` to replace one immediately, or call `result.refine(...)`.

Python callers can use an in-memory object without a file write:

```python
pack = xi.load_technology_pack(pack_payload)
check = xi.validate_technology_pack(pack)
registry = pack.registry()
catalog = pack.process_catalog(registry=registry)
models = pack.model_registry()
```

Packs may also contain `material_templates`. These are boundary and
required-input checklists, not material-property databases. For example,
`oil-gas` contains production-separator, gas-processing, LNG, crude
distillation, refinery-hydrogen, flare/vent/recovery, and produced-water
templates. `advanced-materials` covers ironmaking, steelmaking, clinker,
aluminum, glass, chemicals, beneficiation, battery materials, and recycling.

## Technology-model contracts

The model registry describes the deliberately simple relation used by sparse
assessments: useful energy equals input energy multiplied by an explicit
performance parameter. Built-in contracts include converters, heat pumps,
chillers, compressors/pumps, turbines/expanders, electrolyzers, fuel cells,
storage, heat-to-power systems, and separation systems.

```python
result = xi.evaluate_technology_model(
    "electrolyzer",
    input_energy=100,
    performance=0.67,
    input_exergy_factor=1.0,
    output_exergy_factor=1.0,
)
```

A pack can add a declarative contract under `technology_models`. Custom
performance names use the generic `performance` assessment input. The only
supported pack relation is `input-times-performance`; nonlinear, multi-input,
or state-dependent equipment belongs in a connected system or dedicated
engineering model.

## Material and composition balances

`analyze_material_system()` accepts `MaterialStream` objects with mass,
composition, source, target, role, and an optional explicitly supplied specific
chemical exergy:

```python
result = xi.analyze_material_system(
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
        {
            "id": "tailings",
            "mass": 20,
            "source": "separator",
            "role": "loss",
            "material": "gangue",
        },
    ],
)
```

Composition fractions must sum to one. Supported mass units are kilograms,
grams, metric tonnes, pounds, and short tons; output is normalized to
kilograms. Signed material accumulations reconcile tanks, stockpiles, reactors,
and other inventories.

Chemical-exergy totals appear only when every participating stream and
accumulation has `specific_chemical_exergy_mj_per_kg`. The resulting residual
is called *unreconciled chemical exergy*, not destruction, because a defensible
destruction calculation also needs heat, work, and reaction accounting. The
material result remains separate from the energy result to prevent fuel
chemical exergy from being counted twice.

```bash
exergy material-balance examples/material_recipe.json --json
exergy models --json
exergy model-evaluate model_case.json --json
```

## Connected-system contract

A system contains components, flows, and optional storage accumulations.
Components use a small vocabulary rather than sector-specific equations:

```python
components = [
    {"id": "boiler", "kind": "converter"},
    {"id": "process", "kind": "sink"},
]
```

Supported kinds are `source`, `sink`, `converter`, `heater-cooler`,
`heat-exchanger`, `mixer-splitter`, `compressor-pump`, `turbine-expander`,
`reactor-separator`, `storage`, and `transport`.

Each flow is an interval energy quantity. Its exergy is supplied directly,
calculated from an explicit factor, or resolved from a named carrier:

```python
flows = [
    {
        "id": "fuel",
        "energy": 100,
        "unit": "MWh",
        "target": "boiler",
        "carrier": "natural gas",
    },
    {
        "id": "useful heat",
        "energy": 85,
        "source": "boiler",
        "target": "process",
        "exergy_factor": 0.18,
    },
    {
        "id": "stack and shell losses",
        "energy": 15,
        "exergy": 7,
        "source": "boiler",
        "role": "loss",
    },
    {
        "id": "process service",
        "energy": 85,
        "source": "process",
        "exergy_factor": 0.18,
    },
]

result = xi.analyze_system("process heat", components=components, flows=flows)
```

Boundary inputs have role `resource`, component-to-component flows have role
`internal`, and boundary outputs are `product` or `loss`. Roles can normally be
inferred from source and target, but inconsistent roles are rejected. Internal
flows cancel from the whole-system balance while remaining visible in component
balances.

The result contains separate first-law energy accounting and exergy accounting.
An unclosed energy residual is explicitly called *untracked energy*, never
energy destruction. Exergy destruction is inferred only after product exergy,
loss exergy, and storage change are accounted for.

## Storage and chronological records

Storage change is signed and belongs only to a `storage` component:

```python
{"component": "battery", "energy_change": 10, "carrier": "electricity"}
```

A positive value charges storage; a negative value releases it. Chronological
records carry a timestamp, flows, optional accumulations, and an optional
representative-period weight:

```python
series = xi.analyze_system_timeseries(
    "battery duty",
    components=[{"id": "battery", "kind": "storage"}],
    records=records,
)
```

All values remain interval energy quantities. `duration_hours` is retained as
metadata and never silently turns a power value into energy. Aggregate results
use external flows plus the net storage change over the horizon, avoiding
double-counting charge and discharge turnover.

## Recipes and interoperability

The additive recipe workflows are `custom-assessment`,
`custom-process-assessment`, `system-analysis`, `system-timeseries`,
`material-balance`, `technology-model`, `technology-performance`,
`technology-intensity`, `technology-pack-validation`, and `capability-search`.
They retain contract version `1.0`, including validate-only and dry-run
behavior. The MCP server exposes matching tools and never opens a port in
tests.

Detailed simulators should export interval energy/exergy flows into the system
contract. This preserves their state calculations while allowing this library
to add boundary reconciliation, provenance, emissions, hazards, uncertainty,
and economics without reimplementing TESPy, ExerPy, IDAES, EnergyPlus, pvlib,
PyPSA, or Brightway.

## Limits

- A component kind is accounting metadata, not an implicit equation.
- A pack definition is not evidence that a technology performs at a particular
  value; performance defaults still require a source, range, and boundary.
- Time-series data receive F3 only when the caller identifies synchronized
  measured records as F3. Chronology alone does not turn estimates into
  measurements.
- Transport functional units, pollutant exposure, permit calculations, and
  site-specific design remain separate from thermodynamic exergy.
- The remaining explicit-input oil-and-gas, emerging-energy, and
  advanced-material entries do not infer assays, compositions, leak rates,
  equipment curves, reaction yields, reservoir behavior, or process-emission
  inventories. A performance or intensity prior does not add any of those
  missing ledgers.
- A catalog entry does not imply technology maturity, economics, suitability,
  or regulatory compliance.
