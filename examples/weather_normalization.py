"""Normalize daily plant energy to a declared normal-weather period."""

import exergy_imperative as xi

reference_weather = [
    {"date": "2024-01-01", "temperature_c": 2.0},
    {"date": "2024-01-02", "temperature_c": 6.0},
    {"date": "2024-07-01", "temperature_c": 24.0},
    {"date": "2024-07-02", "temperature_c": 28.0},
]
plant_records = [
    {"date": "2026-01-01", "temperature_c": 0.0, "energy_mwh": 42.0},
    {"date": "2026-01-02", "temperature_c": 8.0, "energy_mwh": 25.0},
]

climatology = xi.monthly_weather_climatology(
    reference_weather,
    heating_base_c=18.0,
    cooling_base_c=20.0,
    source="local reference weather",
)
result = xi.normalize_weather_performance(
    plant_records,
    value_field="energy_mwh",
    metric="plant energy",
    unit="MWh",
    climatology=climatology,
)
print(result.to_dict())
