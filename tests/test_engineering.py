import pytest

import exergy_imperative as xi


def test_steam_system_tracks_blowdown_distribution_and_quality():
    result = xi.analyze_steam_system(
        fuel_energy_mwh=1000,
        boiler_efficiency=0.8,
        distribution_loss_fraction=0.05,
        blowdown_energy_mwh=20,
        steam_temperature_c=180,
    )
    assert result.useful_energy_mwh == pytest.approx(740)
    assert result.recoverable_energy_mwh == pytest.approx(60)
    assert result.metrics["steam_generated_mwh"] == pytest.approx(800)
    assert 0 < result.exergetic_efficiency < result.energy_efficiency


def test_steam_system_marks_declared_efficiency_unused_for_provided_output():
    result = xi.analyze_steam_system(
        fuel_energy_mwh=100,
        steam_output_mwh=81,
        boiler_efficiency=0.8,
        distribution_loss_fraction=0,
    )

    assert result.metrics["implied_boiler_efficiency"] == pytest.approx(0.81)
    assert result.assumptions["declared_boiler_efficiency_not_used"] == pytest.approx(
        0.8
    )
    assert "boiler_efficiency" not in result.assumptions
    assert any("was not used" in warning for warning in result.warnings)


def test_heat_pump_and_refrigeration_compare_with_carnot_limits():
    heat_pump = xi.analyze_heat_pump(
        delivered_heat_mwh=100,
        source_temperature_c=10,
        sink_temperature_c=60,
        cop=3,
    )
    refrigeration = xi.analyze_refrigeration(
        cooling_delivered_mwh=100,
        cold_temperature_c=-10,
        ambient_temperature_c=30,
        cop=2.5,
    )
    assert heat_pump.energy_efficiency == pytest.approx(3)
    assert heat_pump.metrics["carnot_cop"] > 3
    assert refrigeration.energy_efficiency == pytest.approx(2.5)
    assert refrigeration.metrics["carnot_cop"] > 2.5
    with pytest.raises(ValueError, match="Carnot"):
        xi.analyze_heat_pump(
            delivered_heat_mwh=1,
            source_temperature_c=10,
            sink_temperature_c=60,
            cop=20,
        )


def test_furnace_and_compressed_air_expose_recovery_opportunities():
    furnace = xi.analyze_furnace(
        fuel_energy_mwh=1000,
        thermal_efficiency=0.6,
        exhaust_energy_mwh=150,
    )
    air = xi.analyze_compressed_air(
        electricity_mwh=1000,
        free_air_volume_m3=5_000_000,
        delivery_pressure_bar_abs=8,
        end_use_pressure_bar_abs=6,
        leak_fraction=0.1,
    )
    assert furnace.recoverable_energy_mwh == pytest.approx(150)
    assert furnace.metrics["recoverable_exhaust_exergy_mwh"] > 0
    assert air.recoverable_energy_mwh > 0
    assert air.useful_exergy_mwh < air.input_exergy_mwh


def test_furnace_reconciles_measured_heat_with_declared_efficiency():
    furnace = xi.analyze_furnace(
        fuel_energy_mwh=100,
        useful_process_heat_mwh=90,
        thermal_efficiency=0.6,
    )
    assert furnace.energy_efficiency == pytest.approx(0.9)
    assert furnace.metrics["implied_thermal_efficiency"] == pytest.approx(0.9)
    assert furnace.assumptions["declared_thermal_efficiency_not_used"] == pytest.approx(
        0.6
    )
    assert "thermal_efficiency" not in furnace.assumptions
    assert any("was not used" in warning for warning in furnace.warnings)


def test_waste_heat_matching_prioritizes_hot_demands_and_reports_quality_loss():
    result = xi.match_waste_heat(
        [
            {
                "name": "kiln exhaust",
                "available_heat_mwh": 100,
                "supply_temperature_c": 300,
                "minimum_outlet_temperature_c": 100,
            },
            {
                "name": "cooling water",
                "available_heat_mwh": 80,
                "supply_temperature_c": 70,
                "minimum_outlet_temperature_c": 35,
            },
        ],
        [
            {
                "name": "dryer",
                "required_heat_mwh": 60,
                "supply_temperature_c": 150,
                "return_temperature_c": 80,
            },
            {
                "name": "wash water",
                "required_heat_mwh": 90,
                "supply_temperature_c": 50,
                "return_temperature_c": 30,
            },
        ],
        minimum_approach_temperature_c=10,
    )
    assert result.total_heat_recovered_mwh == pytest.approx(150)
    assert result.matches[0].demand == "dryer"
    assert result.total_quality_loss_mwh >= 0
    assert result.unmet_demand_heat_mwh["wash water"] == pytest.approx(0)
    assert xi.report_view(result).charts


def test_engineering_models_reject_inconsistent_balances():
    with pytest.raises(ValueError, match="distribution loss plus blowdown"):
        xi.analyze_steam_system(
            fuel_energy_mwh=100,
            boiler_efficiency=0.5,
            distribution_loss_fraction=0.2,
            blowdown_energy_mwh=45,
        )
    with pytest.raises(ValueError, match="exceeds fuel energy"):
        xi.analyze_furnace(
            fuel_energy_mwh=100,
            useful_process_heat_mwh=90,
            exhaust_energy_mwh=20,
        )


def test_waste_heat_matching_enforces_cold_end_approach_temperature():
    result = xi.match_waste_heat(
        [
            {
                "name": "source",
                "available_heat_mwh": 175,
                "supply_temperature_c": 200,
                "minimum_outlet_temperature_c": 25,
            }
        ],
        [
            {
                "name": "demand",
                "required_heat_mwh": 175,
                "supply_temperature_c": 60,
                "return_temperature_c": 50,
            }
        ],
        minimum_approach_temperature_c=10,
        reference_temperature_c=25,
    )
    assert result.total_heat_recovered_mwh == pytest.approx(140)
    assert result.unmatched_source_heat_mwh["source"] == pytest.approx(35)
    assert result.unmet_demand_heat_mwh["demand"] == pytest.approx(35)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("supply_temperature_c", float("nan")),
        ("supply_temperature_c", float("inf")),
        ("minimum_outlet_temperature_c", float("nan")),
        ("minimum_outlet_temperature_c", float("-inf")),
    ],
)
def test_waste_heat_matching_rejects_nonfinite_source_temperatures(field, value):
    source = {
        "name": "source",
        "available_heat_mwh": 100,
        "supply_temperature_c": 200,
        "minimum_outlet_temperature_c": 50,
    }
    source[field] = value

    with pytest.raises(ValueError, match="must be finite"):
        xi.match_waste_heat(
            [source],
            [
                {
                    "name": "demand",
                    "required_heat_mwh": 50,
                    "supply_temperature_c": 80,
                    "return_temperature_c": 40,
                }
            ],
        )
