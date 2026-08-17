# Industrial engineering models

The detailed engineering API complements the sparse-input process templates.
Use it when measured or design inputs are available and keep the progressive
assessment when they are not.

## Steam systems

`analyze_steam_system()` separates boiler generation, distribution loss,
blowdown, delivered heat, and the heat-quality factor at the declared steam and
reference temperatures. It is a screening balance, not a steam-property model;
use the optional CoolProp physical-exergy API for state-point work.

## Heat pumps and refrigeration

`analyze_heat_pump()` and `analyze_refrigeration()` compare the entered COP with
the corresponding Carnot limit. Both return energy and exergy efficiency, the
electricity requirement, temperatures, and explicit model assumptions.

## Furnaces and compressed air

`analyze_furnace()` reports useful process heat, exhaust heat and exhaust
exergy, unaccounted energy, and fuel-to-product exergy efficiency.
`analyze_compressed_air()` estimates reversible isothermal pressure exergy,
then separates leakage and excess-pressure losses. It deliberately excludes
humidity, compressor heat recovery, storage transients, and detailed pressure
drops.

## Waste-heat matching

`match_waste_heat()` accepts multiple named sources and demands. A match must
pass both a minimum approach temperature and an exergy-quality check. The
hottest demands are served first, and every match reports recovered heat,
source exergy, useful exergy, and quality loss.

```python
result = xi.match_waste_heat(
    sources=[{
        "name": "kiln exhaust",
        "available_heat_mwh": 100,
        "supply_temperature_c": 300,
        "minimum_outlet_temperature_c": 100,
    }],
    demands=[{
        "name": "dryer",
        "required_heat_mwh": 60,
        "supply_temperature_c": 150,
        "return_temperature_c": 80,
    }],
)
```

The matcher is intentionally transparent and deterministic. It is not pinch
optimization, a heat-exchanger network design, or a substitute for equipment
and safety engineering.

Primary method references are retained in each result. The steam and compressed
air screens cite US Department of Energy sourcebooks; the furnace and waste-heat
screens cite the DOE Process Heating Sourcebook.
