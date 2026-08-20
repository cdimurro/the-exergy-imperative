"""Sourced public-health benefit screening for clean-energy interventions.

This module deliberately separates monetized, modeled public-health benefits
from the pollutant inventory and hazard context in :mod:`impacts`. It does not
predict site-specific exposure, diagnoses, or individual risk.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from importlib.resources import files
from typing import Any, Mapping

from .models import Estimate, FidelityTier, RefinementOpportunity
from .units import convert_energy

HEALTH_BENEFIT_SCHEMA_VERSION = "1.0"
HEALTH_BENEFIT_METHOD_ID = "epa-bpk-intervention-energy-v1"


def load_health_benefit_factors() -> dict[str, Any]:
    """Load the packaged EPA benefits-per-kWh factor table and provenance."""

    resource = files("exergy_imperative").joinpath(
        "data", "health_benefit_factors.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


_DATA = load_health_benefit_factors()


def _key(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _lookup(catalog: Mapping[str, Any], value: str, name: str) -> str:
    candidate = _key(value, name)
    for identifier, metadata in catalog.items():
        aliases = {
            _key(identifier, name),
            _key(str(metadata["label"]), name),
            *(_key(str(alias), name) for alias in metadata.get("aliases", ())),
        }
        if candidate in aliases:
            return identifier
    choices = ", ".join(str(item["label"]) for item in catalog.values())
    raise ValueError(f"unknown {name} {value!r}; choose from {choices}")


def _finite_nonnegative(value: float, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return number


def _analysis_year(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("analysis_year must be a finite integer")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("analysis_year must be a finite integer") from exc
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError("analysis_year must be a finite integer")
    return int(number)


@dataclass(frozen=True)
class HealthBenefitFactor:
    """One published or explicitly unavailable EPA regional BPK value."""

    region_id: str
    region: str
    project_type_id: str
    project_type: str
    low_cents_per_kwh: float | None
    high_cents_per_kwh: float | None
    data_version: str
    data_year: int
    currency_year: int
    discount_rate: float
    source_id: str

    @property
    def available(self) -> bool:
        return (
            self.low_cents_per_kwh is not None and self.high_cents_per_kwh is not None
        )

    @property
    def central_cents_per_kwh(self) -> float | None:
        if not self.available:
            return None
        assert self.low_cents_per_kwh is not None
        assert self.high_cents_per_kwh is not None
        return (self.low_cents_per_kwh + self.high_cents_per_kwh) / 2.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "region": self.region,
            "project_type_id": self.project_type_id,
            "project_type": self.project_type,
            "available": self.available,
            "low_cents_per_kwh": self.low_cents_per_kwh,
            "high_cents_per_kwh": self.high_cents_per_kwh,
            "unit": f"{self.currency_year} USD cents/kWh",
            "data_version": self.data_version,
            "data_year": self.data_year,
            "discount_rate": self.discount_rate,
            "source_id": self.source_id,
        }


def _factor(region_id: str, project_type_id: str) -> HealthBenefitFactor:
    values = _DATA["values"][region_id][project_type_id]
    return HealthBenefitFactor(
        region_id=region_id,
        region=str(_DATA["regions"][region_id]["label"]),
        project_type_id=project_type_id,
        project_type=str(_DATA["project_types"][project_type_id]["label"]),
        low_cents_per_kwh=None if values is None else float(values[0]),
        high_cents_per_kwh=None if values is None else float(values[1]),
        data_version=str(_DATA["data_version"]),
        data_year=int(_DATA["data_year"]),
        currency_year=int(_DATA["currency_year"]),
        discount_rate=float(_DATA["discount_rate"]),
        source_id=str(_DATA["source"]["id"]),
    )


def list_health_benefit_factors(
    *,
    region: str | None = None,
    project_type: str | None = None,
    include_unavailable: bool = True,
) -> tuple[HealthBenefitFactor, ...]:
    """List EPA BPK factors, optionally filtered by region or intervention."""

    region_ids = (
        (_lookup(_DATA["regions"], region, "region"),)
        if region is not None
        else tuple(_DATA["regions"])
    )
    project_ids = (
        (_lookup(_DATA["project_types"], project_type, "project_type"),)
        if project_type is not None
        else tuple(_DATA["project_types"])
    )
    items = tuple(
        _factor(region_id, project_id)
        for region_id in region_ids
        for project_id in project_ids
    )
    if include_unavailable:
        return items
    return tuple(item for item in items if item.available)


@dataclass(frozen=True)
class HealthBenefitResult:
    """Auditable screening estimate of monetized outdoor-air health benefits."""

    energy: Estimate
    normalized: bool
    region_id: str
    region: str
    project_type_id: str
    project_type: str
    benefit_rate: Estimate
    monetized_benefit: Estimate
    factor_origin: str
    data_version: str
    source_data_year: int
    analysis_year: int | None
    time_basis: str = "annual"
    tier: FidelityTier = FidelityTier.F1
    method_id: str = HEALTH_BENEFIT_METHOD_ID
    boundaries: Mapping[str, Any] = field(default_factory=dict)
    assumptions: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    refinements: tuple[RefinementOpportunity, ...] = ()
    source_catalog: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": HEALTH_BENEFIT_SCHEMA_VERSION,
            "tier": self.tier.value,
            "method_id": self.method_id,
            "data_version": self.data_version,
            "source_data_year": self.source_data_year,
            "analysis_year": self.analysis_year,
            "time_basis": self.time_basis,
            "energy": self.energy.to_dict(),
            "normalized": self.normalized,
            "region": {"id": self.region_id, "label": self.region},
            "project_type": {
                "id": self.project_type_id,
                "label": self.project_type,
            },
            "factor_origin": self.factor_origin,
            "benefit_rate": self.benefit_rate.to_dict(),
            "monetized_benefit": self.monetized_benefit.to_dict(),
            "boundaries": dict(self.boundaries),
            "assumptions": dict(self.assumptions),
            "warnings": list(self.warnings),
            "refinements": [item.to_dict() for item in self.refinements],
            "sources": list(self.source_catalog),
            "source_catalog": {
                name: dict(value) for name, value in self.source_catalog.items()
            },
        }


def estimate_health_benefits(
    region: str,
    project_type: str,
    energy: float | None = None,
    *,
    unit: str = "MWh",
    analysis_year: int | None = None,
    low_cents_per_kwh: float | None = None,
    high_cents_per_kwh: float | None = None,
) -> HealthBenefitResult:
    """Estimate monetized public-health benefits from an EE/RE/ES+ intervention.

    ``energy`` is the annual intervention quantity. With no ``energy``, the
    result is normalized to one intervention MWh per year. The packaged defaults
    are EPA's regional screening values. Supply both low and high rate overrides
    to run the same calculation with a different sourced or site-specific factor.
    """

    region_id = _lookup(_DATA["regions"], region, "region")
    project_type_id = _lookup(_DATA["project_types"], project_type, "project_type")
    published = _factor(region_id, project_type_id)
    override_supplied = low_cents_per_kwh is not None or high_cents_per_kwh is not None
    if override_supplied and (low_cents_per_kwh is None or high_cents_per_kwh is None):
        raise ValueError(
            "low_cents_per_kwh and high_cents_per_kwh must be supplied together"
        )
    if override_supplied:
        assert low_cents_per_kwh is not None
        assert high_cents_per_kwh is not None
        low_rate = _finite_nonnegative(low_cents_per_kwh, "low_cents_per_kwh")
        high_rate = _finite_nonnegative(high_cents_per_kwh, "high_cents_per_kwh")
        factor_origin = "user-provided"
    else:
        if not published.available:
            raise ValueError(
                f"EPA did not publish a {published.project_type} BPK value for "
                f"the {published.region} AVERT region; supply both explicit rate "
                "overrides or choose an available region/project combination"
            )
        assert published.low_cents_per_kwh is not None
        assert published.high_cents_per_kwh is not None
        low_rate = published.low_cents_per_kwh
        high_rate = published.high_cents_per_kwh
        factor_origin = "EPA-published"
    if high_rate < low_rate:
        raise ValueError(
            "high_cents_per_kwh must be greater than or equal to the low value"
        )

    normalized = energy is None
    if isinstance(energy, bool):
        raise ValueError("energy must be numeric")
    energy_mwh = 1.0 if normalized else convert_energy(energy, unit, "MWh")
    energy_mwh = _finite_nonnegative(energy_mwh, "energy")
    selected_year = _analysis_year(analysis_year)
    central_rate = (low_rate + high_rate) / 2.0
    multiplier = energy_mwh * 10.0
    low_benefit = low_rate * multiplier
    high_benefit = high_rate * multiplier
    central_benefit = central_rate * multiplier

    boundaries = dict(_DATA["boundary"])
    assumptions: dict[str, Any] = {
        "central_value": (
            "Arithmetic midpoint of the published or user-provided low/high "
            "range; it is not an additional EPA estimate."
        ),
        "factor_application": (
            "Benefit rate multiplied by intervention kWh; one cent per kWh "
            "equals 10 USD per MWh."
        ),
        "discount_rate": float(_DATA["discount_rate"]),
        "currency_year": int(_DATA["currency_year"]),
    }
    if normalized:
        assumptions["energy"] = (
            "Normalized per 1 annual intervention MWh because no energy quantity was supplied."
        )
    if override_supplied:
        assumptions["benefit_rate"] = (
            "User-provided low/high rate override; the EPA source remains listed "
            "only for method and boundary context."
        )

    warnings = [
        (
            "Screening-level monetized outdoor-air public-health benefit; not a "
            "site-specific exposure, incidence, diagnosis, clinical-risk, or "
            "causal-attribution result."
        ),
        (
            "Regional benefits include modeled effects outside the source AVERT "
            "region and are not suitable for locating neighborhood-level impacts."
        ),
    ]
    valid_years = tuple(int(item) for item in boundaries["valid_analysis_years"])
    if (
        selected_year is not None
        and not valid_years[0] <= selected_year <= valid_years[1]
    ):
        warnings.append(
            f"Analysis year {selected_year} is outside EPA's suggested "
            f"{valid_years[0]}-{valid_years[1]} use window for the 2023 values; "
            "use updated AVERT/COBRA modeling for decision support."
        )

    source = dict(_DATA["source"])
    source["data_year"] = int(_DATA["data_year"])
    source["currency_year"] = int(_DATA["currency_year"])
    source["discount_rate"] = float(_DATA["discount_rate"])
    source_catalog = {str(source["id"]): source}
    return HealthBenefitResult(
        energy=Estimate(energy_mwh, "MWh"),
        normalized=normalized,
        region_id=published.region_id,
        region=published.region,
        project_type_id=published.project_type_id,
        project_type=published.project_type,
        benefit_rate=Estimate(
            central_rate,
            f"{_DATA['currency_year']} USD cents/kWh",
            low=low_rate,
            high=high_rate,
            confidence="screening range",
        ),
        monetized_benefit=Estimate(
            central_benefit,
            f"{_DATA['currency_year']} USD/year",
            low=low_benefit,
            high=high_benefit,
            confidence="screening range",
        ),
        factor_origin=factor_origin,
        data_version=str(_DATA["data_version"]),
        source_data_year=int(_DATA["data_year"]),
        analysis_year=selected_year,
        boundaries=boundaries,
        assumptions=assumptions,
        warnings=tuple(warnings),
        refinements=(
            RefinementOpportunity(
                field="avert_cobra_scenario",
                priority="high",
                reason=(
                    "County-level emissions and health modeling is needed to "
                    "resolve local exposure and incidence."
                ),
                unlocks="Higher-fidelity AVERT/COBRA or comparable analysis.",
            ),
            RefinementOpportunity(
                field="current_grid_and_population_inputs",
                priority="medium",
                reason=(
                    "The published factors use a fixed 2023 electricity, emissions, "
                    "population, baseline-incidence, and valuation context."
                ),
                unlocks="Analysis-year-specific screening.",
            ),
        ),
        source_catalog=source_catalog,
    )
