"""Scenario comparison across exergy, climate, health, and economics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from .models import AssessmentResult
from .processes import ProcessAssessment


@dataclass(frozen=True)
class ScenarioMetrics:
    input_energy_mwh: float | None = None
    input_exergy_mwh: float | None = None
    useful_exergy_mwh: float | None = None
    exergy_destruction_mwh: float | None = None
    exergetic_efficiency: float | None = None
    co2e20_kg: float | None = None
    co2e100_kg: float | None = None
    health_externality_cost: float | None = None
    npv: float | None = None
    normalized: bool | None = None
    currency: str | None = None
    health_cost_currency: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in self.__dict__.items() if value is not None}


@dataclass(frozen=True)
class ScenarioComparison:
    baseline: str
    scenarios: Mapping[str, ScenarioMetrics]
    deltas_from_baseline: Mapping[str, Mapping[str, float | None]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "baseline": self.baseline,
            "scenarios": {
                name: metrics.to_dict() for name, metrics in self.scenarios.items()
            },
            "deltas_from_baseline": {
                name: dict(values) for name, values in self.deltas_from_baseline.items()
            },
        }


def _assessment_metrics(result: AssessmentResult) -> ScenarioMetrics:
    return ScenarioMetrics(
        input_energy_mwh=result.input_energy.value if result.input_energy else None,
        input_exergy_mwh=result.input_exergy.value if result.input_exergy else None,
        useful_exergy_mwh=result.useful_exergy.value if result.useful_exergy else None,
        exergy_destruction_mwh=(
            result.exergy_destroyed_or_lost.value
            if result.exergy_destroyed_or_lost
            else None
        ),
        exergetic_efficiency=(
            result.exergetic_efficiency.value if result.exergetic_efficiency else None
        ),
        normalized=result.normalized,
    )


def scenario_metrics(value: Any) -> ScenarioMetrics:
    if isinstance(value, ProcessAssessment):
        base = _assessment_metrics(value.assessment)
        metrics = dict(base.__dict__)
        metrics.update(
            co2e20_kg=value.environmental.co2e20_kg,
            co2e100_kg=value.environmental.co2e100_kg,
            health_externality_cost=value.environmental.health_externality_cost,
            npv=value.economics.npv if value.economics else None,
            currency=value.economics.currency if value.economics else None,
            health_cost_currency=value.environmental.health_externality_currency,
        )
        return ScenarioMetrics(**metrics)
    if isinstance(value, AssessmentResult):
        return _assessment_metrics(value)
    if isinstance(value, ScenarioMetrics):
        return scenario_metrics(value.to_dict())
    if isinstance(value, Mapping):
        fields = ScenarioMetrics.__dataclass_fields__
        unknown = sorted(str(name) for name in value if name not in fields)
        if unknown:
            raise ValueError("unknown scenario metric fields: " + ", ".join(unknown))
        converted: dict[str, Any] = {}
        for name, item in value.items():
            if name not in fields or item is None:
                continue
            if name == "normalized":
                if not isinstance(item, bool):
                    raise TypeError("normalized scenario metadata must be boolean")
                converted[name] = item
            elif name in {"currency", "health_cost_currency"}:
                converted[name] = str(item)
            else:
                number = float(item)
                if not math.isfinite(number):
                    raise ValueError(f"scenario metric {name!r} must be finite")
                converted[name] = number
        return ScenarioMetrics(**converted)
    raise TypeError(
        "scenario values must be ProcessAssessment, AssessmentResult, ScenarioMetrics, or mappings"
    )


def _validate_compatible_metadata(
    metrics: Mapping[str, ScenarioMetrics], *, monetary: bool = True
) -> None:
    bases = {
        item.normalized for item in metrics.values() if item.normalized is not None
    }
    if bases and any(item.normalized is None for item in metrics.values()):
        raise ValueError(
            "cannot compare scenarios with known and unknown normalization bases; "
            "set normalized metadata explicitly"
        )
    if len(bases) > 1:
        raise ValueError(
            "cannot compare normalized per-MWh and absolute reporting-period scenarios"
        )

    if not monetary:
        return

    npv_metrics = tuple(item for item in metrics.values() if item.npv is not None)
    currencies = {
        item.currency.strip().upper()
        for item in npv_metrics
        if item.currency is not None
    }
    if len(currencies) > 1 or (
        currencies and any(item.currency is None for item in npv_metrics)
    ):
        raise ValueError("cannot compare NPV values expressed in different currencies")

    health_metrics = tuple(
        item for item in metrics.values() if item.health_externality_cost is not None
    )
    health_valuation_states = {
        item.health_cost_currency is not None for item in health_metrics
    }
    if len(health_valuation_states) > 1:
        raise ValueError("cannot compare valued and unvalued health externality costs")
    health_currencies = {
        item.health_cost_currency.strip().upper()
        for item in health_metrics
        if item.health_cost_currency is not None
    }
    if len(health_currencies) > 1 or (
        health_currencies
        and any(item.health_cost_currency is None for item in health_metrics)
    ):
        raise ValueError(
            "cannot compare health externality costs expressed in different currencies"
        )


def compare_scenarios(
    scenarios: Mapping[str, Any],
    *,
    baseline: str | None = None,
) -> ScenarioComparison:
    if not scenarios:
        raise ValueError("at least one scenario is required")
    converted = {name: scenario_metrics(value) for name, value in scenarios.items()}
    _validate_compatible_metadata(converted)
    baseline_name = baseline or next(iter(converted))
    if baseline_name not in converted:
        raise KeyError(f"baseline {baseline_name!r} is not a supplied scenario")
    reference = converted[baseline_name]
    deltas: dict[str, dict[str, float | None]] = {}
    for name, metrics in converted.items():
        values: dict[str, float | None] = {}
        for field_name in ScenarioMetrics.__dataclass_fields__:
            if field_name in {"normalized", "currency", "health_cost_currency"}:
                continue
            current = getattr(metrics, field_name)
            base = getattr(reference, field_name)
            values[field_name] = (
                current - base if current is not None and base is not None else None
            )
        deltas[name] = values
    return ScenarioComparison(baseline_name, converted, deltas)


def avoided_exergy_destruction(
    baseline: AssessmentResult | ProcessAssessment,
    alternative: AssessmentResult | ProcessAssessment,
) -> float | None:
    metrics = {
        "baseline": scenario_metrics(baseline),
        "alternative": scenario_metrics(alternative),
    }
    _validate_compatible_metadata(metrics, monetary=False)
    base = metrics["baseline"].exergy_destruction_mwh
    improved = metrics["alternative"].exergy_destruction_mwh
    if base is None or improved is None:
        return None
    return base - improved
