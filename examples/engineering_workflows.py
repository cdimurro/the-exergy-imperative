"""Detailed engineering, waste-heat, and native Excel examples."""

from pathlib import Path

import exergy_imperative as xi

heat_pump = xi.analyze_heat_pump(
    delivered_heat_mwh=1_000,
    source_temperature_c=10,
    sink_temperature_c=60,
    cop=3.2,
)

matches = xi.match_waste_heat(
    sources=[
        {
            "name": "furnace exhaust",
            "available_heat_mwh": 600,
            "supply_temperature_c": 300,
            "minimum_outlet_temperature_c": 100,
        }
    ],
    demands=[
        {
            "name": "dryer",
            "required_heat_mwh": 450,
            "supply_temperature_c": 150,
            "return_temperature_c": 80,
        }
    ],
)

assert heat_pump.exergetic_efficiency > 0
assert matches.total_heat_recovered_mwh == 450
assert xi.run_bundled_validation_suite().passed

print(heat_pump.to_dict())
print(matches.to_dict())

# Create editable workbooks only when this example is run directly by a user.
if __name__ == "__main__":
    output = Path("output")
    output.mkdir(exist_ok=True)
    xi.create_excel_template("heat-pump", output / "heat-pump-input.xlsx")
    heat_pump.export_xlsx(output / "heat-pump-report.xlsx")
