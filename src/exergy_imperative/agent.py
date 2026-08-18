"""Stable, machine-readable contracts for coding agents and tool servers."""

from __future__ import annotations

import inspect
import json
import math
from dataclasses import MISSING, dataclass, field, fields
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .assessment import MissingInputError, assess
from .balance import analyze_balance
from .datasets import list_datasets
from .economics import (
    TechnologyCostScenario,
    evaluate_economics,
    evaluate_technology_cost_scenario,
)
from .engineering import (
    analyze_compressed_air,
    analyze_furnace,
    analyze_heat_pump,
    analyze_refrigeration,
    analyze_steam_system,
    match_waste_heat,
)
from .ghg import assess_ghg_boundaries, assess_methane_project
from .impacts import assess_impacts
from .ingestion import MappingPlan, infer_mapping, normalize_records
from .materials import analyze_material_definition
from .models import ExergyStream
from .packs import (
    assess_intensity_with_pack,
    assess_performance_with_pack,
    assess_process_with_pack,
    assess_with_pack,
    bundled_technology_pack_info,
    load_technology_pack,
    validate_technology_pack,
)
from .processes import (
    ProcessTemplateNotFoundError,
    assess_process,
    get_process_template,
    list_process_templates,
)
from .registry import DEFAULT_REGISTRY, ProfileNotFoundError
from .schema import list_schemas, load_schema
from .systems import (
    SYSTEM_COMPONENT_KINDS,
    analyze_system_definition,
    analyze_system_timeseries_definition,
)
from .technology_models import (
    DEFAULT_TECHNOLOGY_MODEL_REGISTRY,
    evaluate_technology_model,
)
from .validation import run_bundled_validation_suite
from .weather import normalize_weather_performance

AGENT_CONTRACT_VERSION = "1.0"
LIBRARY_VERSION = "0.6.0"
RECIPE_MODES = ("execute", "dry-run", "validate-only")
REPORT_OUTPUTS = ("json", "html", "pdf", "xlsx", "excel_directory")


@dataclass(frozen=True)
class AgentNativeError(Exception):
    """An error that includes enough structure for an agent to recover."""

    code: str
    message: str
    suggested_fields: tuple[str, ...] = ()
    hint: str | None = None
    retryable: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.suggested_fields:
            payload["suggested_fields"] = list(self.suggested_fields)
        if self.hint:
            payload["hint"] = self.hint
        if self.details:
            payload["details"] = _serialize(self.details)
        return payload


@dataclass(frozen=True)
class RecipeResult:
    """JSON-ready result returned by :func:`run_recipe`."""

    workflow: str
    mode: str
    result: Any | None = None
    plan: Mapping[str, Any] | None = None
    artifacts: tuple[Mapping[str, Any], ...] = ()

    @property
    def ok(self) -> bool:
        return True

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": AGENT_CONTRACT_VERSION,
            "contract": "exergy-agent-response",
            "ok": True,
            "workflow": self.workflow,
            "mode": self.mode,
            "artifacts": [_serialize(item) for item in self.artifacts],
        }
        if self.result is not None:
            payload["result"] = _serialize(self.result)
        if self.plan is not None:
            payload["plan"] = _serialize(self.plan)
        return payload


@dataclass(frozen=True)
class WorkflowSpec:
    id: str
    description: str
    executor: Callable[[Mapping[str, Any]], Any]
    input_schema: Mapping[str, Any]
    output_schema: str | None = None
    aliases: tuple[str, ...] = ()
    output_formats: tuple[str, ...] = ("json",)
    side_effects: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "description": self.description,
            "aliases": list(self.aliases),
            "input_schema": _serialize(self.input_schema),
            "output_formats": list(self.output_formats),
            "side_effects": list(self.side_effects),
            "supports": {
                "execute": True,
                "dry_run": True,
                "validate_only": True,
            },
        }
        if self.output_schema is not None:
            schema = load_schema(self.output_schema)
            payload["output_schema"] = {
                "name": self.output_schema,
                "$id": schema.get("$id"),
            }
        return payload


def _serialize(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _serialize(value.to_dict())
    if isinstance(value, float) and not math.isfinite(value):
        raise AgentNativeError(
            "NONFINITE_RESULT",
            "workflow result contains a non-finite number and cannot be encoded as strict JSON",
            hint="Correct the input or model producing NaN or infinity before retrying.",
        )
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize(item) for item in value]
    return value


def _json_type(annotation: Any, default: Any = MISSING) -> dict[str, Any]:
    text = str(annotation)
    if "Mapping" in text or "dict" in text:
        kinds = ["object"]
    elif "Sequence" in text or "Iterable" in text or "tuple" in text or "list" in text:
        kinds = ["array"]
    else:
        kinds = []
        if "bool" in text:
            kinds.append("boolean")
        if "float" in text:
            kinds.append("number")
        elif "int" in text:
            kinds.append("integer")
        if "str" in text or "Path" in text:
            kinds.append("string")
        if not kinds:
            kinds.append("object")
    nullable = "None" in text or default is None
    if nullable:
        kinds.append("null")
    schema: dict[str, Any] = {"type": kinds[0] if len(kinds) == 1 else kinds}
    if default is not MISSING and default is not inspect.Parameter.empty:
        serial = _serialize(default)
        if serial is None or isinstance(serial, (str, int, float, bool, list, dict)):
            schema["default"] = serial
    return schema


def _function_input_schema(
    function: Callable[..., Any],
    *,
    exclude: Sequence[str] = (),
    extra_properties: Mapping[str, Mapping[str, Any]] | None = None,
    required: Sequence[str] | None = None,
) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    inferred_required: list[str] = []
    for name, parameter in inspect.signature(function).parameters.items():
        if name in exclude or parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            continue
        properties[name] = _json_type(parameter.annotation, parameter.default)
        if parameter.default is inspect.Parameter.empty:
            inferred_required.append(name)
    properties.update(dict(extra_properties or {}))
    return {
        "type": "object",
        "properties": properties,
        "required": list(required) if required is not None else inferred_required,
        "additionalProperties": False,
    }


def _technology_input_schema() -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for item in fields(TechnologyCostScenario):
        default = item.default
        if default is MISSING and item.default_factory is not MISSING:
            default = item.default_factory()
        properties[item.name] = _json_type(item.type, default)
        if item.default is MISSING and item.default_factory is MISSING:
            required.append(item.name)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _call(function: Callable[..., Any], inputs: Mapping[str, Any]) -> Any:
    return function(**dict(inputs))


def _execute_technology_cost(inputs: Mapping[str, Any]) -> Any:
    return evaluate_technology_cost_scenario(inputs)


_ENGINEERING_MODELS: dict[str, Callable[..., Any]] = {
    "steam": analyze_steam_system,
    "heat-pump": analyze_heat_pump,
    "furnace": analyze_furnace,
    "refrigeration": analyze_refrigeration,
    "compressed-air": analyze_compressed_air,
}
_ENGINEERING_PARAMETER_SCHEMAS = {
    name: _function_input_schema(function)
    for name, function in _ENGINEERING_MODELS.items()
}


def _engineering_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "model": {"type": "string", "enum": list(_ENGINEERING_MODELS)},
            "parameters": {
                "type": "object",
                "description": (
                    "Use the schema under x-model-parameter-schemas that matches model."
                ),
            },
        },
        "required": ["model", "parameters"],
        "additionalProperties": False,
        "x-model-parameter-schemas": _ENGINEERING_PARAMETER_SCHEMAS,
    }


def _execute_engineering(inputs: Mapping[str, Any]) -> Any:
    model = str(inputs["model"]).strip().lower().replace("_", "-")
    try:
        function = _ENGINEERING_MODELS[model]
    except KeyError as exc:
        raise AgentNativeError(
            "UNKNOWN_ENGINEERING_MODEL",
            f"unknown engineering model {inputs['model']!r}",
            suggested_fields=("model",),
            hint=f"Choose from {', '.join(_ENGINEERING_MODELS)}.",
        ) from exc
    parameters = inputs.get("parameters")
    if not isinstance(parameters, Mapping):
        raise AgentNativeError(
            "MISSING_INPUT",
            "engineering inputs require a parameters object",
            suggested_fields=("parameters",),
        )
    return function(**dict(parameters))


def _execute_waste_heat(inputs: Mapping[str, Any]) -> Any:
    options = dict(inputs)
    sources = options.pop("sources")
    demands = options.pop("demands")
    return match_waste_heat(sources, demands, **options)


def _stream(raw: Mapping[str, Any]) -> ExergyStream:
    return ExergyStream(
        name=str(raw["name"]),
        exergy=float(raw["exergy"]),
        unit=str(raw.get("unit", "MWh_ex")),
        energy=float(raw["energy"]) if raw.get("energy") is not None else None,
        exergy_factor=(
            float(raw["exergy_factor"])
            if raw.get("exergy_factor") is not None
            else None
        ),
        metadata=dict(raw.get("metadata", {})),
    )


def _execute_balance(inputs: Mapping[str, Any]) -> Any:
    return analyze_balance(
        str(inputs["name"]),
        inputs=(_stream(item) for item in inputs.get("inputs", [])),
        products=(_stream(item) for item in inputs.get("products", [])),
        losses=(_stream(item) for item in inputs.get("losses", [])),
        destructions=(
            (_stream(item) for item in inputs["destructions"])
            if "destructions" in inputs
            else None
        ),
        unit=str(inputs.get("unit", "MWh_ex")),
        tolerance=float(inputs.get("tolerance", 1e-9)),
    )


def _execute_normalize_records(inputs: Mapping[str, Any]) -> dict[str, Any]:
    records = inputs["records"]
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise AgentNativeError(
            "INVALID_INPUT",
            "records must be an array of objects",
            suggested_fields=("records",),
        )
    if not all(isinstance(record, Mapping) for record in records):
        raise AgentNativeError(
            "INVALID_INPUT",
            "every records item must be an object",
            suggested_fields=("records",),
        )
    mapping_payload = inputs.get("mapping")
    if mapping_payload is None:
        columns = tuple(dict.fromkeys(key for row in records for key in row))
        mapping = infer_mapping(
            columns,
            required=tuple(str(item) for item in inputs.get("required", ())),
            timezone=inputs.get("timezone"),
        )
    elif isinstance(mapping_payload, Mapping):
        mapping = MappingPlan.from_dict(mapping_payload)
    else:
        raise AgentNativeError(
            "INVALID_INPUT",
            "mapping must be an object",
            suggested_fields=("mapping",),
        )
    result = normalize_records(
        records,
        mapping=mapping,
        missing_policy=inputs.get("missing_policy"),
    )
    return result.to_dict(include_records=bool(inputs.get("include_records", True)))


def _execute_validation(_: Mapping[str, Any]) -> Any:
    return run_bundled_validation_suite()


def _execute_weather_normalization(inputs: Mapping[str, Any]) -> Any:
    return normalize_weather_performance(**dict(inputs))


def _execute_custom_assessment(inputs: Mapping[str, Any]) -> Any:
    return assess_with_pack(inputs["pack"], **dict(inputs["assessment"]))


def _execute_custom_process(inputs: Mapping[str, Any]) -> Any:
    options = dict(inputs)
    pack = options.pop("pack")
    template = str(options.pop("template"))
    energy = options.pop("energy", None)
    return assess_process_with_pack(pack, template, energy, **options)


def _execute_technology_intensity(inputs: Mapping[str, Any]) -> Any:
    return _call(assess_intensity_with_pack, inputs)


def _execute_technology_performance(inputs: Mapping[str, Any]) -> Any:
    return _call(assess_performance_with_pack, inputs)


def _registry_from_optional_pack(inputs: Mapping[str, Any]) -> Any:
    pack = inputs.get("pack")
    return load_technology_pack(pack).registry() if pack is not None else None


def _execute_system(inputs: Mapping[str, Any]) -> Any:
    payload = dict(inputs)
    payload.pop("pack", None)
    return analyze_system_definition(
        payload, registry=_registry_from_optional_pack(inputs)
    )


def _execute_system_timeseries(inputs: Mapping[str, Any]) -> Any:
    payload = dict(inputs)
    payload.pop("pack", None)
    return analyze_system_timeseries_definition(
        payload, registry=_registry_from_optional_pack(inputs)
    )


def _execute_material_balance(inputs: Mapping[str, Any]) -> Any:
    return analyze_material_definition(inputs)


def _execute_technology_model(inputs: Mapping[str, Any]) -> Any:
    return _call(evaluate_technology_model, inputs)


def _execute_pack_validation(inputs: Mapping[str, Any]) -> Any:
    return validate_technology_pack(inputs["pack"])


def _execute_capability_search(inputs: Mapping[str, Any]) -> Any:
    return search_capabilities(
        str(inputs["query"]),
        kind=str(inputs.get("kind", "auto")),
        limit=int(inputs.get("limit", 10)),
    )


_COMMON_REPORT_FORMATS = REPORT_OUTPUTS
_EXERGY_STREAM_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "exergy": {"type": "number"},
        "unit": {"type": "string", "default": "MWh_ex"},
        "energy": {"type": ["number", "null"], "default": None},
        "exergy_factor": {"type": ["number", "null"], "default": None},
        "metadata": {"type": "object", "default": {}},
    },
    "required": ["name", "exergy"],
    "additionalProperties": False,
}
_WASTE_HEAT_SOURCE_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "available_heat_mwh": {"type": "number"},
        "supply_temperature_c": {"type": "number"},
        "minimum_outlet_temperature_c": {"type": "number"},
    },
    "required": [
        "name",
        "available_heat_mwh",
        "supply_temperature_c",
        "minimum_outlet_temperature_c",
    ],
    "additionalProperties": False,
}
_HEAT_DEMAND_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "required_heat_mwh": {"type": "number"},
        "supply_temperature_c": {"type": "number"},
        "return_temperature_c": {"type": "number"},
    },
    "required": [
        "name",
        "required_heat_mwh",
        "supply_temperature_c",
        "return_temperature_c",
    ],
    "additionalProperties": False,
}
_PACK_INPUT_SCHEMA = {
    "type": ["object", "string"],
    "description": "An inline technology-pack object, bundled pack name, or explicit local JSON path.",
}
_SYSTEM_COMPONENT_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "kind": {"type": "string", "enum": list(SYSTEM_COMPONENT_KINDS)},
        "label": {"type": "string"},
        "technology": {"type": "string"},
        "metadata": {"type": "object", "default": {}},
    },
    "required": ["id", "kind"],
    "additionalProperties": False,
}
_SYSTEM_FLOW_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "energy": {"type": "number"},
        "unit": {"type": "string", "default": "MWh"},
        "source": {"type": ["string", "null"]},
        "target": {"type": ["string", "null"]},
        "role": {
            "type": "string",
            "enum": ["resource", "internal", "product", "loss"],
        },
        "carrier": {"type": "string"},
        "exergy": {"type": "number"},
        "exergy_factor": {"type": "number"},
        "tier": {"type": "string", "enum": ["F0", "F1", "F2", "F3", "F4"]},
        "metadata": {"type": "object", "default": {}},
    },
    "required": ["id", "energy"],
    "additionalProperties": False,
}
_SYSTEM_ACCUMULATION_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "component": {"type": "string"},
        "energy_change": {"type": "number"},
        "unit": {"type": "string", "default": "MWh"},
        "exergy_change": {"type": "number"},
        "exergy_factor": {"type": "number"},
        "carrier": {"type": "string"},
        "tier": {"type": "string", "enum": ["F0", "F1", "F2", "F3", "F4"]},
        "metadata": {"type": "object", "default": {}},
    },
    "required": ["component", "energy_change"],
    "additionalProperties": False,
}
_MATERIAL_STREAM_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "mass": {"type": "number"},
        "material": {"type": "string"},
        "unit": {
            "type": "string",
            "enum": ["kg", "g", "t", "tonne", "lb", "short-ton"],
            "default": "kg",
        },
        "source": {"type": ["string", "null"]},
        "target": {"type": ["string", "null"]},
        "role": {
            "type": "string",
            "enum": ["resource", "internal", "product", "loss"],
        },
        "composition": {
            "type": "object",
            "additionalProperties": {"type": "number"},
        },
        "specific_chemical_exergy_mj_per_kg": {"type": "number"},
        "tier": {"type": "string", "enum": ["F0", "F1", "F2", "F3", "F4"]},
        "source_id": {"type": "string"},
        "metadata": {"type": "object", "default": {}},
    },
    "required": ["id", "mass"],
    "additionalProperties": False,
}
_MATERIAL_ACCUMULATION_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "component": {"type": "string"},
        "mass_change": {"type": "number"},
        "material": {"type": "string"},
        "unit": {
            "type": "string",
            "enum": ["kg", "g", "t", "tonne", "lb", "short-ton"],
            "default": "kg",
        },
        "composition": {
            "type": "object",
            "additionalProperties": {"type": "number"},
        },
        "specific_chemical_exergy_mj_per_kg": {"type": "number"},
        "tier": {"type": "string", "enum": ["F0", "F1", "F2", "F3", "F4"]},
        "source_id": {"type": "string"},
        "metadata": {"type": "object", "default": {}},
    },
    "required": ["component", "mass_change"],
    "additionalProperties": False,
}
_SYSTEM_PROPERTIES = {
    "name": {"type": "string"},
    "components": {"type": "array", "items": _SYSTEM_COMPONENT_INPUT_SCHEMA},
    "flows": {"type": "array", "items": _SYSTEM_FLOW_INPUT_SCHEMA},
    "accumulations": {
        "type": "array",
        "items": _SYSTEM_ACCUMULATION_INPUT_SCHEMA,
    },
    "unit": {"type": "string", "default": "MWh"},
    "tolerance": {"type": "number", "default": 1e-9},
    "pack": _PACK_INPUT_SCHEMA,
}
_CUSTOM_ASSESSMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "pack": _PACK_INPUT_SCHEMA,
        "assessment": _function_input_schema(assess, exclude=("registry",)),
    },
    "required": ["pack", "assessment"],
    "additionalProperties": False,
}
_CUSTOM_PROCESS_BASE_SCHEMA = _function_input_schema(
    assess_process, exclude=("factor_library", "registry", "catalog")
)
_CUSTOM_PROCESS_SCHEMA = {
    **_CUSTOM_PROCESS_BASE_SCHEMA,
    "properties": {
        "pack": _PACK_INPUT_SCHEMA,
        **_CUSTOM_PROCESS_BASE_SCHEMA["properties"],
    },
    "required": ["pack", "template"],
}
_TECHNOLOGY_INTENSITY_SCHEMA = {
    "type": "object",
    "properties": {
        "pack": _PACK_INPUT_SCHEMA,
        "technology": {"type": "string"},
        "output_mass": {"type": "number", "exclusiveMinimum": 0},
        "output_unit": {
            "type": "string",
            "enum": ["kg", "g", "t", "tonne", "lb", "short-ton"],
            "default": "t",
        },
        "specific_energy_mwh_per_tonne": {
            "type": ["number", "null"],
            "exclusiveMinimum": 0,
            "default": None,
        },
        "estimate_context": {
            "type": ["object", "null"],
            "default": None,
        },
        "strict": {"type": "boolean", "default": False},
    },
    "required": ["pack", "technology", "output_mass"],
    "additionalProperties": False,
}
_TECHNOLOGY_PERFORMANCE_SCHEMA = {
    "type": "object",
    "properties": {
        "pack": _PACK_INPUT_SCHEMA,
        "technology": {"type": "string"},
        "input_energy": {"type": "number", "minimum": 0},
        "unit": {"type": "string", "default": "MWh"},
        "performance": {
            "type": ["number", "null"],
            "exclusiveMinimum": 0,
            "default": None,
        },
        "estimate_context": {
            "type": ["object", "null"],
            "default": None,
        },
        "strict": {"type": "boolean", "default": False},
    },
    "required": ["pack", "technology", "input_energy"],
    "additionalProperties": False,
}
_SYSTEM_TIMESERIES_RECORD_SCHEMA = {
    "type": "object",
    "properties": {
        "timestamp": {"type": "string"},
        "weight": {"type": "number", "default": 1.0},
        "duration_hours": {"type": ["number", "null"], "default": None},
        "flows": {"type": "array", "items": _SYSTEM_FLOW_INPUT_SCHEMA},
        "accumulations": {
            "type": "array",
            "items": _SYSTEM_ACCUMULATION_INPUT_SCHEMA,
        },
    },
    "required": ["timestamp", "flows"],
    "additionalProperties": False,
}

WORKFLOW_SPECS: tuple[WorkflowSpec, ...] = (
    WorkflowSpec(
        "assessment",
        "Progressive-fidelity carrier, service, or technology exergy assessment.",
        lambda inputs: _call(assess, inputs),
        _function_input_schema(assess, exclude=("registry",)),
        "assessment",
        aliases=("assess", "exergy-assessment", "calculate-exergy"),
        output_formats=_COMMON_REPORT_FORMATS,
    ),
    WorkflowSpec(
        "custom-assessment",
        "Run a progressive-fidelity assessment with an explicitly loaded technology pack.",
        _execute_custom_assessment,
        _CUSTOM_ASSESSMENT_SCHEMA,
        "assessment",
        aliases=("packed-assessment",),
        output_formats=_COMMON_REPORT_FORMATS,
    ),
    WorkflowSpec(
        "process-assessment",
        "Integrated process exergy, impact, opportunity, and economic screen.",
        lambda inputs: _call(assess_process, inputs),
        _function_input_schema(
            assess_process, exclude=("factor_library", "registry", "catalog")
        ),
        "process",
        aliases=("process", "assess-process"),
        output_formats=_COMMON_REPORT_FORMATS,
    ),
    WorkflowSpec(
        "custom-process-assessment",
        "Run an integrated process assessment with an explicitly loaded technology pack.",
        _execute_custom_process,
        _CUSTOM_PROCESS_SCHEMA,
        "process",
        aliases=("packed-process",),
        output_formats=_COMMON_REPORT_FORMATS,
    ),
    WorkflowSpec(
        "technology-intensity",
        "Estimate process input energy from a sourced mass-normalized pack prior without implying conversion efficiency.",
        _execute_technology_intensity,
        _TECHNOLOGY_INTENSITY_SCHEMA,
        "technology-intensity",
        aliases=("process-intensity", "material-energy-intensity"),
        output_formats=("json",),
    ),
    WorkflowSpec(
        "technology-performance",
        "Estimate energy output from a sourced efficiency or COP without inventing exergy quality.",
        _execute_technology_performance,
        _TECHNOLOGY_PERFORMANCE_SCHEMA,
        "technology-performance",
        aliases=("performance-screen", "energy-performance"),
        output_formats=("json",),
    ),
    WorkflowSpec(
        "impacts",
        "Greenhouse-gas, warming-horizon, pollutant, and health-hazard screen.",
        lambda inputs: _call(assess_impacts, inputs),
        _function_input_schema(
            assess_impacts, exclude=("assessment", "factor_library")
        ),
        "environmental",
        aliases=("environmental", "screen-impacts"),
        output_formats=_COMMON_REPORT_FORMATS,
    ),
    WorkflowSpec(
        "ghg-boundaries",
        "Explicit combustion, process, fugitive, and purchased-energy GHG accounting.",
        lambda inputs: _call(assess_ghg_boundaries, inputs),
        _function_input_schema(assess_ghg_boundaries, exclude=("factor_library",)),
        "ghg-boundary",
        output_formats=_COMMON_REPORT_FORMATS,
    ),
    WorkflowSpec(
        "methane-project",
        "Compare methane venting, flaring, oxidation, and recovery projects.",
        lambda inputs: _call(assess_methane_project, inputs),
        _function_input_schema(assess_methane_project, exclude=("factor_library",)),
        "methane-project",
        aliases=("methane",),
        output_formats=_COMMON_REPORT_FORMATS,
    ),
    WorkflowSpec(
        "economics",
        "Evaluate standard project cash flow, payback, levelized cost, and abatement metrics.",
        lambda inputs: _call(evaluate_economics, inputs),
        _function_input_schema(evaluate_economics),
        "economic",
        aliases=("project-economics", "evaluate-economics"),
        output_formats=_COMMON_REPORT_FORMATS,
    ),
    WorkflowSpec(
        "technology-cost",
        "Evaluate a user-supplied technology cost and output scenario.",
        _execute_technology_cost,
        _technology_input_schema(),
        "technology-economic",
        output_formats=_COMMON_REPORT_FORMATS,
    ),
    WorkflowSpec(
        "engineering",
        "Run a steam, heat-pump, furnace, refrigeration, or compressed-air model.",
        _execute_engineering,
        _engineering_input_schema(),
        "engineering",
        aliases=("engineering-model",),
        output_formats=_COMMON_REPORT_FORMATS,
    ),
    WorkflowSpec(
        "waste-heat",
        "Match waste-heat sources to compatible demands with quality accounting.",
        _execute_waste_heat,
        {
            "type": "object",
            "properties": {
                "sources": {
                    "type": "array",
                    "items": _WASTE_HEAT_SOURCE_INPUT_SCHEMA,
                },
                "demands": {
                    "type": "array",
                    "items": _HEAT_DEMAND_INPUT_SCHEMA,
                },
                "minimum_approach_temperature_c": {"type": "number", "default": 10.0},
                "reference_temperature_c": {"type": "number", "default": 25.0},
            },
            "required": ["sources", "demands"],
            "additionalProperties": False,
        },
        "engineering",
        output_formats=_COMMON_REPORT_FORMATS,
    ),
    WorkflowSpec(
        "exergy-balance",
        "Analyze named exergy input, product, loss, and destruction streams.",
        _execute_balance,
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "inputs": {"type": "array", "items": _EXERGY_STREAM_INPUT_SCHEMA},
                "products": {
                    "type": "array",
                    "items": _EXERGY_STREAM_INPUT_SCHEMA,
                },
                "losses": {"type": "array", "items": _EXERGY_STREAM_INPUT_SCHEMA},
                "destructions": {
                    "type": "array",
                    "items": _EXERGY_STREAM_INPUT_SCHEMA,
                },
                "unit": {"type": "string", "default": "MWh_ex"},
                "tolerance": {"type": "number", "default": 1e-9},
            },
            "required": ["name", "inputs", "products"],
            "additionalProperties": False,
        },
        aliases=("balance",),
        output_formats=("json",),
    ),
    WorkflowSpec(
        "technology-model",
        "Evaluate a registered single-input technology model from explicit performance and exergy factors.",
        _execute_technology_model,
        _function_input_schema(evaluate_technology_model, exclude=("registry",)),
        "technology-model",
        aliases=("evaluate-technology-model",),
        output_formats=("json",),
    ),
    WorkflowSpec(
        "material-balance",
        "Account for mass, composition, and explicit chemical exergy without conflating them with energy destruction.",
        _execute_material_balance,
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "components": {
                    "type": "array",
                    "items": _SYSTEM_COMPONENT_INPUT_SCHEMA,
                },
                "streams": {
                    "type": "array",
                    "items": _MATERIAL_STREAM_INPUT_SCHEMA,
                },
                "accumulations": {
                    "type": "array",
                    "items": _MATERIAL_ACCUMULATION_INPUT_SCHEMA,
                },
                "tolerance_kg": {"type": "number", "default": 1e-6},
                "source_catalog": {"type": "object", "default": {}},
            },
            "required": ["name", "components", "streams"],
            "additionalProperties": False,
        },
        "material-balance",
        aliases=("materials", "mass-balance"),
        output_formats=("json",),
    ),
    WorkflowSpec(
        "system-analysis",
        "Account for energy and exergy across arbitrary connected component boundaries.",
        _execute_system,
        {
            "type": "object",
            "properties": dict(_SYSTEM_PROPERTIES),
            "required": ["name", "components", "flows"],
            "additionalProperties": False,
        },
        "system-analysis",
        aliases=("system", "flowsheet"),
        output_formats=("json",),
    ),
    WorkflowSpec(
        "system-timeseries",
        "Aggregate chronological connected-system records without treating power as energy.",
        _execute_system_timeseries,
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "components": {
                    "type": "array",
                    "items": _SYSTEM_COMPONENT_INPUT_SCHEMA,
                },
                "records": {
                    "type": "array",
                    "items": _SYSTEM_TIMESERIES_RECORD_SCHEMA,
                },
                "unit": {"type": "string", "default": "MWh"},
                "tolerance": {"type": "number", "default": 1e-9},
                "include_snapshots": {"type": "boolean", "default": True},
                "pack": _PACK_INPUT_SCHEMA,
            },
            "required": ["name", "components", "records"],
            "additionalProperties": False,
        },
        "system-timeseries",
        aliases=("chronological-system",),
        output_formats=("json",),
    ),
    WorkflowSpec(
        "technology-pack-validation",
        "Validate a local or inline technology/process pack and all provenance fields.",
        _execute_pack_validation,
        {
            "type": "object",
            "properties": {"pack": _PACK_INPUT_SCHEMA},
            "required": ["pack"],
            "additionalProperties": False,
        },
        aliases=("validate-pack",),
        output_formats=("json",),
    ),
    WorkflowSpec(
        "capability-search",
        "Search named and generic workflows, profiles, components, packs, and schemas.",
        _execute_capability_search,
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": [
                        "auto",
                        "workflow",
                        "process",
                        "profile",
                        "component",
                        "model",
                        "material",
                        "pack",
                        "schema",
                    ],
                    "default": "auto",
                },
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        aliases=("search", "find-capability"),
        output_formats=("json",),
    ),
    WorkflowSpec(
        "normalize-records",
        "Infer or apply a field mapping and normalize in-memory industrial records.",
        _execute_normalize_records,
        {
            "type": "object",
            "properties": {
                "records": {"type": "array", "items": {"type": "object"}},
                "mapping": {"type": ["object", "null"], "default": None},
                "required": {"type": "array", "items": {"type": "string"}},
                "timezone": {"type": ["string", "null"], "default": None},
                "missing_policy": {
                    "type": ["string", "null"],
                    "enum": [
                        "keep",
                        "drop",
                        "raise",
                        "forward-fill",
                        "interpolate",
                        None,
                    ],
                    "default": None,
                },
                "include_records": {"type": "boolean", "default": True},
            },
            "required": ["records"],
            "additionalProperties": False,
        },
        aliases=("normalize-dataset", "ingest"),
        output_formats=("json",),
    ),
    WorkflowSpec(
        "weather-normalization",
        "Normalize an in-memory daily metric against degree-day weather.",
        _execute_weather_normalization,
        _function_input_schema(
            normalize_weather_performance,
            exclude=("climatology",),
            extra_properties={
                "records": {"type": "array", "items": {"type": "object"}}
            },
        ),
        "weather-normalization",
        output_formats=_COMMON_REPORT_FORMATS,
    ),
    WorkflowSpec(
        "validation-suite",
        "Run the packaged scientific reference cases.",
        _execute_validation,
        {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "validation",
        aliases=("validate",),
        output_formats=("json",),
    ),
)

_WORKFLOW_INDEX = {
    alias: spec for spec in WORKFLOW_SPECS for alias in (spec.id, *spec.aliases)
}


def get_workflow_spec(name: str) -> WorkflowSpec:
    key = str(name).strip().lower().replace("_", "-")
    try:
        return _WORKFLOW_INDEX[key]
    except KeyError as exc:
        raise AgentNativeError(
            "UNKNOWN_WORKFLOW",
            f"unknown workflow {name!r}",
            suggested_fields=("workflow",),
            hint="Use list_capabilities() or `exergy capabilities --json` to discover workflows.",
            details={"available_workflows": [item.id for item in WORKFLOW_SPECS]},
        ) from exc


def describe_workflow(name: str) -> dict[str, Any]:
    """Return the stable input and output contract for one workflow."""

    return get_workflow_spec(name).to_dict()


def list_capabilities() -> dict[str, Any]:
    """Return agent-readable workflow, schema, safety, and interface metadata."""

    return {
        "schema_version": AGENT_CONTRACT_VERSION,
        "contract": "exergy-agent-capabilities",
        "package": "exergy-imperative",
        "package_version": LIBRARY_VERSION,
        "recipe_modes": list(RECIPE_MODES),
        "interfaces": {
            "python": "exergy_imperative.run_recipe",
            "cli": "exergy run RECIPE.json --json",
            "mcp": "exergy-mcp (install the mcp extra)",
        },
        "workflows": [item.to_dict() for item in WORKFLOW_SPECS],
        "schemas": list_schemas(),
        "catalog": {
            "process_template_count": len(list_process_templates()),
            "profile_categories": list(DEFAULT_REGISTRY.categories()),
            "profile_count": len(DEFAULT_REGISTRY.list()),
            "system_component_kinds": list(SYSTEM_COMPONENT_KINDS),
            "technology_models": [
                item.to_dict() for item in DEFAULT_TECHNOLOGY_MODEL_REGISTRY.list()
            ],
            "technology_packs": list(bundled_technology_pack_info()),
            "datasets": [item.to_dict() for item in list_datasets()],
        },
        "safety": {
            "network_access": "No recipe workflow performs implicit network access.",
            "file_writes": "Only execute-mode recipes with explicit outputs write files.",
            "licensed_data": "Publisher datasets are not bundled; local adapters contain field mappings only.",
            "health": "Pollutant results are inventory and hazard screens, not exposure or clinical risk estimates.",
        },
    }


def _capability_score(query: str, texts: Sequence[str]) -> float:
    normalized_query = query.casefold().strip().replace("_", "-")
    normalized_texts = [text.casefold().replace("_", "-") for text in texts if text]
    if any(normalized_query == text for text in normalized_texts):
        return 1.0
    contains = max(
        (
            min(0.96, 0.78 + len(normalized_query) / max(len(text), 1) * 0.18)
            for text in normalized_texts
            if normalized_query in text
        ),
        default=0.0,
    )
    query_tokens = set(normalized_query.replace("-", " ").split())
    token_score = max(
        (
            len(query_tokens & set(text.replace("-", " ").split()))
            / max(len(query_tokens), 1)
            * 0.82
            for text in normalized_texts
        ),
        default=0.0,
    )
    similarity = max(
        (
            SequenceMatcher(None, normalized_query, text).ratio() * 0.75
            for text in normalized_texts
        ),
        default=0.0,
    )
    return max(contains, token_score, similarity)


def search_capabilities(
    query: str, *, kind: str = "auto", limit: int = 10
) -> dict[str, Any]:
    """Search workflows, profiles, templates, components, models, packs, and schemas."""

    normalized_query = str(query).strip()
    if not normalized_query:
        raise AgentNativeError(
            "INVALID_ARGUMENT",
            "capability search query must not be empty",
            suggested_fields=("query",),
        )
    normalized_kind = str(kind).strip().lower().replace("_", "-")
    valid_kinds = {
        "auto",
        "workflow",
        "process",
        "profile",
        "component",
        "model",
        "material",
        "pack",
        "schema",
    }
    if normalized_kind not in valid_kinds:
        raise AgentNativeError(
            "INVALID_ARGUMENT",
            "kind must be " + ", ".join(sorted(valid_kinds)),
            suggested_fields=("kind",),
        )
    try:
        limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise AgentNativeError(
            "INVALID_ARGUMENT", "limit must be an integer", suggested_fields=("limit",)
        ) from exc
    if not 1 <= limit <= 100:
        raise AgentNativeError(
            "INVALID_ARGUMENT",
            "limit must be between 1 and 100",
            suggested_fields=("limit",),
        )
    candidates: list[dict[str, Any]] = []
    if normalized_kind in {"auto", "workflow"}:
        for item in WORKFLOW_SPECS:
            candidates.append(
                {
                    "kind": "workflow",
                    "id": item.id,
                    "label": item.id,
                    "description": item.description,
                    "aliases": list(item.aliases),
                    "score": _capability_score(
                        normalized_query,
                        (item.id, item.description, *item.aliases),
                    ),
                    "next_action": f"describe_workflow({item.id!r})",
                }
            )
    if normalized_kind in {"auto", "process"}:
        for item in list_process_templates():
            candidates.append(
                {
                    "kind": "process",
                    "id": item.id,
                    "label": item.label,
                    "description": item.description,
                    "aliases": list(item.aliases),
                    "score": _capability_score(
                        normalized_query,
                        (
                            item.id,
                            item.label,
                            item.description,
                            item.sector,
                            *item.aliases,
                        ),
                    ),
                    "next_action": (
                        "Run process-assessment in validate-only mode with "
                        f"template={item.id!r}."
                    ),
                }
            )
    if normalized_kind in {"auto", "profile"}:
        for item in DEFAULT_REGISTRY.list():
            candidates.append(
                {
                    "kind": "profile",
                    "category": item.category,
                    "id": item.id,
                    "label": item.label,
                    "aliases": list(item.aliases),
                    "score": _capability_score(
                        normalized_query,
                        (item.id, item.label, item.category, *item.aliases),
                    ),
                    "next_action": (
                        f"Use {item.category}={item.id!r} in an assessment recipe."
                    ),
                }
            )
    if normalized_kind in {"auto", "component"}:
        for item in SYSTEM_COMPONENT_KINDS:
            candidates.append(
                {
                    "kind": "component",
                    "id": item,
                    "label": item.replace("-", " ").title(),
                    "description": (
                        "Generic accounting component for explicit incoming, outgoing, "
                        "loss, and storage flows."
                    ),
                    "score": _capability_score(normalized_query, (item,)),
                    "next_action": "Use it in a system-analysis component definition.",
                }
            )
    if normalized_kind in {"auto", "model"}:
        for item in DEFAULT_TECHNOLOGY_MODEL_REGISTRY.list():
            candidates.append(
                {
                    "kind": "model",
                    "id": item.id,
                    "label": item.label,
                    "description": item.description,
                    "aliases": list(item.aliases),
                    "score": _capability_score(
                        normalized_query,
                        (item.id, item.label, item.description, *item.aliases),
                    ),
                    "next_action": (
                        f"Use model={item.id!r} in a technology pack or call "
                        "evaluate_technology_model."
                    ),
                }
            )
    if normalized_kind in {"auto", "pack"}:
        for item in bundled_technology_pack_info():
            pack = load_technology_pack(str(item["id"]))
            profile_terms = tuple(
                str(value)
                for records in pack.profiles.values()
                for profile in records
                for value in (
                    profile.get("id", ""),
                    profile.get("label", ""),
                    *profile.get("aliases", ()),
                )
            )
            material_terms = tuple(
                str(value)
                for template in pack.material_templates
                for value in (
                    template.get("id", ""),
                    template.get("label", ""),
                    template.get("boundary", ""),
                    *template.get("aliases", ()),
                )
            )
            candidates.append(
                {
                    "kind": "pack",
                    **dict(item),
                    "label": item["id"].replace("-", " ").title(),
                    "score": _capability_score(
                        normalized_query,
                        (
                            str(item["id"]),
                            str(item["description"]),
                            *(str(value) for value in item["domains"]),
                            *profile_terms,
                            *material_terms,
                        ),
                    ),
                    "next_action": (
                        f"Load bundled pack {item['id']!r} or use custom-assessment."
                    ),
                }
            )
    if normalized_kind in {"auto", "material"}:
        for pack_name in (str(item["id"]) for item in bundled_technology_pack_info()):
            pack = load_technology_pack(pack_name)
            for item in pack.material_templates:
                candidates.append(
                    {
                        "kind": "material",
                        "id": str(item["id"]),
                        "label": str(item["label"]),
                        "description": str(item["boundary"]),
                        "pack": pack.id,
                        "aliases": list(item.get("aliases", ())),
                        "score": _capability_score(
                            normalized_query,
                            (
                                str(item["id"]),
                                str(item["label"]),
                                str(item["boundary"]),
                                *(str(value) for value in item.get("aliases", ())),
                            ),
                        ),
                        "next_action": (
                            "Use the template's required_inputs to construct a "
                            "material-balance recipe."
                        ),
                    }
                )
    if normalized_kind in {"auto", "schema"}:
        for item in list_schemas():
            candidates.append(
                {
                    "kind": "schema",
                    "id": item["name"],
                    "label": item["name"],
                    "description": str(item.get("$id", "")),
                    "score": _capability_score(
                        normalized_query,
                        (str(item["name"]), str(item.get("$id", ""))),
                    ),
                    "next_action": f"load_schema({item['name']!r})",
                }
            )
    matches = [item for item in candidates if item["score"] >= 0.3]
    matches.sort(key=lambda item: (-item["score"], item["kind"], item["id"]))
    for item in matches:
        item["score"] = round(float(item["score"]), 3)
    return {
        "query": normalized_query,
        "kind": normalized_kind,
        "matches": matches[:limit],
        "fallback": (
            None
            if matches
            else {
                "workflow": (
                    "material-balance"
                    if normalized_kind == "material"
                    else "system-analysis"
                ),
                "reason": (
                    "Define explicit material streams when no material template "
                    "matches."
                    if normalized_kind == "material"
                    else "Define explicit components and energy/exergy flows when no named technology matches."
                ),
            }
        ),
    }


def describe_target(name: str, *, kind: str = "auto") -> dict[str, Any]:
    """Describe a workflow, process template, or bundled profile."""

    normalized_kind = str(kind).strip().lower().replace("_", "-")
    if normalized_kind not in {
        "auto",
        "workflow",
        "process",
        "profile",
        "component",
        "model",
        "material",
        "pack",
        "schema",
    }:
        raise AgentNativeError(
            "INVALID_ARGUMENT",
            "kind must be auto, workflow, process, profile, component, model, material, pack, or schema",
            suggested_fields=("kind",),
        )
    if normalized_kind in {"auto", "workflow"}:
        try:
            return {"kind": "workflow", "item": describe_workflow(name)}
        except AgentNativeError:
            if normalized_kind == "workflow":
                raise
    if normalized_kind in {"auto", "process"}:
        try:
            return {"kind": "process", "item": get_process_template(name).to_dict()}
        except ProcessTemplateNotFoundError:
            if normalized_kind == "process":
                raise AgentNativeError(
                    "UNKNOWN_PROCESS_TEMPLATE",
                    f"unknown process template {name!r}",
                    suggested_fields=("name",),
                    details={
                        "available_processes": [
                            item.id for item in list_process_templates()
                        ]
                    },
                ) from None
    matches = []
    if normalized_kind in {"auto", "profile"}:
        for category in DEFAULT_REGISTRY.categories():
            profile = DEFAULT_REGISTRY.find(category, name)
            if profile is not None and profile.id not in {
                item["id"] for item in matches
            }:
                matches.append(profile.to_dict())
        if matches:
            return {"kind": "profile", "items": matches}
    if normalized_kind in {"auto", "component"}:
        component = str(name).strip().lower().replace("_", "-")
        if component in SYSTEM_COMPONENT_KINDS:
            return {
                "kind": "component",
                "item": {
                    "id": component,
                    "description": (
                        "Generic accounting boundary used by system-analysis; "
                        "performance and flows remain explicit."
                    ),
                },
            }
    if normalized_kind in {"auto", "model"}:
        try:
            return {
                "kind": "model",
                "item": DEFAULT_TECHNOLOGY_MODEL_REGISTRY.get(name).to_dict(),
            }
        except KeyError:
            if normalized_kind == "model":
                pass
    if normalized_kind in {"auto", "material"}:
        material_key = str(name).strip().lower().replace("_", "-")
        material_matches = []
        for pack_info in bundled_technology_pack_info():
            pack = load_technology_pack(str(pack_info["id"]))
            for item in pack.material_templates:
                names = {
                    str(item["id"]).strip().lower().replace("_", "-"),
                    str(item["label"]).strip().lower().replace("_", "-"),
                    *(
                        str(value).strip().lower().replace("_", "-")
                        for value in item.get("aliases", ())
                    ),
                }
                if material_key in names:
                    material_matches.append({"pack": pack.id, **dict(item)})
        if material_matches:
            return {"kind": "material", "items": material_matches}
    if normalized_kind in {"auto", "pack"}:
        for item in bundled_technology_pack_info():
            if item["id"] == str(name).strip().lower().replace("_", "-"):
                return {"kind": "pack", "item": dict(item)}
    if normalized_kind in {"auto", "schema"}:
        try:
            return {"kind": "schema", "item": load_schema(name)}
        except KeyError:
            pass
    search = search_capabilities(name, kind=normalized_kind, limit=5)
    raise AgentNativeError(
        "UNKNOWN_TARGET",
        f"no capability matched {name!r}",
        suggested_fields=("name", "kind"),
        hint="Use capability search to discover a named item or the generic system workflow.",
        details={"suggestions": search["matches"]},
    )


def _validate_object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AgentNativeError(
            "INVALID_RECIPE",
            f"{name} must be an object",
            suggested_fields=(name,),
        )
    invalid_keys = [key for key in value if not isinstance(key, str)]
    if invalid_keys:
        raise AgentNativeError(
            "INVALID_INPUT_TYPE",
            f"{name} object keys must be strings",
            suggested_fields=(name,),
            details={"invalid_keys": [repr(key) for key in invalid_keys]},
        )
    return value


def _matches_json_type(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, Sequence) and not isinstance(value, (str, bytes))
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


def _validate_schema_value(
    workflow: str,
    value: Any,
    field_schema: Mapping[str, Any],
    *,
    path: str,
    suggested_field: str,
) -> None:
    raw_types = field_schema.get("type")
    expected_types = (
        (raw_types,) if isinstance(raw_types, str) else tuple(raw_types or ())
    )
    if expected_types and not any(
        _matches_json_type(value, expected) for expected in expected_types
    ):
        raise AgentNativeError(
            "INVALID_INPUT_TYPE",
            f"{workflow} input {path!r} must have JSON type "
            + " or ".join(expected_types),
            suggested_fields=(suggested_field,),
            details={"actual_type": type(value).__name__, "path": path},
        )
    if isinstance(value, float) and not math.isfinite(value):
        raise AgentNativeError(
            "NONFINITE_NUMBER",
            f"{workflow} input {path!r} must be a finite number",
            suggested_fields=(suggested_field,),
            details={"path": path},
        )
    if "enum" in field_schema and value not in field_schema["enum"]:
        raise AgentNativeError(
            "INVALID_INPUT_VALUE",
            f"{workflow} input {path!r} must be one of "
            + ", ".join(repr(item) for item in field_schema["enum"]),
            suggested_fields=(suggested_field,),
        )
    if isinstance(value, Mapping):
        invalid_keys = [key for key in value if not isinstance(key, str)]
        if invalid_keys:
            raise AgentNativeError(
                "INVALID_INPUT_TYPE",
                f"{workflow} input {path!r} object keys must be strings",
                suggested_fields=(suggested_field,),
                details={"path": path},
            )
        properties = field_schema.get("properties", {})
        if isinstance(properties, Mapping):
            if field_schema.get("additionalProperties") is False:
                unknown = sorted(set(value) - set(properties))
                if unknown:
                    raise AgentNativeError(
                        "UNKNOWN_INPUT_FIELD",
                        f"unknown fields at {path}: " + ", ".join(unknown),
                        suggested_fields=(suggested_field,),
                        details={"path": path, "unknown_fields": unknown},
                    )
            missing = [
                name for name in field_schema.get("required", ()) if name not in value
            ]
            if missing:
                raise AgentNativeError(
                    "MISSING_INPUT",
                    f"missing required fields at {path}: " + ", ".join(missing),
                    suggested_fields=(suggested_field,),
                    details={"path": path, "missing_fields": missing},
                )
            for name, item in value.items():
                child_schema = properties.get(name, {})
                if isinstance(child_schema, Mapping):
                    _validate_schema_value(
                        workflow,
                        item,
                        child_schema,
                        path=f"{path}.{name}",
                        suggested_field=suggested_field,
                    )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        item_schema = field_schema.get("items", {})
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                _validate_schema_value(
                    workflow,
                    item,
                    item_schema,
                    path=f"{path}[{index}]",
                    suggested_field=suggested_field,
                )


def _validate_input_values(
    workflow: str,
    inputs: Mapping[str, Any],
    properties: Mapping[str, Any],
) -> None:
    for name, value in inputs.items():
        field_schema = properties.get(name, {})
        if isinstance(field_schema, Mapping):
            _validate_schema_value(
                workflow,
                value,
                field_schema,
                path=name,
                suggested_field=name,
            )


def _normalize_recipe(
    recipe: Mapping[str, Any], mode: str | None
) -> tuple[WorkflowSpec, dict[str, Any], dict[str, str], str]:
    payload = dict(_validate_object(recipe, "recipe"))
    unknown_root = sorted(
        set(payload) - {"schema_version", "workflow", "inputs", "outputs", "mode"}
    )
    if unknown_root:
        raise AgentNativeError(
            "UNKNOWN_RECIPE_FIELD",
            "unknown recipe fields: " + ", ".join(unknown_root),
            suggested_fields=tuple(unknown_root),
            hint="Recipe fields are schema_version, workflow, inputs, outputs, and mode.",
        )
    schema_version = str(payload.get("schema_version", AGENT_CONTRACT_VERSION))
    if schema_version != AGENT_CONTRACT_VERSION:
        raise AgentNativeError(
            "UNSUPPORTED_SCHEMA_VERSION",
            f"unsupported recipe schema version {schema_version!r}",
            suggested_fields=("schema_version",),
            hint=f"Use schema_version {AGENT_CONTRACT_VERSION!r}.",
        )
    workflow = payload.get("workflow")
    if not isinstance(workflow, str) or not workflow.strip():
        raise AgentNativeError(
            "MISSING_INPUT",
            "recipe requires a non-empty workflow",
            suggested_fields=("workflow",),
        )
    spec = get_workflow_spec(workflow)
    if "inputs" not in payload:
        raise AgentNativeError(
            "MISSING_INPUT",
            "recipe requires an inputs object; use an empty object when the workflow has no inputs",
            suggested_fields=("inputs",),
        )
    inputs = dict(_validate_object(payload["inputs"], "inputs"))
    raw_outputs = _validate_object(payload.get("outputs", {}), "outputs")
    outputs: dict[str, str] = {}
    for name, path in raw_outputs.items():
        if name not in REPORT_OUTPUTS:
            raise AgentNativeError(
                "UNKNOWN_OUTPUT_FORMAT",
                f"unknown output format {name!r}",
                suggested_fields=("outputs",),
                hint=f"Choose from {', '.join(REPORT_OUTPUTS)}.",
            )
        if not isinstance(path, (str, Path)) or not str(path).strip():
            raise AgentNativeError(
                "INVALID_OUTPUT_PATH",
                f"output path for {name!r} must be a non-empty string",
                suggested_fields=("outputs",),
            )
        outputs[name] = str(path)
    selected_mode = str(mode or payload.get("mode", "execute")).strip().lower()
    if selected_mode not in RECIPE_MODES:
        raise AgentNativeError(
            "INVALID_RECIPE_MODE",
            f"unknown recipe mode {selected_mode!r}",
            suggested_fields=("mode",),
            hint=f"Choose from {', '.join(RECIPE_MODES)}.",
        )
    properties = spec.input_schema.get("properties", {})
    unknown_inputs = sorted(set(inputs) - set(properties))
    if unknown_inputs:
        raise AgentNativeError(
            "UNKNOWN_INPUT_FIELD",
            f"unknown inputs for {spec.id}: " + ", ".join(unknown_inputs),
            suggested_fields=tuple(unknown_inputs),
            hint="Use describe_workflow() to inspect accepted inputs.",
        )
    _validate_input_values(spec.id, inputs, properties)
    required = tuple(spec.input_schema.get("required", ()))
    missing = tuple(name for name in required if name not in inputs)
    if missing:
        raise AgentNativeError(
            "MISSING_INPUT",
            f"missing required inputs for {spec.id}: " + ", ".join(missing),
            suggested_fields=missing,
        )
    if spec.id == "engineering":
        model = str(inputs["model"])
        _validate_schema_value(
            spec.id,
            inputs["parameters"],
            _ENGINEERING_PARAMETER_SCHEMAS[model],
            path="parameters",
            suggested_field="parameters",
        )
    unsupported = sorted(set(outputs) - set(spec.output_formats))
    if unsupported:
        raise AgentNativeError(
            "UNSUPPORTED_OUTPUT",
            f"{spec.id} does not support outputs: " + ", ".join(unsupported),
            suggested_fields=("outputs",),
            details={"supported_outputs": list(spec.output_formats)},
        )
    return spec, inputs, outputs, selected_mode


def validate_recipe(
    recipe: Mapping[str, Any], *, mode: str | None = None
) -> dict[str, Any]:
    """Validate recipe structure without executing calculations or writing files."""

    spec, inputs, outputs, selected_mode = _normalize_recipe(recipe, mode)
    properties = spec.input_schema.get("properties", {})
    defaults = {
        name: details["default"]
        for name, details in properties.items()
        if isinstance(details, Mapping) and "default" in details and name not in inputs
    }
    return {
        "valid": True,
        "workflow": spec.id,
        "requested_mode": selected_mode,
        "supplied_inputs": sorted(inputs),
        "defaulted_inputs": defaults,
        "requested_outputs": dict(outputs),
        "will_execute_calculations": selected_mode in {"execute", "dry-run"},
        "will_write_files": selected_mode == "execute" and bool(outputs),
        "notes": [
            "Validation checks the recipe contract; domain checks run during dry-run or execute.",
            "Dry-run performs calculations but suppresses all requested file writes.",
        ],
    }


def _write_artifacts(
    spec: WorkflowSpec,
    result: Any,
    result_payload: Any,
    outputs: Mapping[str, str],
) -> tuple[Mapping[str, Any], ...]:
    artifacts: list[Mapping[str, Any]] = []
    method_names = {
        "html": "export_html",
        "pdf": "export_pdf",
        "xlsx": "export_xlsx",
        "excel_directory": "export_excel_compatible",
    }
    for format_name in outputs:
        if (
            format_name != "json"
            and getattr(result, method_names[format_name], None) is None
        ):
            raise AgentNativeError(
                "UNSUPPORTED_OUTPUT",
                f"{spec.id} result cannot export {format_name}",
                suggested_fields=("outputs",),
                details={"supported_outputs": ["json"]},
            )
    for format_name, raw_path in outputs.items():
        target = Path(raw_path)
        if format_name == "json":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(
                    result_payload, indent=2, ensure_ascii=False, sort_keys=True
                ),
                encoding="utf-8",
            )
            artifacts.append({"format": "json", "path": str(target)})
            continue
        method_name = method_names[format_name]
        method = getattr(result, method_name, None)
        written = method(str(target))
        paths = written if isinstance(written, (list, tuple)) else (written,)
        for path in paths:
            artifacts.append({"format": format_name, "path": str(path)})
    return tuple(artifacts)


def run_recipe(recipe: Mapping[str, Any], *, mode: str | None = None) -> RecipeResult:
    """Run one stable recipe contract.

    ``validate-only`` performs structural preflight. ``dry-run`` performs the
    calculation but never writes requested output files. ``execute`` performs
    the calculation and writes only explicitly requested outputs.
    """

    spec, inputs, outputs, selected_mode = _normalize_recipe(recipe, mode)
    plan = validate_recipe(recipe, mode=selected_mode)
    if selected_mode == "validate-only":
        return RecipeResult(spec.id, selected_mode, plan=plan)
    try:
        result = spec.executor(inputs)
    except AgentNativeError:
        raise
    except Exception as exc:
        raise agent_error_from_exception(exc, workflow=spec.id) from exc
    result_payload = _serialize(result)
    try:
        artifacts = (
            _write_artifacts(spec, result, result_payload, outputs)
            if selected_mode == "execute"
            else ()
        )
    except AgentNativeError:
        raise
    except Exception as exc:
        raise agent_error_from_exception(exc, workflow=spec.id) from exc
    if selected_mode == "dry-run" and outputs:
        plan = {**plan, "suppressed_outputs": dict(outputs)}
    return RecipeResult(
        workflow=spec.id,
        mode=selected_mode,
        result=result_payload,
        plan=plan if selected_mode == "dry-run" else None,
        artifacts=artifacts,
    )


def agent_error_from_exception(
    exc: Exception, *, workflow: str | None = None
) -> AgentNativeError:
    """Translate public API exceptions into stable agent error categories."""

    if isinstance(exc, AgentNativeError):
        return exc
    message = str(exc).strip() or exc.__class__.__name__
    lowered = message.casefold()
    details: dict[str, Any] = {"exception_type": exc.__class__.__name__}
    if workflow:
        details["workflow"] = workflow
    if isinstance(exc, MissingInputError):
        return AgentNativeError(
            "MISSING_INPUT",
            message,
            hint="Provide the missing measurement or use a non-strict screening profile.",
            details=details,
        )
    if isinstance(exc, FileNotFoundError):
        return AgentNativeError(
            "FILE_NOT_FOUND",
            message,
            suggested_fields=("path",),
            details=details,
        )
    if isinstance(exc, ImportError):
        return AgentNativeError(
            "OPTIONAL_DEPENDENCY_MISSING",
            message,
            hint="Install the optional extra named in the error message.",
            details=details,
        )
    if isinstance(exc, (ProfileNotFoundError, ProcessTemplateNotFoundError, KeyError)):
        return AgentNativeError(
            "UNKNOWN_REFERENCE",
            message,
            hint="Use capabilities, profiles, processes, or describe to discover valid names.",
            details=details,
        )
    if "absolute mass inputs" in lowered and "explicit energy" in lowered:
        return AgentNativeError(
            "MISSING_ENERGY_BASIS",
            message,
            suggested_fields=("energy", "unit"),
            hint="For a normalized result, use gas_factors_kg_per_mwh or pollutant_factors_kg_per_mwh.",
            details=details,
        )
    if isinstance(exc, (ValueError, TypeError, OSError)):
        return AgentNativeError(
            "INVALID_INPUT",
            message,
            hint="Inspect the workflow input schema and correct the named field.",
            details=details,
        )
    return AgentNativeError(
        "EXECUTION_ERROR",
        message,
        retryable=False,
        details=details,
    )


def error_response(
    exc: Exception,
    *,
    workflow: str | None = None,
    mode: str | None = None,
    command: str | None = None,
) -> dict[str, Any]:
    """Return a complete JSON error envelope for CLI and MCP callers."""

    error = agent_error_from_exception(exc, workflow=workflow)
    payload: dict[str, Any] = {
        "schema_version": AGENT_CONTRACT_VERSION,
        "contract": "exergy-agent-response",
        "ok": False,
        "error": error.to_dict(),
    }
    if workflow:
        payload["workflow"] = workflow
    if mode in RECIPE_MODES:
        payload["mode"] = mode
    if command:
        payload["command"] = command
    return payload


def safe_run_recipe(
    recipe: Mapping[str, Any], *, mode: str | None = None
) -> dict[str, Any]:
    """Run a recipe and always return a success or error JSON envelope."""

    try:
        return run_recipe(recipe, mode=mode).to_dict()
    except Exception as exc:
        workflow = recipe.get("workflow") if isinstance(recipe, Mapping) else None
        return error_response(
            exc,
            workflow=str(workflow) if workflow else None,
            mode=mode or (recipe.get("mode") if isinstance(recipe, Mapping) else None),
        )
