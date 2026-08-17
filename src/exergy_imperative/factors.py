"""Versioned climate, combustion, grid, and health-screening factors."""

from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping


class FactorNotFoundError(KeyError):
    """Raised when no bundled or custom factor matches a request."""


def normalize_factor_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def _finite_nonnegative(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return number


def _finite_integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite integer")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite integer") from exc
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError(f"{name} must be a finite integer")
    return int(number)


def _factor_range(
    raw: Mapping[str, Any], name: str, source_id: str | None = None
) -> FactorRange:
    value = _finite_nonnegative(raw["value"], f"{name} value")
    low = (
        _finite_nonnegative(raw["low"], f"{name} low")
        if raw.get("low") is not None
        else None
    )
    high = (
        _finite_nonnegative(raw["high"], f"{name} high")
        if raw.get("high") is not None
        else None
    )
    if low is not None and low > value or high is not None and value > high:
        raise ValueError(f"{name} range must satisfy low <= value <= high")
    return FactorRange(value, "kg/MWh", low, high, source_id)


@dataclass(frozen=True)
class WarmingPotential:
    gas: str
    name: str
    gwp20: float
    gwp100: float
    source_id: str
    assessment: str = "AR6"

    def for_horizon(self, horizon: int) -> float:
        if horizon == 20:
            return self.gwp20
        if horizon == 100:
            return self.gwp100
        raise ValueError("GWP horizon must be 20 or 100 years")

    def to_dict(self) -> dict[str, Any]:
        return {
            "gas": self.gas,
            "name": self.name,
            "assessment": self.assessment,
            "gwp20": self.gwp20,
            "gwp100": self.gwp100,
            "source_id": self.source_id,
        }


@dataclass(frozen=True)
class FactorRange:
    value: float
    unit: str
    low: float | None = None
    high: float | None = None
    source_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"value": self.value, "unit": self.unit}
        if self.low is not None:
            result["low"] = self.low
        if self.high is not None:
            result["high"] = self.high
        if self.source_id:
            result["source_id"] = self.source_id
        return result


@dataclass(frozen=True)
class FuelEmissionFactor:
    id: str
    label: str
    basis: str
    gases_kg_per_mwh: Mapping[str, float]
    pollutants_kg_per_mwh: Mapping[str, FactorRange]
    source_id: str
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "basis": self.basis,
            "gases_kg_per_mwh": dict(self.gases_kg_per_mwh),
            "pollutants_kg_per_mwh": {
                key: value.to_dict()
                for key, value in self.pollutants_kg_per_mwh.items()
            },
            "source_id": self.source_id,
        }
        if self.note:
            result["note"] = self.note
        return result


@dataclass(frozen=True)
class GridEmissionFactor:
    iso3: str
    country: str
    year: int
    kg_co2e_per_mwh: float
    data_version: str
    source_ids: tuple[str, ...] = ()
    requested_year: int | None = None

    @property
    def is_fallback_year(self) -> bool:
        return self.requested_year is not None and self.year != self.requested_year

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "iso3": self.iso3,
            "country": self.country,
            "year": self.year,
            "kg_co2e_per_mwh": self.kg_co2e_per_mwh,
            "unit": "kg CO2e/MWh",
            "data_version": self.data_version,
            "source_ids": list(self.source_ids),
        }
        if self.requested_year is not None:
            result["requested_year"] = self.requested_year
        return result


@dataclass(frozen=True)
class PollutantHealthProfile:
    pollutant: str
    name: str
    category: str
    health_effects: tuple[str, ...]
    sensitive_groups: tuple[str, ...]
    secondary_effects: tuple[str, ...]
    source_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pollutant": self.pollutant,
            "name": self.name,
            "category": self.category,
            "health_effects": list(self.health_effects),
            "sensitive_groups": list(self.sensitive_groups),
            "secondary_effects": list(self.secondary_effects),
            "source_id": self.source_id,
            "screening_only": True,
        }


class ImpactFactorLibrary:
    """Lookup interface for bundled factors and custom overlays."""

    def __init__(
        self,
        impact_payload: Mapping[str, Any],
        grid_payload: Mapping[str, Any],
    ):
        self.impact_payload = copy.deepcopy(dict(impact_payload))
        self.grid_payload = copy.deepcopy(dict(grid_payload))
        self.data_version = (
            f"{impact_payload.get('data_version', 'unknown')}+"
            f"{grid_payload.get('data_version', 'unknown')}"
        )
        self.sources = {
            **dict(impact_payload.get("sources", {})),
            **dict(grid_payload.get("sources", {})),
        }
        self._gwp: dict[str, WarmingPotential] = {}
        self._fuel: dict[str, FuelEmissionFactor] = {}
        self._health: dict[str, PollutantHealthProfile] = {}
        self._grid: dict[str, list[GridEmissionFactor]] = {}
        self._index_impact_factors()
        self._index_grid_factors()

    def _alias(self, index: dict[str, Any], alias: str, value: Any) -> None:
        key = normalize_factor_id(alias)
        existing = index.get(key)
        if existing is not None and existing != value:
            raise ValueError(f"factor alias {alias!r} is ambiguous")
        index[key] = value

    def _index_impact_factors(self) -> None:
        for assessment, spec in self.impact_payload.get("gwp_sets", {}).items():
            source_id = str(spec.get("source_id", "unspecified"))
            for gas, raw in spec.get("gases", {}).items():
                factor = WarmingPotential(
                    gas=str(gas),
                    name=str(raw.get("name", gas)),
                    gwp20=_finite_nonnegative(raw["gwp20"], f"{gas} GWP20"),
                    gwp100=_finite_nonnegative(raw["gwp100"], f"{gas} GWP100"),
                    source_id=str(raw.get("source_id", source_id)),
                    assessment=str(assessment),
                )
                for alias in (gas, factor.name, *raw.get("aliases", [])):
                    self._alias(self._gwp, str(alias), factor)

        for factor_id, raw in self.impact_payload.get("fuel_combustion", {}).items():
            pollutant_source = str(raw.get("pollutant_source_id", raw["source_id"]))
            pollutants = {
                str(name): _factor_range(spec, f"{factor_id} {name}", pollutant_source)
                for name, spec in raw.get("pollutants_kg_per_mwh", {}).items()
            }
            factor = FuelEmissionFactor(
                id=str(factor_id),
                label=str(raw.get("label", factor_id)),
                basis=str(raw.get("basis", "unspecified")),
                gases_kg_per_mwh={
                    str(name): _finite_nonnegative(value, f"{factor_id} {name} factor")
                    for name, value in raw.get("gases_kg_per_mwh", {}).items()
                },
                pollutants_kg_per_mwh=pollutants,
                source_id=str(raw["source_id"]),
                note=str(raw["note"]) if raw.get("note") else None,
            )
            for alias in (factor_id, factor.label, *raw.get("aliases", [])):
                self._alias(self._fuel, str(alias), factor)

        for pollutant, raw in self.impact_payload.get("pollutant_health", {}).items():
            profile = PollutantHealthProfile(
                pollutant=str(pollutant),
                name=str(raw.get("name", pollutant)),
                category=str(raw.get("category", "air pollutant")),
                health_effects=tuple(
                    str(item) for item in raw.get("health_effects", [])
                ),
                sensitive_groups=tuple(
                    str(item) for item in raw.get("sensitive_groups", [])
                ),
                secondary_effects=tuple(
                    str(item) for item in raw.get("secondary_effects", [])
                ),
                source_id=str(raw.get("source_id", "unspecified")),
            )
            for alias in (pollutant, profile.name, *raw.get("aliases", [])):
                self._alias(self._health, str(alias), profile)

    def _index_grid_factors(self) -> None:
        default_source_ids = tuple(
            str(item) for item in self.grid_payload.get("sources", {})
        )
        for raw in self.grid_payload.get("records", []):
            raw_source_ids = raw.get("source_ids")
            if raw_source_ids is None and raw.get("source_id"):
                raw_source_ids = [raw["source_id"]]
            grid_intensity = float(raw["kg_co2e_per_mwh"])
            if not math.isfinite(grid_intensity) or grid_intensity < 0.0:
                raise ValueError(
                    "grid kg_co2e_per_mwh values must be finite and nonnegative"
                )
            factor = GridEmissionFactor(
                iso3=str(raw["iso3"]),
                country=str(raw["country"]),
                year=_finite_integer(raw["year"], "grid year"),
                kg_co2e_per_mwh=grid_intensity,
                data_version=str(self.grid_payload.get("data_version", "unknown")),
                source_ids=tuple(
                    str(item) for item in (raw_source_ids or default_source_ids)
                ),
            )
            for alias in (factor.iso3, factor.country):
                key = normalize_factor_id(alias)
                records = self._grid.setdefault(key, [])
                if factor not in records:
                    records.append(factor)
        for records in self._grid.values():
            records.sort(key=lambda item: item.year)

    def warming_potential(self, gas: str) -> WarmingPotential:
        try:
            return self._gwp[normalize_factor_id(gas)]
        except KeyError as exc:
            raise FactorNotFoundError(f"unknown greenhouse gas {gas!r}") from exc

    def list_warming_potentials(self) -> tuple[WarmingPotential, ...]:
        return tuple({item.gas: item for item in self._gwp.values()}.values())

    def fuel_emissions(self, carrier: str) -> FuelEmissionFactor:
        try:
            return self._fuel[normalize_factor_id(carrier)]
        except KeyError as exc:
            raise FactorNotFoundError(
                f"no combustion emission factor for carrier {carrier!r}"
            ) from exc

    def list_fuel_emissions(self) -> tuple[FuelEmissionFactor, ...]:
        return tuple({item.id: item for item in self._fuel.values()}.values())

    def pollutant_health(self, pollutant: str) -> PollutantHealthProfile:
        try:
            return self._health[normalize_factor_id(pollutant)]
        except KeyError as exc:
            raise FactorNotFoundError(
                f"no health-screening profile for pollutant {pollutant!r}"
            ) from exc

    def list_pollutant_health(self) -> tuple[PollutantHealthProfile, ...]:
        return tuple({item.pollutant: item for item in self._health.values()}.values())

    def grid_emissions(
        self, location: str, year: int | None = None
    ) -> GridEmissionFactor:
        try:
            records = self._grid[normalize_factor_id(location)]
        except KeyError as exc:
            raise FactorNotFoundError(
                f"no bundled grid factor for location {location!r}"
            ) from exc
        if year is None:
            return records[-1]
        requested = _finite_integer(year, "grid lookup year")
        earlier = [item for item in records if item.year <= requested]
        selected = earlier[-1] if earlier else records[0]
        return GridEmissionFactor(
            iso3=selected.iso3,
            country=selected.country,
            year=selected.year,
            kg_co2e_per_mwh=selected.kg_co2e_per_mwh,
            data_version=selected.data_version,
            source_ids=selected.source_ids,
            requested_year=requested,
        )

    def grid_locations(self) -> tuple[tuple[str, str], ...]:
        locations = {
            (records[-1].iso3, records[-1].country) for records in self._grid.values()
        }
        return tuple(sorted(locations, key=lambda item: item[1]))

    def with_pack(self, path: str | Path) -> "ImpactFactorLibrary":
        """Overlay impact and/or grid sections from a user-owned JSON pack."""

        custom = json.loads(Path(path).read_text(encoding="utf-8"))
        impact = copy.deepcopy(self.impact_payload)
        grid = copy.deepcopy(self.grid_payload)
        suffix = str(custom.get("data_version", "custom"))
        for assessment, specification in custom.get("gwp_sets", {}).items():
            existing = impact.setdefault("gwp_sets", {}).get(assessment, {})
            existing_source = str(existing.get("source_id", "unspecified"))
            custom_source = str(specification.get("source_id", "unspecified"))
            existing_gases = {
                gas: {"source_id": existing_source, **raw}
                for gas, raw in existing.get("gases", {}).items()
            }
            custom_gases = {
                gas: {"source_id": custom_source, **raw}
                for gas, raw in specification.get("gases", {}).items()
            }
            merged = {
                **existing,
                **{
                    key: value
                    for key, value in specification.items()
                    if key not in {"gases", "source_id"}
                },
                "source_id": existing_source,
            }
            merged["gases"] = {
                **existing_gases,
                **custom_gases,
            }
            impact["gwp_sets"][assessment] = merged
        for section in ("fuel_combustion", "pollutant_health", "sources"):
            impact.setdefault(section, {}).update(custom.get(section, {}))
        if custom.get("grid_records"):
            bundled_source_ids = list(grid.get("sources", {}))
            replacements = {
                (str(item["iso3"]), _finite_integer(item["year"], "grid year")): {
                    **item,
                    "year": _finite_integer(item["year"], "grid year"),
                    "source_ids": item.get("source_ids", bundled_source_ids),
                }
                for item in grid.get("records", [])
            }
            custom_sources = dict(custom.get("sources", {}))
            if not custom_sources:
                custom_source_id = (
                    f"custom-grid-{normalize_factor_id(suffix) or 'pack'}"
                )
                custom_sources[custom_source_id] = {
                    "title": "User-owned custom grid factor pack"
                }
            grid.setdefault("sources", {}).update(custom_sources)
            for item in custom["grid_records"]:
                replacement = dict(item)
                year = _finite_integer(item["year"], "grid year")
                replacement["year"] = year
                if not replacement.get("source_ids") and not replacement.get(
                    "source_id"
                ):
                    replacement["source_ids"] = list(custom_sources)
                replacements[(str(item["iso3"]), year)] = replacement
            grid["records"] = list(replacements.values())
        impact["data_version"] = f"{impact.get('data_version', 'unknown')}+{suffix}"
        if custom.get("grid_records"):
            grid["data_version"] = f"{grid.get('data_version', 'unknown')}+{suffix}"
        return ImpactFactorLibrary(impact, grid)


def _load_payload(name: str) -> dict[str, Any]:
    resource = files("exergy_imperative").joinpath("data", name)
    return json.loads(resource.read_text(encoding="utf-8"))


DEFAULT_IMPACT_FACTORS = ImpactFactorLibrary(
    _load_payload("impact_factors.json"),
    _load_payload("global_electricity.json"),
)


def load_impact_factor_pack(path: str | Path) -> ImpactFactorLibrary:
    return DEFAULT_IMPACT_FACTORS.with_pack(path)
