"""Transparent engineering screens for common industrial energy systems."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .formulas import (
    cooling_exergy_factor_c,
    sensible_heat_exergy_factor_c,
    thermal_exergy_factor_c,
)

DOE_STEAM_SOURCE = (
    "https://www.energy.gov/sites/prod/files/2014/05/f15/steamsourcebook.pdf"
)
DOE_COMPRESSED_AIR_SOURCE = (
    "https://www1.eere.energy.gov/manufacturing/tech_assistance/pdfs/"
    "compressed_air_sourcebook.pdf"
)
DOE_PROCESS_HEATING_SOURCE = (
    "https://www1.eere.energy.gov/manufacturing/tech_assistance/pdfs/"
    "process_heating_sourcebook2.pdf"
)


def _number(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _positive(value: float, name: str) -> float:
    number = _number(value, name)
    if number <= 0.0:
        raise ValueError(f"{name} must be greater than zero")
    return number


def _nonnegative(value: float, name: str) -> float:
    number = _number(value, name)
    if number < 0.0:
        raise ValueError(f"{name} must be nonnegative")
    return number


def _fraction(value: float, name: str) -> float:
    number = _nonnegative(value, name)
    if number > 1.0:
        raise ValueError(f"{name} must be between zero and one")
    return number


@dataclass(frozen=True)
class EngineeringModelResult:
    """Common result contract for an explicit industrial engineering model."""

    model_id: str
    name: str
    input_energy_mwh: float
    useful_energy_mwh: float
    input_exergy_mwh: float
    useful_exergy_mwh: float
    exergy_destroyed_or_lost_mwh: float
    energy_efficiency: float
    exergetic_efficiency: float
    recoverable_energy_mwh: float
    metrics: Mapping[str, float | str]
    assumptions: Mapping[str, Any]
    sources: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "model_id": self.model_id,
            "name": self.name,
            "energy": {
                "input_mwh": self.input_energy_mwh,
                "useful_mwh": self.useful_energy_mwh,
                "efficiency": self.energy_efficiency,
                "recoverable_mwh": self.recoverable_energy_mwh,
            },
            "exergy": {
                "input_mwh": self.input_exergy_mwh,
                "useful_mwh": self.useful_exergy_mwh,
                "destroyed_or_lost_mwh": self.exergy_destroyed_or_lost_mwh,
                "efficiency": self.exergetic_efficiency,
            },
            "metrics": dict(self.metrics),
            "assumptions": dict(self.assumptions),
            "sources": list(self.sources),
            "warnings": list(self.warnings),
        }

    def export_html(self, path: str, **options: Any) -> Any:
        from .reporting import export_html

        return export_html(self, path, **options)

    def export_pdf(self, path: str, **options: Any) -> Any:
        from .reporting import export_pdf

        return export_pdf(self, path, **options)

    def export_excel_compatible(self, directory: str, **options: Any) -> Any:
        from .reporting import export_excel_compatible_report

        return export_excel_compatible_report(self, directory, **options)

    def export_xlsx(self, path: str, **options: Any) -> Any:
        from .excel import export_xlsx_report

        return export_xlsx_report(self, path, **options)


def _result(
    *,
    model_id: str,
    name: str,
    input_energy: float,
    useful_energy: float,
    input_exergy: float,
    useful_exergy: float,
    recoverable_energy: float,
    metrics: Mapping[str, float | str],
    assumptions: Mapping[str, Any],
    sources: tuple[str, ...],
    warnings: Iterable[str] = (),
) -> EngineeringModelResult:
    if useful_exergy > input_exergy + 1e-9:
        raise ValueError(
            "calculated useful exergy exceeds input exergy; review inputs and boundaries"
        )
    return EngineeringModelResult(
        model_id=model_id,
        name=name,
        input_energy_mwh=input_energy,
        useful_energy_mwh=useful_energy,
        input_exergy_mwh=input_exergy,
        useful_exergy_mwh=useful_exergy,
        exergy_destroyed_or_lost_mwh=max(input_exergy - useful_exergy, 0.0),
        energy_efficiency=useful_energy / input_energy if input_energy else 0.0,
        exergetic_efficiency=useful_exergy / input_exergy if input_exergy else 0.0,
        recoverable_energy_mwh=max(recoverable_energy, 0.0),
        metrics=dict(metrics),
        assumptions=dict(assumptions),
        sources=sources,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def analyze_steam_system(
    *,
    fuel_energy_mwh: float,
    steam_output_mwh: float | None = None,
    boiler_efficiency: float = 0.80,
    distribution_loss_fraction: float = 0.05,
    blowdown_energy_mwh: float = 0.0,
    steam_temperature_c: float = 180.0,
    reference_temperature_c: float = 25.0,
    fuel_exergy_factor: float = 1.0,
) -> EngineeringModelResult:
    """Screen steam generation, distribution loss, and delivered heat quality.

    The steam product is represented as heat delivered at the declared steam
    temperature. Use the CoolProp state-vector API for a detailed steam audit.
    """

    fuel = _positive(fuel_energy_mwh, "fuel_energy_mwh")
    efficiency = _fraction(boiler_efficiency, "boiler_efficiency")
    distribution_loss = _fraction(
        distribution_loss_fraction, "distribution_loss_fraction"
    )
    generated = (
        fuel * efficiency
        if steam_output_mwh is None
        else _nonnegative(steam_output_mwh, "steam_output_mwh")
    )
    if generated > fuel + 1e-9:
        raise ValueError("steam_output_mwh cannot exceed fuel_energy_mwh")
    blowdown = _nonnegative(blowdown_energy_mwh, "blowdown_energy_mwh")
    distribution_loss_energy = generated * distribution_loss
    if distribution_loss_energy + blowdown > generated + 1e-9:
        raise ValueError(
            "distribution loss plus blowdown energy cannot exceed generated steam energy"
        )
    delivered = generated - distribution_loss_energy - blowdown
    factor = thermal_exergy_factor_c(steam_temperature_c, reference_temperature_c)
    fuel_factor = _positive(fuel_exergy_factor, "fuel_exergy_factor")
    recoverable = distribution_loss_energy + blowdown
    warnings = [
        "Steam exergy uses an isothermal heat-product approximation; use fluid-state properties for an F4 audit."
    ]
    assumptions = {
        "distribution_loss_fraction": distribution_loss,
        "steam_temperature_c": steam_temperature_c,
        "reference_temperature_c": reference_temperature_c,
        "fuel_exergy_factor": fuel_factor,
        "steam_output_source": "calculated" if steam_output_mwh is None else "provided",
    }
    if steam_output_mwh is not None:
        implied = generated / fuel
        assumptions["declared_boiler_efficiency_not_used"] = efficiency
        if abs(implied - efficiency) > 1e-9:
            warnings.append(
                "Provided steam output implies a boiler efficiency of "
                f"{implied:.6g}; the declared boiler_efficiency of "
                f"{efficiency:.6g} was not used in the balance."
            )
    else:
        assumptions["boiler_efficiency"] = efficiency
    return _result(
        model_id="industrial.steam-system.v1",
        name="Industrial steam system",
        input_energy=fuel,
        useful_energy=delivered,
        input_exergy=fuel * fuel_factor,
        useful_exergy=delivered * factor,
        recoverable_energy=recoverable,
        metrics={
            "steam_generated_mwh": generated,
            "distribution_loss_mwh": distribution_loss_energy,
            "blowdown_energy_mwh": blowdown,
            "steam_heat_exergy_factor": factor,
            "implied_boiler_efficiency": generated / fuel,
        },
        assumptions=assumptions,
        sources=(DOE_STEAM_SOURCE,),
        warnings=warnings,
    )


def analyze_heat_pump(
    *,
    delivered_heat_mwh: float,
    source_temperature_c: float,
    sink_temperature_c: float,
    cop: float,
) -> EngineeringModelResult:
    """Compare an actual heat pump with the reversible Carnot heating COP."""

    heat = _nonnegative(delivered_heat_mwh, "delivered_heat_mwh")
    actual_cop = _positive(cop, "cop")
    source_k = _positive(source_temperature_c + 273.15, "source_temperature")
    sink_k = _positive(sink_temperature_c + 273.15, "sink_temperature")
    if sink_k <= source_k:
        raise ValueError("sink_temperature_c must exceed source_temperature_c")
    carnot_cop = sink_k / (sink_k - source_k)
    if actual_cop > carnot_cop + 1e-9:
        raise ValueError("cop cannot exceed the Carnot heating COP")
    electricity = heat / actual_cop
    product_factor = 1.0 - source_k / sink_k
    useful_exergy = heat * product_factor
    return _result(
        model_id="industrial.heat-pump.v1",
        name="Heat pump",
        input_energy=electricity,
        useful_energy=heat,
        input_exergy=electricity,
        useful_exergy=useful_exergy,
        recoverable_energy=0.0,
        metrics={
            "cop": actual_cop,
            "carnot_cop": carnot_cop,
            "heat_service_exergy_factor": product_factor,
            "electricity_mwh": electricity,
        },
        assumptions={
            "source_temperature_c": source_temperature_c,
            "sink_temperature_c": sink_temperature_c,
            "electricity_exergy_factor": 1.0,
        },
        sources=(),
    )


def analyze_furnace(
    *,
    fuel_energy_mwh: float,
    useful_process_heat_mwh: float | None = None,
    thermal_efficiency: float = 0.60,
    process_temperature_c: float = 800.0,
    exhaust_energy_mwh: float = 0.0,
    exhaust_temperature_c: float = 300.0,
    reference_temperature_c: float = 25.0,
    fuel_exergy_factor: float = 1.0,
) -> EngineeringModelResult:
    """Screen furnace product exergy and the quality of declared exhaust heat."""

    fuel = _positive(fuel_energy_mwh, "fuel_energy_mwh")
    efficiency = _fraction(thermal_efficiency, "thermal_efficiency")
    useful = (
        fuel * efficiency
        if useful_process_heat_mwh is None
        else _nonnegative(useful_process_heat_mwh, "useful_process_heat_mwh")
    )
    measured_useful_heat = useful_process_heat_mwh is not None
    implied_efficiency = useful / fuel
    exhaust = _nonnegative(exhaust_energy_mwh, "exhaust_energy_mwh")
    if useful + exhaust > fuel + 1e-9:
        raise ValueError("useful process heat plus exhaust energy exceeds fuel energy")
    product_factor = thermal_exergy_factor_c(
        process_temperature_c, reference_temperature_c
    )
    exhaust_factor = (
        thermal_exergy_factor_c(exhaust_temperature_c, reference_temperature_c)
        if exhaust
        else 0.0
    )
    fuel_factor = _positive(fuel_exergy_factor, "fuel_exergy_factor")
    assumptions = {
        "process_temperature_c": process_temperature_c,
        "exhaust_temperature_c": exhaust_temperature_c,
        "reference_temperature_c": reference_temperature_c,
        "fuel_exergy_factor": fuel_factor,
        "useful_heat_source": "provided" if measured_useful_heat else "calculated",
    }
    warnings: list[str] = []
    if measured_useful_heat:
        assumptions["declared_thermal_efficiency_not_used"] = efficiency
        if abs(implied_efficiency - efficiency) > 1e-9:
            warnings.append(
                "Provided useful process heat implies a thermal efficiency of "
                f"{implied_efficiency:.6g}; the declared thermal_efficiency of "
                f"{efficiency:.6g} was not used in the balance."
            )
    else:
        assumptions["thermal_efficiency"] = efficiency

    return _result(
        model_id="industrial.furnace.v1",
        name="Industrial furnace",
        input_energy=fuel,
        useful_energy=useful,
        input_exergy=fuel * fuel_factor,
        useful_exergy=useful * product_factor,
        recoverable_energy=exhaust,
        metrics={
            "process_heat_exergy_factor": product_factor,
            "exhaust_heat_exergy_factor": exhaust_factor,
            "recoverable_exhaust_exergy_mwh": exhaust * exhaust_factor,
            "unaccounted_energy_mwh": max(fuel - useful - exhaust, 0.0),
            "implied_thermal_efficiency": implied_efficiency,
        },
        assumptions=assumptions,
        sources=(DOE_PROCESS_HEATING_SOURCE,),
        warnings=warnings,
    )


def analyze_refrigeration(
    *,
    cooling_delivered_mwh: float,
    cold_temperature_c: float,
    ambient_temperature_c: float,
    cop: float,
) -> EngineeringModelResult:
    """Compare an actual refrigeration system with the Carnot cooling COP."""

    cooling = _nonnegative(cooling_delivered_mwh, "cooling_delivered_mwh")
    actual_cop = _positive(cop, "cop")
    cold_k = _positive(cold_temperature_c + 273.15, "cold_temperature")
    ambient_k = _positive(ambient_temperature_c + 273.15, "ambient_temperature")
    if ambient_k <= cold_k:
        raise ValueError("ambient_temperature_c must exceed cold_temperature_c")
    carnot_cop = cold_k / (ambient_k - cold_k)
    if actual_cop > carnot_cop + 1e-9:
        raise ValueError("cop cannot exceed the Carnot cooling COP")
    electricity = cooling / actual_cop
    product_factor = cooling_exergy_factor_c(cold_temperature_c, ambient_temperature_c)
    return _result(
        model_id="industrial.refrigeration.v1",
        name="Industrial refrigeration",
        input_energy=electricity,
        useful_energy=cooling,
        input_exergy=electricity,
        useful_exergy=cooling * product_factor,
        recoverable_energy=0.0,
        metrics={
            "cop": actual_cop,
            "carnot_cop": carnot_cop,
            "cooling_service_exergy_factor": product_factor,
            "electricity_mwh": electricity,
        },
        assumptions={
            "cold_temperature_c": cold_temperature_c,
            "ambient_temperature_c": ambient_temperature_c,
            "electricity_exergy_factor": 1.0,
        },
        sources=(),
    )


def analyze_compressed_air(
    *,
    electricity_mwh: float,
    free_air_volume_m3: float,
    delivery_pressure_bar_abs: float,
    end_use_pressure_bar_abs: float | None = None,
    ambient_pressure_bar_abs: float = 1.01325,
    leak_fraction: float = 0.0,
) -> EngineeringModelResult:
    """Screen compressed-air pressure exergy, leaks, and pressure mismatch."""

    electricity = _positive(electricity_mwh, "electricity_mwh")
    volume = _nonnegative(free_air_volume_m3, "free_air_volume_m3")
    ambient = _positive(ambient_pressure_bar_abs, "ambient_pressure_bar_abs")
    delivery = _positive(delivery_pressure_bar_abs, "delivery_pressure_bar_abs")
    end_use = (
        delivery
        if end_use_pressure_bar_abs is None
        else _positive(end_use_pressure_bar_abs, "end_use_pressure_bar_abs")
    )
    if delivery <= ambient:
        raise ValueError("delivery pressure must exceed ambient pressure")
    if not ambient < end_use <= delivery:
        raise ValueError(
            "end-use pressure must exceed ambient pressure and not exceed delivery pressure"
        )
    leakage = _fraction(leak_fraction, "leak_fraction")
    joules_per_bar_m3 = 100_000.0
    delivered_pressure_exergy = (
        ambient * volume * math.log(delivery / ambient) * joules_per_bar_m3 / 3.6e9
    )
    useful_pressure_exergy = (
        ambient
        * volume
        * (1.0 - leakage)
        * math.log(end_use / ambient)
        * joules_per_bar_m3
        / 3.6e9
    )
    if delivered_pressure_exergy > electricity + 1e-9:
        raise ValueError(
            "ideal pressure exergy exceeds electricity input; review free-air volume and reporting period"
        )
    wasted_pneumatic = max(delivered_pressure_exergy - useful_pressure_exergy, 0.0)
    return _result(
        model_id="industrial.compressed-air.v1",
        name="Compressed-air system",
        input_energy=electricity,
        useful_energy=useful_pressure_exergy,
        input_exergy=electricity,
        useful_exergy=useful_pressure_exergy,
        recoverable_energy=wasted_pneumatic,
        metrics={
            "ideal_delivery_pressure_exergy_mwh": delivered_pressure_exergy,
            "useful_pressure_exergy_mwh": useful_pressure_exergy,
            "pneumatic_exergy_lost_to_leaks_or_pressure_mismatch_mwh": wasted_pneumatic,
            "pressure_match_fraction": math.log(end_use / ambient)
            / math.log(delivery / ambient),
        },
        assumptions={
            "free_air_volume_m3": volume,
            "delivery_pressure_bar_abs": delivery,
            "end_use_pressure_bar_abs": end_use,
            "ambient_pressure_bar_abs": ambient,
            "leak_fraction": leakage,
            "compression_reference": "reversible isothermal pressure exergy",
        },
        sources=(DOE_COMPRESSED_AIR_SOURCE,),
        warnings=(
            "The pressure-exergy screen excludes compressor heat recovery, humidity, pressure drops, and transient storage.",
        ),
    )


@dataclass(frozen=True)
class WasteHeatSource:
    name: str
    available_heat_mwh: float
    supply_temperature_c: float
    minimum_outlet_temperature_c: float


@dataclass(frozen=True)
class HeatDemand:
    name: str
    required_heat_mwh: float
    supply_temperature_c: float
    return_temperature_c: float


@dataclass(frozen=True)
class WasteHeatMatch:
    source: str
    demand: str
    heat_recovered_mwh: float
    source_exergy_mwh: float
    useful_exergy_mwh: float
    quality_loss_mwh: float

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class WasteHeatMatchResult:
    matches: tuple[WasteHeatMatch, ...]
    total_heat_recovered_mwh: float
    total_source_exergy_mwh: float
    total_useful_exergy_mwh: float
    total_quality_loss_mwh: float
    unmatched_source_heat_mwh: Mapping[str, float]
    unmet_demand_heat_mwh: Mapping[str, float]
    minimum_approach_temperature_c: float
    reference_temperature_c: float
    sources: tuple[str, ...] = (DOE_PROCESS_HEATING_SOURCE,)
    warnings: tuple[str, ...] = (
        "Matches use a transparent greedy temperature-and-quality screen, not pinch optimization or heat-exchanger design.",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "model_id": "industrial.waste-heat-matching.v1",
            "matches": [item.to_dict() for item in self.matches],
            "totals": {
                "heat_recovered_mwh": self.total_heat_recovered_mwh,
                "source_exergy_mwh": self.total_source_exergy_mwh,
                "useful_exergy_mwh": self.total_useful_exergy_mwh,
                "quality_loss_mwh": self.total_quality_loss_mwh,
            },
            "unmatched_source_heat_mwh": dict(self.unmatched_source_heat_mwh),
            "unmet_demand_heat_mwh": dict(self.unmet_demand_heat_mwh),
            "minimum_approach_temperature_c": self.minimum_approach_temperature_c,
            "reference_temperature_c": self.reference_temperature_c,
            "sources": list(self.sources),
            "warnings": list(self.warnings),
        }

    def export_html(self, path: str, **options: Any) -> Any:
        from .reporting import export_html

        return export_html(self, path, **options)

    def export_pdf(self, path: str, **options: Any) -> Any:
        from .reporting import export_pdf

        return export_pdf(self, path, **options)

    def export_excel_compatible(self, directory: str, **options: Any) -> Any:
        from .reporting import export_excel_compatible_report

        return export_excel_compatible_report(self, directory, **options)

    def export_xlsx(self, path: str, **options: Any) -> Any:
        from .excel import export_xlsx_report

        return export_xlsx_report(self, path, **options)


def match_waste_heat(
    sources: Iterable[WasteHeatSource | Mapping[str, Any]],
    demands: Iterable[HeatDemand | Mapping[str, Any]],
    *,
    minimum_approach_temperature_c: float = 10.0,
    reference_temperature_c: float = 25.0,
) -> WasteHeatMatchResult:
    """Greedily match heat by temperature feasibility and exergy quality."""

    approach = _nonnegative(
        minimum_approach_temperature_c, "minimum_approach_temperature_c"
    )
    source_items = [
        item if isinstance(item, WasteHeatSource) else WasteHeatSource(**item)
        for item in sources
    ]
    demand_items = [
        item if isinstance(item, HeatDemand) else HeatDemand(**item) for item in demands
    ]
    if not source_items or not demand_items:
        raise ValueError("at least one waste-heat source and heat demand are required")
    remaining_sources: dict[str, float] = {}
    source_totals: dict[str, float] = {}
    source_temperatures: dict[str, float] = {}
    source_minimum_outlets: dict[str, float] = {}
    for item in source_items:
        if item.name in remaining_sources:
            raise ValueError(f"duplicate waste-heat source name {item.name!r}")
        heat = _nonnegative(item.available_heat_mwh, "available_heat_mwh")
        supply_temperature = _number(
            item.supply_temperature_c, "source supply_temperature_c"
        )
        minimum_outlet_temperature = _number(
            item.minimum_outlet_temperature_c,
            "source minimum_outlet_temperature_c",
        )
        if supply_temperature <= minimum_outlet_temperature:
            raise ValueError("source supply temperature must exceed minimum outlet")
        if minimum_outlet_temperature < reference_temperature_c:
            raise ValueError(
                "source minimum outlet temperature must not be below the reference temperature"
            )
        remaining_sources[item.name] = heat
        source_totals[item.name] = heat
        source_temperatures[item.name] = supply_temperature
        source_minimum_outlets[item.name] = minimum_outlet_temperature
    remaining_demands: dict[str, float] = {}
    demand_factors: dict[str, float] = {}
    for item in demand_items:
        if item.name in remaining_demands:
            raise ValueError(f"duplicate heat-demand name {item.name!r}")
        heat = _nonnegative(item.required_heat_mwh, "required_heat_mwh")
        if item.supply_temperature_c <= item.return_temperature_c:
            raise ValueError("demand supply temperature must exceed return temperature")
        remaining_demands[item.name] = heat
        demand_factors[item.name] = sensible_heat_exergy_factor_c(
            item.supply_temperature_c,
            item.return_temperature_c,
            reference_temperature_c,
        )

    matches: list[WasteHeatMatch] = []
    sorted_demands = sorted(
        demand_items, key=lambda item: item.supply_temperature_c, reverse=True
    )
    sorted_sources = sorted(
        source_items, key=lambda item: source_temperatures[item.name], reverse=True
    )
    for demand in sorted_demands:
        for source in sorted_sources:
            available = remaining_sources[source.name]
            needed = remaining_demands[demand.name]
            if available <= 0.0 or needed <= 0.0:
                continue
            current_source_temperature = source_temperatures[source.name]
            if current_source_temperature < demand.supply_temperature_c + approach:
                continue
            minimum_feasible_outlet = max(
                source_minimum_outlets[source.name],
                demand.return_temperature_c + approach,
            )
            if current_source_temperature <= minimum_feasible_outlet:
                continue
            heat_per_degree_c = source_totals[source.name] / (
                source_temperatures[source.name] - source_minimum_outlets[source.name]
            )
            if heat_per_degree_c <= 0.0:
                continue
            thermally_feasible_heat = heat_per_degree_c * (
                current_source_temperature - minimum_feasible_outlet
            )
            recovered = min(available, needed, thermally_feasible_heat)
            if recovered <= 0.0:
                continue
            new_source_temperature = current_source_temperature - (
                recovered / heat_per_degree_c
            )
            source_factor = sensible_heat_exergy_factor_c(
                current_source_temperature,
                new_source_temperature,
                reference_temperature_c,
            )
            demand_factor = demand_factors[demand.name]
            if source_factor + 1e-12 < demand_factor:
                continue
            source_exergy = recovered * source_factor
            useful_exergy = recovered * demand_factor
            matches.append(
                WasteHeatMatch(
                    source=source.name,
                    demand=demand.name,
                    heat_recovered_mwh=recovered,
                    source_exergy_mwh=source_exergy,
                    useful_exergy_mwh=useful_exergy,
                    quality_loss_mwh=max(source_exergy - useful_exergy, 0.0),
                )
            )
            remaining_sources[source.name] -= recovered
            source_temperatures[source.name] = new_source_temperature
            remaining_demands[demand.name] -= recovered

    return WasteHeatMatchResult(
        matches=tuple(matches),
        total_heat_recovered_mwh=sum(item.heat_recovered_mwh for item in matches),
        total_source_exergy_mwh=sum(item.source_exergy_mwh for item in matches),
        total_useful_exergy_mwh=sum(item.useful_exergy_mwh for item in matches),
        total_quality_loss_mwh=sum(item.quality_loss_mwh for item in matches),
        unmatched_source_heat_mwh=remaining_sources,
        unmet_demand_heat_mwh=remaining_demands,
        minimum_approach_temperature_c=approach,
        reference_temperature_c=reference_temperature_c,
    )
