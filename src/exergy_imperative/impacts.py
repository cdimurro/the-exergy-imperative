"""Climate and air-pollutant screening tied to energy and exergy assessments."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

from .economics import normalize_currency
from .factors import (
    DEFAULT_IMPACT_FACTORS,
    FactorNotFoundError,
    ImpactFactorLibrary,
    PollutantHealthProfile,
)
from .models import AssessmentResult, Estimate
from .registry import DEFAULT_REGISTRY
from .units import convert_energy, energy_basis


@dataclass(frozen=True)
class ClimateContribution:
    gas: str
    mass_kg: float
    gwp20: float | None
    gwp100: float | None
    co2e20_kg: float | None
    co2e100_kg: float | None
    source_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "gas": self.gas,
                "mass_kg": self.mass_kg,
                "gwp20": self.gwp20,
                "gwp100": self.gwp100,
                "co2e20_kg": self.co2e20_kg,
                "co2e100_kg": self.co2e100_kg,
                "source_id": self.source_id,
            }.items()
            if value is not None
        }


@dataclass(frozen=True)
class PollutantScreening:
    pollutant: str
    mass: Estimate
    profile: PollutantHealthProfile | None
    monetary_damage: float | None = None
    currency: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "pollutant": self.pollutant,
            "mass": self.mass.to_dict(),
        }
        if self.profile is not None:
            result["health_screening"] = self.profile.to_dict()
        if self.monetary_damage is not None:
            result["monetary_damage"] = {
                "value": self.monetary_damage,
                "currency": self.currency,
                "method": "user-supplied damage cost per kg",
            }
        return result


@dataclass(frozen=True)
class EnvironmentalResult:
    energy_mwh: float
    normalized: bool
    carrier: str | None
    geography: str | None
    factor_version: str
    gases_kg: Mapping[str, float]
    climate_contributions: tuple[ClimateContribution, ...]
    co2e20_kg: float
    co2e100_kg: float
    aggregate_grid_co2e_kg: float
    pollutants: tuple[PollutantScreening, ...]
    sources: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    assumptions: Mapping[str, Any] = field(default_factory=dict)
    source_catalog: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    @property
    def warming_horizon_gap_kg_co2e(self) -> float:
        return self.co2e20_kg - self.co2e100_kg

    @property
    def warming_horizon_ratio(self) -> float | None:
        if self.co2e100_kg == 0.0:
            return None
        return self.co2e20_kg / self.co2e100_kg

    @property
    def health_externality_cost(self) -> float:
        return sum(
            item.monetary_damage or 0.0
            for item in self.pollutants
            if item.monetary_damage is not None
        )

    @property
    def health_externality_currency(self) -> str | None:
        currencies = {
            item.currency
            for item in self.pollutants
            if item.monetary_damage is not None and item.currency is not None
        }
        if len(currencies) > 1:
            raise ValueError("pollutant monetary damages use multiple currencies")
        return next(iter(currencies), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "energy": {"value": self.energy_mwh, "unit": "MWh"},
            "normalized": self.normalized,
            "carrier": self.carrier,
            "geography": self.geography,
            "factor_version": self.factor_version,
            "gases_kg": dict(self.gases_kg),
            "climate": {
                "co2e20_kg": self.co2e20_kg,
                "co2e100_kg": self.co2e100_kg,
                "warming_horizon_gap_kg_co2e": self.warming_horizon_gap_kg_co2e,
                "warming_horizon_ratio": self.warming_horizon_ratio,
                "aggregate_grid_co2e_kg": self.aggregate_grid_co2e_kg,
                "contributions": [
                    item.to_dict() for item in self.climate_contributions
                ],
            },
            "pollutants": [item.to_dict() for item in self.pollutants],
            "health_externality_cost": self.health_externality_cost,
            "health_externality_currency": self.health_externality_currency,
            "assumptions": dict(self.assumptions),
            "sources": list(self.sources),
            "source_catalog": {
                name: dict(value) for name, value in self.source_catalog.items()
            },
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


def _finite_nonnegative(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return number


def _assessment_carrier(result: AssessmentResult) -> str | None:
    if result.carrier_id:
        return result.carrier_id
    carrier = result.request.get("carrier")
    if carrier:
        return str(carrier)
    technology = result.request.get("technology")
    if not technology:
        return None
    profile = DEFAULT_REGISTRY.find("technology", str(technology))
    if profile is None:
        return None
    value = profile.metadata.get("input_carrier")
    return str(value) if value else None


def assess_impacts(
    energy: float | None = None,
    *,
    unit: str = "MWh",
    assessment: AssessmentResult | None = None,
    carrier: str | None = None,
    country: str | None = None,
    year: int | None = None,
    grid_factor_kg_co2e_per_mwh: float | None = None,
    gases_kg: Mapping[str, float] | None = None,
    gas_factors_kg_per_mwh: Mapping[str, float] | None = None,
    pollutant_masses_kg: Mapping[str, float] | None = None,
    pollutant_factors_kg_per_mwh: Mapping[str, float] | None = None,
    refrigerant_leakage_kg: Mapping[str, float] | None = None,
    damage_costs_per_kg: Mapping[str, float] | None = None,
    currency: str = "USD",
    factor_library: ImpactFactorLibrary | None = None,
) -> EnvironmentalResult:
    """Estimate climate and pollutant inventories without requiring every input.

    The function uses a country grid factor for electricity and a declared-basis
    combustion factor for recognized fuels. Explicit user factors override the
    matching defaults. Pollutant health text is qualitative context, not an
    exposure or epidemiological risk assessment.
    """

    library = factor_library or DEFAULT_IMPACT_FACTORS
    warnings: list[str] = []
    assumptions: dict[str, Any] = {}
    sources: set[str] = set()

    normalized = energy is None
    if assessment is not None:
        if energy is None and assessment.input_energy is not None:
            normalized = assessment.normalized
            energy = assessment.input_energy.value
            unit = assessment.input_energy.unit
        carrier = carrier or _assessment_carrier(assessment)
        country = country or assessment.request.get("location")
    absolute_inventory_inputs = {
        "gases_kg": gases_kg,
        "pollutant_masses_kg": pollutant_masses_kg,
        "refrigerant_leakage_kg": refrigerant_leakage_kg,
    }
    if normalized:
        supplied_absolute_inputs = [
            name for name, values in absolute_inventory_inputs.items() if values
        ]
        if supplied_absolute_inputs:
            supplied = ", ".join(supplied_absolute_inputs)
            raise ValueError(
                f"absolute mass inputs ({supplied}) require an explicit energy "
                "quantity; use the corresponding per-MWh factor inputs for a "
                "normalized result"
            )
    energy_mwh = 1.0 if energy is None else convert_energy(energy, unit, "MWh")
    _finite_nonnegative(energy_mwh, "energy")
    has_explicit_emissions = any(
        (
            grid_factor_kg_co2e_per_mwh is not None,
            bool(gases_kg),
            bool(gas_factors_kg_per_mwh),
            bool(pollutant_masses_kg),
            bool(pollutant_factors_kg_per_mwh),
            bool(refrigerant_leakage_kg),
        )
    )
    if normalized:
        assumptions["energy"] = "normalized per 1 MWh because no quantity was supplied"

    gas_totals: dict[str, float] = {}
    pollutant_values: dict[str, tuple[float, float | None, float | None]] = {}
    aggregate_grid = 0.0
    carrier_profile = (
        DEFAULT_REGISTRY.find("carrier", str(carrier)) if carrier is not None else None
    )
    unit_basis = energy_basis(unit)
    if unit_basis is not None:
        assumptions["energy_basis"] = unit_basis
    factor_carrier = carrier_profile.id if carrier_profile is not None else carrier
    if unit_basis is not None and carrier_profile is not None:
        if carrier_profile.id in {"natural-gas-hhv", "methane-lhv"}:
            factor_carrier = "natural-gas-hhv" if unit_basis == "HHV" else "methane-lhv"
        elif "hydrogen" in carrier_profile.id:
            factor_carrier = f"hydrogen-{unit_basis.lower()}"
        else:
            carrier_basis = str(carrier_profile.metadata.get("basis", "")).upper()
            if carrier_basis in {"HHV", "LHV"} and carrier_basis != unit_basis:
                raise ValueError(
                    f"typed unit {unit!r} conflicts with the {carrier_basis} basis "
                    f"of {carrier_profile.label}"
                )
    is_electricity = factor_carrier == "electricity" or bool(
        carrier
        and carrier.strip().lower()
        in {
            "electricity",
            "electric",
            "grid electricity",
            "power",
        }
    )
    has_resolved_carrier_factor = is_electricity
    if carrier and not is_electricity:
        try:
            library.fuel_emissions(factor_carrier)
        except FactorNotFoundError:
            pass
        else:
            has_resolved_carrier_factor = True
    if (
        energy_mwh > 0.0
        and not has_explicit_emissions
        and not has_resolved_carrier_factor
    ):
        raise ValueError(
            "a positive energy quantity requires a carrier with a matched factor, "
            "a grid factor, or explicit emissions inventory or per-MWh factors"
        )
    if grid_factor_kg_co2e_per_mwh is not None:
        if carrier is None or not carrier.strip():
            is_electricity = True
            factor_carrier = "electricity"
            assumptions["carrier"] = (
                "electricity inferred from the provided grid emissions factor"
            )
            warnings.append(
                "No carrier was supplied; the explicit grid factor was applied to "
                "the full energy quantity as electricity."
            )
        elif not is_electricity:
            raise ValueError(
                "grid_factor_kg_co2e_per_mwh requires an electricity carrier or "
                "no carrier"
            )
    if is_electricity:
        if grid_factor_kg_co2e_per_mwh is None:
            location = country or "World"
            if country is None:
                assumptions["grid_location"] = "World"
                warnings.append(
                    "No electricity location was supplied; the latest bundled world grid factor was used."
                )
            try:
                grid = library.grid_emissions(location, year)
            except FactorNotFoundError as exc:
                raise ValueError(
                    f"no grid factor matched supplied location {location!r}; "
                    "use a supported country/ISO3 code or provide an explicit grid factor"
                ) from exc
            grid_factor = grid.kg_co2e_per_mwh
            assumptions["grid_factor"] = grid.to_dict()
            sources.update(grid.source_ids)
            if grid.is_fallback_year:
                warnings.append(
                    f"Requested grid year {grid.requested_year} was unavailable; {grid.year} was used."
                )
            country = grid.country
        else:
            grid_factor = _finite_nonnegative(
                grid_factor_kg_co2e_per_mwh, "grid_factor_kg_co2e_per_mwh"
            )
            assumptions["grid_factor"] = {
                "value": grid_factor,
                "unit": "kg CO2e/MWh",
                "status": "provided",
            }
        aggregate_grid = energy_mwh * grid_factor
        warnings.append(
            "The selected grid factor is aggregate lifecycle CO2e on its published horizon; "
            "it is carried unchanged into the 20-year total because gas-level composition is unavailable."
        )
    elif carrier:
        try:
            fuel = library.fuel_emissions(factor_carrier)
        except FactorNotFoundError:
            warnings.append(
                f"No bundled emission factor matched carrier {carrier!r}; only explicit emissions were counted."
            )
        else:
            fuel_basis = fuel.basis.strip().upper()
            if (
                unit_basis is not None
                and fuel_basis in {"HHV", "LHV"}
                and unit_basis != fuel_basis
            ):
                raise ValueError(
                    f"typed unit {unit!r} conflicts with the {fuel_basis} basis "
                    f"of emission factor {fuel.id!r}"
                )
            factor_carrier = fuel.id
            sources.add(fuel.source_id)
            assumptions["combustion_factor"] = fuel.to_dict()
            for gas, factor in fuel.gases_kg_per_mwh.items():
                gas_totals[gas] = energy_mwh * factor
            for pollutant, factor in fuel.pollutants_kg_per_mwh.items():
                pollutant_values[pollutant] = (
                    energy_mwh * factor.value,
                    energy_mwh * factor.low if factor.low is not None else None,
                    energy_mwh * factor.high if factor.high is not None else None,
                )
                if factor.source_id:
                    sources.add(factor.source_id)
            if fuel.note:
                warnings.append(fuel.note)

    def canonical_gas(name: str) -> str:
        try:
            return library.warming_potential(name).gas
        except FactorNotFoundError:
            return str(name)

    def canonical_pollutant(name: str) -> str:
        try:
            return library.pollutant_health(name).pollutant
        except FactorNotFoundError:
            return str(name)

    gas_factor_overrides: dict[str, float] = {}
    for gas, factor in (gas_factors_kg_per_mwh or {}).items():
        gas_name = canonical_gas(str(gas))
        factor_value = _finite_nonnegative(factor, f"gas factor {gas}")
        gas_totals[gas_name] = energy_mwh * factor_value
        gas_factor_overrides[gas_name] = factor_value
    if gas_factor_overrides:
        assumptions["gas_factor_overrides_kg_per_mwh"] = gas_factor_overrides
    for gas, mass in (gases_kg or {}).items():
        gas_name = canonical_gas(str(gas))
        gas_totals[gas_name] = gas_totals.get(gas_name, 0.0) + _finite_nonnegative(
            mass, f"gas mass {gas}"
        )
    for gas, mass in (refrigerant_leakage_kg or {}).items():
        gas_name = canonical_gas(str(gas))
        gas_totals[gas_name] = gas_totals.get(gas_name, 0.0) + _finite_nonnegative(
            mass, f"refrigerant leakage {gas}"
        )

    pollutant_factor_overrides: dict[str, float] = {}
    for pollutant, factor in (pollutant_factors_kg_per_mwh or {}).items():
        pollutant_name = canonical_pollutant(str(pollutant))
        factor_value = _finite_nonnegative(factor, f"pollutant factor {pollutant}")
        value = energy_mwh * factor_value
        pollutant_values[pollutant_name] = (value, value, value)
        pollutant_factor_overrides[pollutant_name] = factor_value
    if pollutant_factor_overrides:
        assumptions["pollutant_factor_overrides_kg_per_mwh"] = (
            pollutant_factor_overrides
        )
    for pollutant, mass in (pollutant_masses_kg or {}).items():
        pollutant_name = canonical_pollutant(str(pollutant))
        value = _finite_nonnegative(mass, f"pollutant mass {pollutant}")
        current = pollutant_values.get(pollutant_name)
        if current is None:
            pollutant_values[pollutant_name] = (value, value, value)
        else:
            pollutant_values[pollutant_name] = (
                current[0] + value,
                current[1] + value if current[1] is not None else None,
                current[2] + value if current[2] is not None else None,
            )

    contributions: list[ClimateContribution] = []
    co2e20 = aggregate_grid
    co2e100 = aggregate_grid
    canonical_gases: dict[str, float] = {}
    for gas, mass in gas_totals.items():
        try:
            gwp = library.warming_potential(gas)
        except FactorNotFoundError:
            warnings.append(
                f"No warming potential matched gas {gas!r}; its mass is reported but excluded from CO2e."
            )
            canonical_gases[gas] = canonical_gases.get(gas, 0.0) + mass
            contributions.append(
                ClimateContribution(gas, mass, None, None, None, None, None)
            )
            continue
        canonical_gases[gwp.gas] = canonical_gases.get(gwp.gas, 0.0) + mass
        item20 = mass * gwp.gwp20
        item100 = mass * gwp.gwp100
        co2e20 += item20
        co2e100 += item100
        sources.add(gwp.source_id)
        contributions.append(
            ClimateContribution(
                gwp.gas,
                mass,
                gwp.gwp20,
                gwp.gwp100,
                item20,
                item100,
                gwp.source_id,
            )
        )

    pollutant_results: list[PollutantScreening] = []
    damage_lookup = {
        canonical_pollutant(str(name)).strip().lower(): _finite_nonnegative(
            value, f"damage cost {name}"
        )
        for name, value in (damage_costs_per_kg or {}).items()
    }
    damage_currency = normalize_currency(currency) if damage_lookup else None
    for pollutant, (mass, low, high) in sorted(pollutant_values.items()):
        try:
            profile = library.pollutant_health(pollutant)
        except FactorNotFoundError:
            profile = None
            warnings.append(
                f"No qualitative health profile matched pollutant {pollutant!r}."
            )
        else:
            sources.add(profile.source_id)
        damage_factor = damage_lookup.get(pollutant.strip().lower())
        pollutant_results.append(
            PollutantScreening(
                pollutant=profile.pollutant if profile else pollutant,
                mass=Estimate(mass, "kg", low, high, "screening"),
                profile=profile,
                monetary_damage=mass * damage_factor
                if damage_factor is not None
                else None,
                currency=damage_currency if damage_factor is not None else None,
            )
        )
    if pollutant_results:
        warnings.append(
            "Pollutant health descriptions are qualitative context only. Estimating health outcomes requires dispersion, "
            "ambient concentration, exposure, population, and concentration-response data."
        )
    if damage_lookup:
        assumptions["damage_costs_per_kg"] = dict(damage_costs_per_kg or {})
        assumptions["damage_cost_currency"] = damage_currency
        warnings.append(
            "Pollutant monetary damages use user-supplied factors and are not bundled health valuations."
        )

    return EnvironmentalResult(
        energy_mwh=energy_mwh,
        normalized=normalized,
        carrier=factor_carrier,
        geography=str(country) if country else None,
        factor_version=library.data_version,
        gases_kg=canonical_gases,
        climate_contributions=tuple(contributions),
        co2e20_kg=co2e20,
        co2e100_kg=co2e100,
        aggregate_grid_co2e_kg=aggregate_grid,
        pollutants=tuple(pollutant_results),
        sources=tuple(sorted(sources)),
        warnings=tuple(dict.fromkeys(warnings)),
        assumptions=assumptions,
        source_catalog={
            source_id: dict(library.sources[source_id])
            for source_id in sorted(sources)
            if source_id in library.sources
        },
    )
