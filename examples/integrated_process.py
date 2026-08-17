from pathlib import Path

import exergy_imperative as xi

output = Path("output/integrated-process")
case = xi.assess_process(
    "steam",
    energy=10_000,
    country="USA",
    year=2025,
    annualization_factor=1.0,  # the input period is one year
    assessment_options={
        "efficiency": 0.88,
        "source_temperature": "180 C",
        "return_temperature": "90 C",
        "ambient_temperature": "20 C",
    },
    impact_options={
        "damage_costs_per_kg": {"NOx": 12, "SO2": 18},
        "currency": "USD",
    },
    economics_options={
        "capital_cost": 300_000,
        "energy_price_per_mwh": 42,
        "annual_maintenance_savings": 8_000,
        "carbon_price_per_tonne": 50,
        "project_life_years": 15,
        "discount_rate": 0.07,
    },
)

print(case.summary())
case.export_html(output / "report.html")
case.export_excel_compatible(output / "excel")
