"""Screen methane recovery with user-supplied project and price inputs."""

import exergy_imperative as xi

result = xi.assess_methane_project(
    annual_methane_mass_kg=25_000,
    methane_origin="biogenic",
    baseline_mode="vented",
    project_mode="recovered",
    project_efficiency=0.9,
    recovered_gas_price_per_mwh=40,
    capital_cost=150_000,
    annual_opex_increase=8_000,
    carbon_price_per_tonne=50,
    project_life_years=10,
)
print(result.to_dict())
