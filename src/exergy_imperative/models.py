"""Public data models for progressive-fidelity exergy analysis."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class FidelityTier(str, Enum):
    """Evidence level used for a result."""

    F0 = "F0"
    F1 = "F1"
    F2 = "F2"
    F3 = "F3"
    F4 = "F4"


class ValueStatus(str, Enum):
    """Where a parameter value came from."""

    PROVIDED = "provided"
    MEASURED = "measured"
    DERIVED = "derived"
    SITE_PROFILE = "site_profile"
    DATASET = "dataset"
    PROFILE = "profile"
    PUBLISHED_ESTIMATE = "published_estimate"
    LOOKUP = "lookup"
    GLOBAL_DEFAULT = "global_default"
    MISSING = "missing"


@dataclass(frozen=True)
class Parameter:
    """A value together with evidence, range, and reproducibility metadata."""

    value: Any
    unit: str | None = None
    status: ValueStatus = ValueStatus.PROVIDED
    source_id: str | None = None
    source_version: str | None = None
    method_id: str | None = None
    low: float | None = None
    high: float | None = None
    confidence: str | None = None
    note: str | None = None
    evidence_kind: str | None = None
    statistic: str | None = None
    range_basis: str | None = None
    applicability: Mapping[str, Any] | None = None
    estimate_variant: str | None = None
    selection_basis: str | None = None
    selection_context: Mapping[str, Any] | None = None
    available_context: tuple[str, ...] | None = None

    @property
    def is_assumed(self) -> bool:
        return self.status in {
            ValueStatus.SITE_PROFILE,
            ValueStatus.PROFILE,
            ValueStatus.PUBLISHED_ESTIMATE,
            ValueStatus.LOOKUP,
            ValueStatus.GLOBAL_DEFAULT,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value.value if isinstance(value, Enum) else value
            for key, value in self.__dict__.items()
            if value is not None
        }


@dataclass(frozen=True)
class Estimate:
    """A central estimate with an optional screening interval."""

    value: float
    unit: str
    low: float | None = None
    high: float | None = None
    confidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"value": self.value, "unit": self.unit}
        if self.low is not None:
            result["low"] = self.low
        if self.high is not None:
            result["high"] = self.high
        if self.confidence is not None:
            result["confidence"] = self.confidence
        return result

    def formatted(self, digits: int = 3) -> str:
        center = f"{self.value:.{digits}g} {self.unit}"
        if self.low is None or self.high is None or self.low == self.high:
            return center
        return (
            f"{center} (screening range {self.low:.{digits}g}-{self.high:.{digits}g})"
        )


@dataclass(frozen=True)
class Environment:
    """Reference environment used to define the thermodynamic dead state."""

    temperature_c: float = 25.0
    pressure_kpa: float = 101.325
    composition_model: str = "standard-atmosphere"
    source_id: str = "reference.standard_25c.v1"

    def __post_init__(self) -> None:
        try:
            temperature = float(self.temperature_c)
            pressure = float(self.pressure_kpa)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                "environment temperature and pressure must be numeric"
            ) from exc
        if not math.isfinite(temperature) or temperature <= -273.15:
            raise ValueError(
                "environment temperature must be finite and greater than absolute zero"
            )
        if not math.isfinite(pressure) or pressure <= 0.0:
            raise ValueError(
                "environment pressure must be finite and greater than zero"
            )
        if (
            not isinstance(self.composition_model, str)
            or not self.composition_model.strip()
        ):
            raise ValueError("environment composition_model must be a non-empty string")
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise ValueError("environment source_id must be a non-empty string")

    @property
    def temperature_k(self) -> float:
        return self.temperature_c + 273.15

    @classmethod
    def reporting_20c(cls) -> "Environment":
        return cls(
            temperature_c=20.0,
            pressure_kpa=101.325,
            source_id="reference.reporting_20c.v1",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "temperature_c": self.temperature_c,
            "pressure_kpa": self.pressure_kpa,
            "composition_model": self.composition_model,
            "source_id": self.source_id,
        }


@dataclass(frozen=True)
class RefinementOpportunity:
    """One optional measurement or input that would improve an estimate."""

    field: str
    priority: str
    reason: str
    unlocks: str | None = None

    def to_dict(self) -> dict[str, str]:
        result = {
            "field": self.field,
            "priority": self.priority,
            "reason": self.reason,
        }
        if self.unlocks:
            result["unlocks"] = self.unlocks
        return result


@dataclass
class AssessmentResult:
    """An auditable screening or engineering assessment."""

    subject: str
    tier: FidelityTier
    method_id: str
    registry_version: str
    parameters: dict[str, Parameter]
    carrier_id: str | None = None
    exergy_factor: Estimate | None = None
    input_energy: Estimate | None = None
    input_exergy: Estimate | None = None
    useful_energy: Estimate | None = None
    useful_exergy: Estimate | None = None
    exergy_destroyed_or_lost: Estimate | None = None
    exergetic_efficiency: Estimate | None = None
    normalized: bool = False
    warnings: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    refinements: list[RefinementOpportunity] = field(default_factory=list)
    source_catalog: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    request: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def assumptions(self) -> dict[str, Parameter]:
        return {name: item for name, item in self.parameters.items() if item.is_assumed}

    @property
    def provided(self) -> dict[str, Parameter]:
        return {
            name: item
            for name, item in self.parameters.items()
            if item.status in {ValueStatus.PROVIDED, ValueStatus.MEASURED}
        }

    def refinement_opportunities(self) -> tuple[RefinementOpportunity, ...]:
        return tuple(self.refinements)

    def refine(self, **overrides: Any) -> "AssessmentResult":
        """Re-run this assessment with explicit parameters replacing defaults."""

        from .assessment import assess

        request = dict(self.request)
        normalized_override = request.pop("_normalized_override", None)
        if "energy" in overrides:
            normalized_override = None
        request.update(overrides)
        result = assess(**request)
        if normalized_override is not None:
            result.normalized = bool(normalized_override)
            result.request["_normalized_override"] = bool(normalized_override)
        return result

    def impacts(self, **options: Any) -> Any:
        """Attach climate and air-pollutant screening to this assessment."""

        from .impacts import assess_impacts

        return assess_impacts(assessment=self, **options)

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

    def to_dict(self) -> dict[str, Any]:
        estimates = {
            name: value.to_dict()
            for name, value in {
                "exergy_factor": self.exergy_factor,
                "input_energy": self.input_energy,
                "input_exergy": self.input_exergy,
                "useful_energy": self.useful_energy,
                "useful_exergy": self.useful_exergy,
                "exergy_destroyed_or_lost": self.exergy_destroyed_or_lost,
                "exergetic_efficiency": self.exergetic_efficiency,
            }.items()
            if value is not None
        }
        return {
            "schema_version": "1.0",
            "subject": self.subject,
            "tier": self.tier.value,
            "method_id": self.method_id,
            "registry_version": self.registry_version,
            "carrier_id": self.carrier_id,
            "normalized": self.normalized,
            "parameters": {
                name: value.to_dict() for name, value in self.parameters.items()
            },
            "results": estimates,
            "warnings": list(self.warnings),
            "missing": list(self.missing),
            "refinements": [item.to_dict() for item in self.refinements],
            "source_catalog": {
                name: dict(value) for name, value in self.source_catalog.items()
            },
        }

    def summary(self) -> str:
        lines = [
            self.subject,
            f"Fidelity: {self.tier.value}",
            f"Method: {self.method_id}",
        ]
        if self.normalized:
            basis = "Basis: normalized per 1 MWh of input"
            if self.request.get("energy") is None:
                basis += " because no energy quantity was supplied"
            lines.append(basis)
        labels = (
            ("Exergy factor", self.exergy_factor),
            ("Input exergy", self.input_exergy),
            ("Useful exergy", self.useful_exergy),
            ("Exergy destroyed or lost", self.exergy_destroyed_or_lost),
            ("Exergetic efficiency", self.exergetic_efficiency),
        )
        for label, estimate in labels:
            if estimate is not None:
                lines.append(f"{label}: {estimate.formatted()}")
        if self.assumptions:
            lines.append("Assumed/defaulted inputs:")
            for name, item in self.assumptions.items():
                display = f"{item.value} {item.unit or ''}".strip()
                if item.low is not None and item.high is not None:
                    display += f" [{item.low}-{item.high}]"
                lines.append(
                    f"  - {name}: {display} ({item.source_id or item.status.value})"
                )
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"  - {message}" for message in self.warnings)
        if self.refinements:
            lines.append("Most valuable refinements:")
            lines.extend(
                f"  - {item.field} ({item.priority}): {item.reason}"
                for item in self.refinements[:3]
            )
        return "\n".join(lines)


@dataclass(frozen=True)
class ExergyStream:
    """A stream for a process-level exergy balance."""

    name: str
    exergy: float
    unit: str = "MWh_ex"
    energy: float | None = None
    exergy_factor: float | None = None
    tier: FidelityTier = FidelityTier.F2
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "exergy": self.exergy,
            "unit": self.unit,
            "tier": self.tier.value,
        }
        if self.energy is not None:
            result["energy"] = self.energy
        if self.exergy_factor is not None:
            result["exergy_factor"] = self.exergy_factor
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result


@dataclass(frozen=True)
class BalanceResult:
    """Closed or diagnosed exergy balance around a declared boundary."""

    name: str
    input_exergy: float
    product_exergy: float
    loss_exergy: float
    destruction_exergy: float
    residual: float
    exergetic_efficiency: float | None
    unit: str
    inferred_destruction: bool
    warnings: tuple[str, ...] = ()
    hotspots: tuple[tuple[str, float], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "name": self.name,
            "unit": self.unit,
            "input_exergy": self.input_exergy,
            "product_exergy": self.product_exergy,
            "loss_exergy": self.loss_exergy,
            "destruction_exergy": self.destruction_exergy,
            "residual": self.residual,
            "exergetic_efficiency": self.exergetic_efficiency,
            "inferred_destruction": self.inferred_destruction,
            "warnings": list(self.warnings),
            "hotspots": [
                {"name": label, "exergy": value, "unit": self.unit}
                for label, value in self.hotspots
            ],
        }
