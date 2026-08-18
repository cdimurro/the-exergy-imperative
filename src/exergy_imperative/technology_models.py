"""Declarative, extensible technology-model contracts.

The built-in assessment engine uses a deliberately small relation: useful
energy equals input energy multiplied by an explicitly supplied performance
parameter.  Model specifications name that parameter, constrain its range, and
document the physical boundary.  More detailed multi-stream physics belongs in
the connected-system and material-balance APIs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from difflib import get_close_matches
from typing import Any, Iterable, Mapping

from .registry import normalize_id
from .units import convert_energy, exergy_unit_for

TECHNOLOGY_MODEL_CONTRACT_VERSION = "1.0"
TECHNOLOGY_MODEL_RELATION = "input-times-performance"


def _text(value: Any, name: str) -> str:
    result = str(value).strip()
    if not result:
        raise ValueError(f"{name} must not be empty")
    return result


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


@dataclass(frozen=True)
class TechnologyModelSpec:
    """A transparent single-input/single-product model definition."""

    id: str
    label: str
    performance_parameter: str
    description: str
    maximum_performance: float | None = None
    aliases: tuple[str, ...] = ()
    relation: str = TECHNOLOGY_MODEL_RELATION

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TechnologyModelSpec":
        allowed = {
            "id",
            "label",
            "performance_parameter",
            "description",
            "maximum_performance",
            "aliases",
            "relation",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError("unknown technology-model fields: " + ", ".join(unknown))
        model_id = normalize_id(_text(payload.get("id"), "technology-model id"))
        parameter = normalize_id(
            _text(
                payload.get("performance_parameter"),
                f"technology-model {model_id!r} performance_parameter",
            )
        ).replace("-", "_")
        relation = str(payload.get("relation", TECHNOLOGY_MODEL_RELATION))
        if relation != TECHNOLOGY_MODEL_RELATION:
            raise ValueError(
                f"technology-model {model_id!r} relation must be "
                f"{TECHNOLOGY_MODEL_RELATION!r}"
            )
        maximum = payload.get("maximum_performance")
        if maximum is not None:
            maximum = _number(maximum, f"technology-model {model_id!r} maximum")
            if maximum <= 0.0:
                raise ValueError("maximum_performance must be positive")
        aliases_raw = payload.get("aliases", ())
        if not isinstance(aliases_raw, (list, tuple)):
            raise ValueError("technology-model aliases must be an array")
        aliases = tuple(_text(item, "technology-model alias") for item in aliases_raw)
        return cls(
            id=model_id,
            label=_text(payload.get("label", model_id), "technology-model label"),
            performance_parameter=parameter,
            description=_text(
                payload.get("description"),
                f"technology-model {model_id!r} description",
            ),
            maximum_performance=maximum,
            aliases=aliases,
            relation=relation,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "performance_parameter": self.performance_parameter,
            "description": self.description,
            "aliases": list(self.aliases),
            "relation": self.relation,
        }
        if self.maximum_performance is not None:
            result["maximum_performance"] = self.maximum_performance
        return result

    def validate_performance(self, value: Any) -> float:
        performance = _number(value, self.performance_parameter)
        if performance < 0.0:
            raise ValueError(f"{self.performance_parameter} must be nonnegative")
        if (
            self.maximum_performance is not None
            and performance > self.maximum_performance
        ):
            raise ValueError(
                f"{self.performance_parameter} must not exceed "
                f"{self.maximum_performance:g} for model {self.id!r}"
            )
        return performance


@dataclass(frozen=True)
class TechnologyModelResult:
    model_id: str
    performance_parameter: str
    performance: float
    input_energy: float
    useful_energy: float
    input_exergy: float
    useful_exergy: float
    destroyed_or_unallocated_exergy: float
    exergetic_efficiency: float | None
    unit: str
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TECHNOLOGY_MODEL_CONTRACT_VERSION,
            "model_id": self.model_id,
            "performance_parameter": self.performance_parameter,
            "performance": self.performance,
            "unit": self.unit,
            "exergy_unit": exergy_unit_for(self.unit),
            "input_energy": self.input_energy,
            "useful_energy": self.useful_energy,
            "input_exergy": self.input_exergy,
            "useful_exergy": self.useful_exergy,
            "destroyed_or_unallocated_exergy": self.destroyed_or_unallocated_exergy,
            "exergetic_efficiency": self.exergetic_efficiency,
            "warnings": list(self.warnings),
        }


class TechnologyModelRegistry:
    """Immutable-by-convention lookup for declarative technology models."""

    def __init__(self, models: Iterable[TechnologyModelSpec | Mapping[str, Any]]):
        self._models: dict[str, TechnologyModelSpec] = {}
        self._aliases: dict[str, str] = {}
        for raw in models:
            model = (
                raw
                if isinstance(raw, TechnologyModelSpec)
                else TechnologyModelSpec.from_dict(raw)
            )
            if model.id in self._models:
                raise ValueError(f"duplicate technology model {model.id!r}")
            self._models[model.id] = model
            for alias in (model.id, model.label, *model.aliases):
                key = normalize_id(alias)
                existing = self._aliases.get(key)
                if existing is not None and existing != model.id:
                    raise ValueError(
                        f"technology-model alias {alias!r} maps to both "
                        f"{existing!r} and {model.id!r}"
                    )
                self._aliases[key] = model.id

    def list(self) -> tuple[TechnologyModelSpec, ...]:
        return tuple(self._models.values())

    def get(self, value: str) -> TechnologyModelSpec:
        key = normalize_id(value)
        model_id = self._aliases.get(key)
        if model_id is None:
            choices = sorted(self._models)
            suggestions = get_close_matches(key, choices, n=3, cutoff=0.45)
            suffix = (
                f"; closest matches: {', '.join(suggestions)}" if suggestions else ""
            )
            raise KeyError(
                f"unknown technology model {value!r}; available models: "
                f"{', '.join(choices)}{suffix}"
            )
        return self._models[model_id]

    def with_models(
        self, models: Iterable[TechnologyModelSpec | Mapping[str, Any]]
    ) -> "TechnologyModelRegistry":
        replacements = {
            (
                item.id
                if isinstance(item, TechnologyModelSpec)
                else normalize_id(str(item["id"]))
            ): item
            for item in models
        }
        combined: list[TechnologyModelSpec | Mapping[str, Any]] = [
            item for item in self.list() if item.id not in replacements
        ]
        combined.extend(replacements.values())
        return TechnologyModelRegistry(combined)


_BUILTIN_MODEL_DATA = (
    ("converter", "Converter", "efficiency", 1.0),
    ("heat-pump", "Heat pump", "cop", None),
    ("chiller", "Chiller", "cop", None),
    ("compressor-pump", "Compressor or pump", "efficiency", 1.0),
    ("turbine-expander", "Turbine or expander", "efficiency", 1.0),
    ("electrolyzer", "Electrolyzer", "efficiency", 1.0),
    ("fuel-cell", "Fuel cell", "efficiency", 1.0),
    ("storage", "Energy storage", "efficiency", 1.0),
    ("heat-to-power", "Heat-to-power converter", "efficiency", 1.0),
    ("separation", "Separation system", "efficiency", 1.0),
)

DEFAULT_TECHNOLOGY_MODEL_REGISTRY = TechnologyModelRegistry(
    TechnologyModelSpec(
        id=model_id,
        label=label,
        performance_parameter=parameter,
        maximum_performance=maximum,
        description=(
            "Single-input screening relation with explicit boundary performance; "
            "multi-stream physics must be modeled as connected flows."
        ),
    )
    for model_id, label, parameter, maximum in _BUILTIN_MODEL_DATA
)

SUPPORTED_TECHNOLOGY_MODELS = tuple(
    item.id for item in DEFAULT_TECHNOLOGY_MODEL_REGISTRY.list()
)


def evaluate_technology_model(
    model: str,
    *,
    input_energy: float,
    performance: float,
    input_exergy_factor: float,
    output_exergy_factor: float,
    unit: str = "MWh",
    registry: TechnologyModelRegistry | None = None,
) -> TechnologyModelResult:
    """Evaluate a registered single-input screening model.

    This function does not infer performance, state, composition, or site data.
    """

    model_registry = registry or DEFAULT_TECHNOLOGY_MODEL_REGISTRY
    spec = model_registry.get(model)
    input_value = convert_energy(_number(input_energy, "input_energy"), unit, unit)
    if input_value < 0.0:
        raise ValueError("input_energy must be nonnegative")
    performance_value = spec.validate_performance(performance)
    input_factor = _number(input_exergy_factor, "input_exergy_factor")
    output_factor = _number(output_exergy_factor, "output_exergy_factor")
    if input_factor < 0.0 or output_factor < 0.0:
        raise ValueError("exergy factors must be nonnegative")
    useful_energy = input_value * performance_value
    input_exergy = input_value * input_factor
    useful_exergy = useful_energy * output_factor
    remainder = input_exergy - useful_exergy
    if remainder < -1e-12:
        raise ValueError(
            "product exergy exceeds input exergy; check the performance, factors, "
            "and selected boundary"
        )
    warnings = (
        "Residual exergy combines destruction and unallocated losses; use explicit "
        "connected flows to separate them.",
    )
    return TechnologyModelResult(
        model_id=spec.id,
        performance_parameter=spec.performance_parameter,
        performance=performance_value,
        input_energy=input_value,
        useful_energy=useful_energy,
        input_exergy=input_exergy,
        useful_exergy=useful_exergy,
        destroyed_or_unallocated_exergy=max(remainder, 0.0),
        exergetic_efficiency=(
            useful_exergy / input_exergy if input_exergy > 0.0 else None
        ),
        unit=unit,
        warnings=warnings,
    )
