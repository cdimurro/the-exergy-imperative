"""Versioned technology and process packs with provenance validation."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping

from .assessment import assess
from .materials import convert_mass
from .models import Estimate, FidelityTier, Parameter, ValueStatus
from .processes import (
    DEFAULT_PROCESS_CATALOG,
    ProcessAssessment,
    ProcessCatalog,
    assess_process,
)
from .registry import DEFAULT_REGISTRY, Registry, normalize_id
from .technology_models import (
    DEFAULT_TECHNOLOGY_MODEL_REGISTRY,
    TechnologyModelRegistry,
    TechnologyModelSpec,
)
from .technology_models import (
    SUPPORTED_TECHNOLOGY_MODELS as _SUPPORTED_TECHNOLOGY_MODELS,
)
from .units import convert_energy

TECHNOLOGY_PACK_SCHEMA_VERSION = "1.0"
SUPPORTED_TECHNOLOGY_MODELS = _SUPPORTED_TECHNOLOGY_MODELS

_BUNDLED_PACK_FILES: Mapping[str, str] = {
    "buildings": "buildings.json",
    "power": "power.json",
    "mobility": "mobility.json",
    "water-materials": "water_materials.json",
    "oil-gas": "oil_gas.json",
    "emerging-energy": "emerging_energy.json",
    "advanced-materials": "advanced_materials.json",
}


def _nonempty(value: Any, name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


def _finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _validate_parameter(
    name: str,
    spec: Mapping[str, Any],
    *,
    profile_id: str,
    sources: Mapping[str, Any],
) -> None:
    allowed = {
        "value",
        "unit",
        "low",
        "high",
        "confidence",
        "method_id",
        "note",
        "source_id",
        "source_version",
        "evidence_kind",
        "statistic",
        "range_basis",
        "applicability",
        "variants",
    }
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise ValueError(
            f"profile {profile_id!r} parameter {name!r} has unknown fields: "
            + ", ".join(unknown)
        )
    variants = spec.get("variants", ())
    if not isinstance(variants, (list, tuple)):
        raise ValueError(f"parameter {profile_id}.{name} variants must be an array")
    spec = {key: value for key, value in spec.items() if key != "variants"}
    for field_name in ("value", "unit", "confidence"):
        if field_name not in spec:
            raise ValueError(
                f"profile {profile_id!r} parameter {name!r} requires {field_name}"
            )
    value = spec["value"]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        center = _finite(value, f"profile {profile_id!r} parameter {name!r} value")
        confidence = str(spec["confidence"]).strip().lower()
        if confidence not in {"exact", "convention"}:
            if "low" not in spec or "high" not in spec:
                raise ValueError(
                    f"screening parameter {profile_id}.{name} requires low and high"
                )
        if "low" in spec or "high" in spec:
            if "low" not in spec or "high" not in spec:
                raise ValueError(
                    f"parameter {profile_id}.{name} requires both low and high"
                )
            low = _finite(spec["low"], f"parameter {profile_id}.{name} low")
            high = _finite(spec["high"], f"parameter {profile_id}.{name} high")
            if not low <= center <= high:
                raise ValueError(
                    f"parameter {profile_id}.{name} must satisfy low <= value <= high"
                )
    parameter_source = spec.get("source_id")
    if parameter_source is not None and parameter_source not in sources:
        raise ValueError(
            f"parameter {profile_id}.{name} references unknown source "
            f"{parameter_source!r}"
        )
    if spec.get("evidence_kind") == "published_estimate":
        for field_name in (
            "source_id",
            "source_version",
            "statistic",
            "range_basis",
            "applicability",
            "low",
            "high",
        ):
            if field_name not in spec:
                raise ValueError(
                    f"published estimate {profile_id}.{name} requires {field_name}"
                )
        for field_name in ("source_id", "source_version", "statistic", "range_basis"):
            _nonempty(spec[field_name], f"parameter {profile_id}.{name} {field_name}")
        applicability = spec["applicability"]
        if not isinstance(applicability, Mapping):
            raise ValueError(
                f"parameter {profile_id}.{name} applicability must be an object"
            )
        for field_name in ("technology", "boundary", "geography", "vintage"):
            if field_name not in applicability:
                raise ValueError(
                    f"parameter {profile_id}.{name} applicability requires {field_name}"
                )
            _nonempty(
                applicability[field_name],
                f"parameter {profile_id}.{name} applicability {field_name}",
            )
    variant_ids: set[str] = set()
    variant_allowed = allowed - {"variants"} | {"id", "when", "priority"}
    for raw_variant in variants:
        if not isinstance(raw_variant, Mapping):
            raise ValueError(f"parameter {profile_id}.{name} variant must be an object")
        variant_unknown = sorted(set(raw_variant) - variant_allowed)
        if variant_unknown:
            raise ValueError(
                f"parameter {profile_id}.{name} variant has unknown fields: "
                + ", ".join(variant_unknown)
            )
        variant_id = _nonempty(
            raw_variant.get("id"), f"parameter {profile_id}.{name} variant id"
        )
        if variant_id in variant_ids:
            raise ValueError(
                f"parameter {profile_id}.{name} has duplicate variant {variant_id!r}"
            )
        variant_ids.add(variant_id)
        when = raw_variant.get("when")
        if not isinstance(when, Mapping) or not when:
            raise ValueError(
                f"parameter {profile_id}.{name} variant {variant_id!r} requires "
                "a non-empty when object"
            )
        for context_name, condition in when.items():
            _nonempty(context_name, "variant context field")
            if not isinstance(condition, Mapping):
                continue
            unknown_operators = sorted(
                set(condition) - {"eq", "in", "gt", "gte", "lt", "lte"}
            )
            if unknown_operators:
                raise ValueError(
                    f"parameter {profile_id}.{name} variant {variant_id!r} has "
                    "unknown condition operators: " + ", ".join(unknown_operators)
                )
            if "in" in condition and not isinstance(condition["in"], (list, tuple)):
                raise ValueError(
                    f"parameter {profile_id}.{name} variant {variant_id!r} "
                    "condition 'in' must be an array"
                )
            for operator in ("gt", "gte", "lt", "lte"):
                if operator in condition:
                    _finite(
                        condition[operator],
                        f"parameter {profile_id}.{name} variant condition {operator}",
                    )
        if "priority" in raw_variant:
            _finite(raw_variant["priority"], f"variant {variant_id!r} priority")
        merged = dict(spec)
        merged.update(
            {
                key: value
                for key, value in raw_variant.items()
                if key not in {"id", "when", "priority"}
            }
        )
        _validate_parameter(name, merged, profile_id=profile_id, sources=sources)


def _validate_sources(sources: Mapping[str, Any]) -> None:
    for source_id, raw in sources.items():
        _nonempty(source_id, "source id")
        if not isinstance(raw, Mapping):
            raise ValueError(f"source {source_id!r} must be an object")
        missing = {
            "title",
            "license",
            "applicable_boundary",
        } - set(raw)
        if missing:
            raise ValueError(
                f"source {source_id!r} is missing: " + ", ".join(sorted(missing))
            )
        for field_name in ("title", "license", "applicable_boundary"):
            _nonempty(raw[field_name], f"source {source_id!r} {field_name}")


def _validate_profiles(
    profiles: Mapping[str, Any],
    sources: Mapping[str, Any],
    model_registry: TechnologyModelRegistry,
) -> None:
    allowed_categories = {
        "reference",
        "carrier",
        "service",
        "technology",
        "intensity",
    }
    unknown_categories = sorted(set(profiles) - allowed_categories)
    if unknown_categories:
        raise ValueError("unknown profile categories: " + ", ".join(unknown_categories))
    seen: set[tuple[str, str]] = set()
    for category, records in profiles.items():
        if not isinstance(records, (list, tuple)):
            raise ValueError(f"profile category {category!r} must be an array")
        for raw in records:
            if not isinstance(raw, Mapping):
                raise ValueError(f"{category} profile must be an object")
            profile_id = normalize_id(
                _nonempty(raw.get("id"), f"{category} profile id")
            )
            key = (category, profile_id)
            if key in seen:
                raise ValueError(f"duplicate {category} profile {profile_id!r}")
            seen.add(key)
            _nonempty(raw.get("label", raw.get("id")), f"profile {profile_id!r} label")
            source_id = _nonempty(
                raw.get("source_id"), f"profile {profile_id!r} source_id"
            )
            if source_id not in sources:
                raise ValueError(
                    f"profile {profile_id!r} references unknown source {source_id!r}"
                )
            source_boundary = sources[source_id].get("applicable_boundary")
            if not raw.get("boundary") and not source_boundary:
                raise ValueError(
                    f"profile {profile_id!r} requires an applicable boundary"
                )
            parameters = raw.get("parameters", {})
            if not isinstance(parameters, Mapping):
                raise ValueError(f"profile {profile_id!r} parameters must be an object")
            for name, spec in parameters.items():
                if not isinstance(spec, Mapping):
                    raise ValueError(
                        f"profile {profile_id!r} parameter {name!r} must be an object"
                    )
                _validate_parameter(
                    str(name), spec, profile_id=profile_id, sources=sources
                )
            if category == "technology":
                model = str(raw.get("model", "converter"))
                try:
                    model_spec = model_registry.get(model)
                except KeyError as exc:
                    raise ValueError(str(exc)) from exc
                performance = raw.get("performance_parameter")
                if performance != model_spec.performance_parameter:
                    raise ValueError(
                        f"technology {profile_id!r} performance_parameter must be "
                        f"{model_spec.performance_parameter!r} for model {model_spec.id!r}"
                    )
                if performance not in parameters:
                    required_inputs = tuple(raw.get("required_inputs", ()))
                    if performance not in required_inputs:
                        raise ValueError(
                            f"technology {profile_id!r} must provide {performance!r} "
                            "or list it in required_inputs"
                        )
                else:
                    spec = parameters[performance]
                    if isinstance(spec.get("value"), (int, float)) and not isinstance(
                        spec.get("value"), bool
                    ):
                        model_spec.validate_performance(spec["value"])
                        if spec.get("high") is not None:
                            model_spec.validate_performance(spec["high"])
            if category == "intensity":
                for field_name in (
                    "technology",
                    "energy_carrier",
                    "output_material",
                    "boundary",
                ):
                    _nonempty(
                        raw.get(field_name),
                        f"intensity profile {profile_id!r} {field_name}",
                    )
                specific_energy = parameters.get("specific_energy")
                if not isinstance(specific_energy, Mapping):
                    raise ValueError(
                        f"intensity profile {profile_id!r} requires specific_energy"
                    )
                unit = str(specific_energy.get("unit", "")).lower().replace(" ", "")
                if unit not in {"mwh/t", "mwh/tonne"}:
                    raise ValueError(
                        f"intensity profile {profile_id!r} specific_energy unit must "
                        "be MWh/t or MWh/tonne"
                    )
                for field_name in ("value", "low", "high"):
                    if (
                        field_name in specific_energy
                        and _finite(
                            specific_energy[field_name],
                            f"intensity profile {profile_id!r} {field_name}",
                        )
                        <= 0.0
                    ):
                        raise ValueError(
                            f"intensity profile {profile_id!r} {field_name} must be positive"
                        )


@dataclass(frozen=True)
class PerformanceAssessment:
    """Energy-performance screen that makes no unstated exergy assumptions."""

    technology: str
    model: str
    input_carrier: str
    output_carrier: str
    input_energy: Estimate
    performance_parameter: str
    performance: Parameter
    output_energy: Estimate
    boundary: str
    tier: FidelityTier
    warnings: tuple[str, ...]
    source_catalog: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "model": "technology-energy-performance",
            "technology": self.technology,
            "technology_model": self.model,
            "input_carrier": self.input_carrier,
            "output_carrier": self.output_carrier,
            "input_energy": self.input_energy.to_dict(),
            "performance_parameter": self.performance_parameter,
            "performance": self.performance.to_dict(),
            "output_energy": self.output_energy.to_dict(),
            "boundary": self.boundary,
            "tier": self.tier.value,
            "warnings": list(self.warnings),
            "source_catalog": {
                key: dict(value) for key, value in self.source_catalog.items()
            },
        }


@dataclass(frozen=True)
class IntensityAssessment:
    """Mass-normalized energy estimate kept separate from efficiency."""

    technology: str
    output_material: str
    output_mass: Estimate
    energy_carrier: str
    specific_energy: Parameter
    input_energy: Estimate
    boundary: str
    tier: FidelityTier
    warnings: tuple[str, ...]
    source_catalog: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "model": "mass-normalized-energy-intensity",
            "technology": self.technology,
            "output_material": self.output_material,
            "output_mass": self.output_mass.to_dict(),
            "energy_carrier": self.energy_carrier,
            "specific_energy": self.specific_energy.to_dict(),
            "input_energy": self.input_energy.to_dict(),
            "boundary": self.boundary,
            "tier": self.tier.value,
            "warnings": list(self.warnings),
            "source_catalog": {
                key: dict(value) for key, value in self.source_catalog.items()
            },
        }


@dataclass(frozen=True)
class TechnologyPack:
    """A validated, local extension of profiles and process templates."""

    id: str
    version: str
    license: str
    description: str
    domains: tuple[str, ...]
    sources: Mapping[str, Mapping[str, Any]]
    profiles: Mapping[str, tuple[Mapping[str, Any], ...]]
    process_templates: tuple[Mapping[str, Any], ...] = ()
    material_templates: tuple[Mapping[str, Any], ...] = ()
    technology_models: tuple[TechnologyModelSpec, ...] = ()
    schema_version: str = TECHNOLOGY_PACK_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TechnologyPack":
        allowed = {
            "schema_version",
            "id",
            "version",
            "license",
            "description",
            "domains",
            "sources",
            "profiles",
            "process_templates",
            "material_templates",
            "technology_models",
            "metadata",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError("unknown technology-pack fields: " + ", ".join(unknown))
        schema_version = str(payload.get("schema_version", ""))
        if schema_version != TECHNOLOGY_PACK_SCHEMA_VERSION:
            raise ValueError(
                f"technology-pack schema_version must be {TECHNOLOGY_PACK_SCHEMA_VERSION!r}"
            )
        pack_id = normalize_id(_nonempty(payload.get("id"), "technology-pack id"))
        version = _nonempty(payload.get("version"), "technology-pack version")
        license_name = _nonempty(payload.get("license"), "technology-pack license")
        description = _nonempty(
            payload.get("description"), "technology-pack description"
        )
        domains_raw = payload.get("domains", ())
        if not isinstance(domains_raw, (list, tuple)) or not domains_raw:
            raise ValueError("technology-pack domains must be a non-empty array")
        domains = tuple(
            _nonempty(item, "technology-pack domain") for item in domains_raw
        )
        sources = payload.get("sources", {})
        if not isinstance(sources, Mapping) or not sources:
            raise ValueError("technology-pack sources must be a non-empty object")
        _validate_sources(sources)
        models_raw = payload.get("technology_models", ())
        if not isinstance(models_raw, (list, tuple)):
            raise ValueError("technology-pack technology_models must be an array")
        technology_model_items: list[TechnologyModelSpec] = []
        for item in models_raw:
            if not isinstance(item, Mapping):
                raise ValueError("technology-model definition must be an object")
            technology_model_items.append(TechnologyModelSpec.from_dict(item))
        technology_models = tuple(technology_model_items)
        model_registry = DEFAULT_TECHNOLOGY_MODEL_REGISTRY.with_models(
            technology_models
        )
        profiles = payload.get("profiles", {})
        if not isinstance(profiles, Mapping) or not profiles:
            raise ValueError("technology-pack profiles must be a non-empty object")
        _validate_profiles(profiles, sources, model_registry)
        process_templates = payload.get("process_templates", ())
        if not isinstance(process_templates, (list, tuple)):
            raise ValueError("technology-pack process_templates must be an array")
        normalized_templates: list[Mapping[str, Any]] = []
        for raw in process_templates:
            if not isinstance(raw, Mapping):
                raise ValueError("process template must be an object")
            source_id = _nonempty(raw.get("source_id"), "process-template source_id")
            if source_id not in sources:
                raise ValueError(
                    f"process template references unknown source {source_id!r}"
                )
            normalized_templates.append(dict(raw))
        # Reuse the process engine's range and alias validation.
        ProcessCatalog.from_payload(
            {
                "data_version": version,
                "process_templates": normalized_templates,
            }
        )
        material_templates_raw = payload.get("material_templates", ())
        if not isinstance(material_templates_raw, (list, tuple)):
            raise ValueError("technology-pack material_templates must be an array")
        material_templates: list[Mapping[str, Any]] = []
        material_ids: set[str] = set()
        for raw in material_templates_raw:
            if not isinstance(raw, Mapping):
                raise ValueError("material template must be an object")
            missing = {"id", "label", "source_id", "boundary", "required_inputs"} - set(
                raw
            )
            if missing:
                raise ValueError(
                    "material template is missing: " + ", ".join(sorted(missing))
                )
            material_id = normalize_id(_nonempty(raw["id"], "material-template id"))
            if material_id in material_ids:
                raise ValueError(f"duplicate material template {material_id!r}")
            material_ids.add(material_id)
            source_id = _nonempty(raw["source_id"], "material-template source_id")
            if source_id not in sources:
                raise ValueError(
                    f"material template {material_id!r} references unknown source {source_id!r}"
                )
            _nonempty(raw["label"], f"material template {material_id!r} label")
            _nonempty(raw["boundary"], f"material template {material_id!r} boundary")
            required_inputs = raw["required_inputs"]
            if not isinstance(required_inputs, (list, tuple)) or not required_inputs:
                raise ValueError(
                    f"material template {material_id!r} required_inputs must be a non-empty array"
                )
            material_templates.append(dict(raw))
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise ValueError("technology-pack metadata must be an object")
        return cls(
            id=pack_id,
            version=version,
            license=license_name,
            description=description,
            domains=domains,
            sources={str(key): dict(value) for key, value in sources.items()},
            profiles={
                str(category): tuple(dict(item) for item in records)
                for category, records in profiles.items()
            },
            process_templates=tuple(normalized_templates),
            material_templates=tuple(material_templates),
            technology_models=technology_models,
            schema_version=schema_version,
            metadata=dict(metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "version": self.version,
            "license": self.license,
            "description": self.description,
            "domains": list(self.domains),
            "sources": {key: dict(value) for key, value in self.sources.items()},
            "profiles": {
                category: [dict(item) for item in records]
                for category, records in self.profiles.items()
            },
            "process_templates": [dict(item) for item in self.process_templates],
            "material_templates": [dict(item) for item in self.material_templates],
            "technology_models": [item.to_dict() for item in self.technology_models],
            "metadata": dict(self.metadata),
        }

    def summary(self) -> dict[str, Any]:
        published_prior_count = sum(
            1
            for records in self.profiles.values()
            for profile in records
            for parameter in profile.get("parameters", {}).values()
            if parameter.get("evidence_kind") == "published_estimate"
        )
        technologies = {
            normalize_id(str(profile["id"]))
            for profile in self.profiles.get("technology", ())
        }
        performance_defaults = {
            normalize_id(str(profile["id"]))
            for profile in self.profiles.get("technology", ())
            if profile.get("performance_parameter") in profile.get("parameters", {})
        }
        intensity_defaults = {
            normalize_id(str(profile.get("technology", profile["id"])))
            for profile in self.profiles.get("intensity", ())
            if "specific_energy" in profile.get("parameters", {})
        }
        automatic = performance_defaults | intensity_defaults
        return {
            "id": self.id,
            "version": self.version,
            "license": self.license,
            "description": self.description,
            "domains": list(self.domains),
            "profile_count": sum(len(items) for items in self.profiles.values()),
            "process_template_count": len(self.process_templates),
            "material_template_count": len(self.material_templates),
            "technology_model_count": len(self.technology_models),
            "published_prior_count": published_prior_count,
            "intensity_model_count": len(self.profiles.get("intensity", ())),
            "technology_coverage": {
                "technology_count": len(technologies),
                "performance_prior_count": len(performance_defaults),
                "intensity_prior_count": len(intensity_defaults),
                "automatic_estimate_count": len(automatic),
                "explicit_input_count": len(technologies - automatic),
                "automatic_estimate_fraction": (
                    len(automatic) / len(technologies) if technologies else 0.0
                ),
            },
        }

    def coverage(self) -> tuple[Mapping[str, Any], ...]:
        """Describe the safest available calculation path for every technology.

        A technology is automatic only when the pack contains a compatible,
        sourced performance or mass-normalized intensity prior.  Other entries
        remain discoverable, but explicitly require caller data.
        """

        intensities: dict[str, list[Mapping[str, Any]]] = {}
        for profile in self.profiles.get("intensity", ()):
            technology_id = normalize_id(str(profile["technology"]))
            intensities.setdefault(technology_id, []).append(profile)

        entries: list[Mapping[str, Any]] = []
        for profile in self.profiles.get("technology", ()):
            technology_id = normalize_id(str(profile["id"]))
            parameter_name = profile.get("performance_parameter")
            parameters = profile.get("parameters", {})
            performance = (
                parameters.get(parameter_name) if parameter_name is not None else None
            )
            available: list[dict[str, Any]] = []
            if isinstance(performance, Mapping):
                available.append(
                    {
                        "kind": "performance",
                        "parameter": str(parameter_name),
                        "unit": performance.get("unit"),
                        "source_id": performance.get(
                            "source_id", profile.get("source_id")
                        ),
                        "context_fields": sorted(
                            {
                                str(field)
                                for variant in performance.get("variants", ())
                                for field in variant.get("when", {})
                            }
                        ),
                    }
                )
            for intensity in intensities.get(technology_id, ()):
                specific_energy = intensity.get("parameters", {}).get("specific_energy")
                if not isinstance(specific_energy, Mapping):
                    continue
                available.append(
                    {
                        "kind": "mass_normalized_intensity",
                        "profile": str(intensity["id"]),
                        "output_material": str(intensity["output_material"]),
                        "energy_carrier": str(intensity["energy_carrier"]),
                        "unit": specific_energy.get("unit"),
                        "source_id": specific_energy.get(
                            "source_id", intensity.get("source_id")
                        ),
                        "context_fields": sorted(
                            {
                                str(field)
                                for variant in specific_energy.get("variants", ())
                                for field in variant.get("when", {})
                            }
                        ),
                    }
                )
            required_inputs = [str(item) for item in profile.get("required_inputs", ())]
            automatic = bool(available)
            reason = profile.get("default_unavailable_reason")
            if not automatic and not reason:
                listed = ", ".join(required_inputs) or "boundary-specific performance"
                reason = (
                    "No boundary-compatible published prior is bundled; explicit "
                    f"inputs are required for {listed}."
                )
            entries.append(
                {
                    "technology": technology_id,
                    "label": str(profile["label"]),
                    "status": (
                        "automatic_screening_estimate"
                        if automatic
                        else "explicit_inputs_required"
                    ),
                    "boundary": str(profile["boundary"]),
                    "available_estimates": available,
                    "required_inputs": required_inputs,
                    "recommended_overrides": [
                        str(item) for item in profile.get("recommended_overrides", ())
                    ],
                    "reason": None if automatic else str(reason),
                }
            )
        return tuple(entries)

    def registry(self, base: Registry | None = None) -> Registry:
        registry = base or DEFAULT_REGISTRY
        return registry.with_payload(
            {
                "data_version": self.version,
                "license": self.license,
                "sources": self.sources,
                "profiles": self.profiles,
            }
        )

    def process_catalog(
        self, base: ProcessCatalog | None = None, *, registry: Registry | None = None
    ) -> ProcessCatalog:
        catalog = base or DEFAULT_PROCESS_CATALOG
        result = catalog.with_payload(
            {
                "data_version": self.version,
                "process_templates": self.process_templates,
            }
        )
        combined_registry = registry or self.registry()
        for template in result.list():
            if template.id in {str(item.get("id")) for item in self.process_templates}:
                combined_registry.get("technology", template.technology)
        return result

    def model_registry(self) -> TechnologyModelRegistry:
        """Return built-in model contracts overlaid by this pack."""

        return DEFAULT_TECHNOLOGY_MODEL_REGISTRY.with_models(self.technology_models)


def list_bundled_technology_packs() -> tuple[str, ...]:
    """Return stable names for the bundled data-only starter packs."""

    return tuple(_BUNDLED_PACK_FILES)


def _load_bundled_payload(name: str) -> Mapping[str, Any]:
    key = normalize_id(name)
    filename = _BUNDLED_PACK_FILES.get(key)
    if filename is None:
        raise KeyError(
            f"unknown bundled technology pack {name!r}; available packs: "
            + ", ".join(_BUNDLED_PACK_FILES)
        )
    resource = files("exergy_imperative").joinpath("data", "packs", filename)
    return json.loads(resource.read_text(encoding="utf-8"))


def load_technology_pack(
    source: TechnologyPack | Mapping[str, Any] | str | Path,
) -> TechnologyPack:
    """Load a pack from an object, explicit local path, or bundled stable name."""

    if isinstance(source, TechnologyPack):
        return source
    if isinstance(source, Mapping):
        return TechnologyPack.from_dict(source)
    path = Path(source)
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = _load_bundled_payload(str(source))
    if not isinstance(payload, Mapping):
        raise ValueError("technology pack must be a JSON object")
    return TechnologyPack.from_dict(payload)


def bundled_technology_pack_info() -> tuple[Mapping[str, Any], ...]:
    return tuple(load_technology_pack(name).summary() for name in _BUNDLED_PACK_FILES)


def technology_pack_coverage(
    source: TechnologyPack | Mapping[str, Any] | str | Path,
) -> dict[str, Any]:
    """Return per-technology default availability without running calculations."""

    pack = load_technology_pack(source)
    entries = pack.coverage()
    automatic_count = sum(
        item["status"] == "automatic_screening_estimate" for item in entries
    )
    return {
        "schema_version": "1.0",
        "pack": pack.summary(),
        "coverage": list(entries),
        "automatic_estimate_count": automatic_count,
        "explicit_input_count": len(entries) - automatic_count,
        "warnings": [
            "Automatic values are sourced F1 screening estimates, not measurements or site-specific designs.",
            "Use the declared boundary and applicability before calculation, and replace priors with site or vendor data when available.",
        ],
    }


def validate_technology_pack(
    source: TechnologyPack | Mapping[str, Any] | str | Path,
) -> dict[str, Any]:
    pack = load_technology_pack(source)
    registry = pack.registry()
    for raw in pack.profiles.get("technology", ()):
        technology_id = str(raw["id"])
        for field_name, category in (
            ("input_carrier", "carrier"),
            ("output_carrier", "carrier"),
            ("default_service", "service"),
        ):
            value = raw.get(field_name)
            if value is None:
                continue
            try:
                registry.get(category, str(value))
            except KeyError as exc:
                raise ValueError(
                    f"technology {technology_id!r} references unknown "
                    f"{field_name} {value!r}"
                ) from exc
    technology_ids = {
        normalize_id(str(item["id"])) for item in pack.profiles.get("technology", ())
    }
    for raw in pack.profiles.get("intensity", ()):
        technology_id = normalize_id(str(raw["technology"]))
        if technology_id not in technology_ids:
            raise ValueError(
                f"intensity profile {raw['id']!r} references unknown technology "
                f"{raw['technology']!r}"
            )
    catalog = pack.process_catalog(registry=registry)
    return {
        "valid": True,
        "pack": pack.summary(),
        "profile_categories": sorted(pack.profiles),
        "combined_profile_count": len(registry.list()),
        "combined_process_template_count": len(catalog.list()),
        "technology_model_count": len(pack.model_registry().list()),
        "material_template_count": len(pack.material_templates),
        "intensity_model_count": len(pack.profiles.get("intensity", ())),
        "warnings": [
            "Pack validation checks structure and provenance, not site performance.",
            *(
                [
                    "Published performance defaults are F1 screening estimates with "
                    "declared applicability; override them with site data or use strict mode."
                ]
                if pack.summary()["published_prior_count"]
                else []
            ),
            "Profiles without performance defaults require explicit user inputs.",
        ],
    }


def technology_pack_template() -> dict[str, Any]:
    """Return a safe scaffold with no invented performance default."""

    return {
        "schema_version": TECHNOLOGY_PACK_SCHEMA_VERSION,
        "id": "my-technology-pack",
        "version": "1.0.0",
        "license": "Proprietary or replace with an SPDX identifier",
        "description": "Organization-specific technology definitions.",
        "domains": ["replace-with-domain"],
        "sources": {
            "my-engineering-source": {
                "title": "Replace with a test report, datasheet, or publication",
                "license": "Replace with applicable source terms",
                "applicable_boundary": "Replace with the exact equipment boundary",
                "note": "This scaffold intentionally contains no performance value.",
            }
        },
        "profiles": {
            "technology": [
                {
                    "id": "my-converter",
                    "label": "My converter",
                    "aliases": [],
                    "model": "converter",
                    "input_carrier": "electricity",
                    "output_carrier": "shaft-work",
                    "performance_parameter": "efficiency",
                    "required_inputs": ["efficiency"],
                    "source_id": "my-engineering-source",
                    "boundary": "Replace with the exact equipment boundary",
                    "parameters": {},
                }
            ]
        },
        "technology_models": [],
        "material_templates": [],
        "process_templates": [],
        "metadata": {},
    }


def write_technology_pack_template(path: str | Path) -> Path:
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing file {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(technology_pack_template(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def assess_with_pack(
    pack: TechnologyPack | Mapping[str, Any] | str | Path,
    **inputs: Any,
) -> Any:
    """Run the standard assessment engine against one explicitly loaded pack."""

    definition = load_technology_pack(pack)
    technology = inputs.get("technology")
    if technology is not None:
        profile = definition.registry().get("technology", str(technology))
        model = definition.model_registry().get(
            str(profile.metadata.get("model", "converter"))
        )
        performance = inputs.get("performance")
        if performance is None:
            performance = inputs.get(model.performance_parameter)
        if performance is not None:
            model.validate_performance(performance)
    return assess(**inputs, registry=definition.registry())


def assess_performance_with_pack(
    pack: TechnologyPack | Mapping[str, Any] | str | Path,
    technology: str,
    input_energy: float,
    *,
    unit: str = "MWh",
    performance: float | None = None,
    estimate_context: Mapping[str, Any] | None = None,
    strict: bool = False,
) -> PerformanceAssessment:
    """Estimate energy output without silently estimating exergy quality.

    This path is appropriate when a sourced efficiency or COP is available but
    temperatures, composition, or another exergy-quality input is not.
    """

    definition = load_technology_pack(pack)
    registry = definition.registry()
    profile = registry.get("technology", technology)
    model_name = str(profile.metadata.get("model", "converter"))
    model = definition.model_registry().get(model_name)
    parameter_name = str(
        profile.metadata.get("performance_parameter", model.performance_parameter)
    )
    energy = _finite(input_energy, "input_energy")
    if energy < 0.0:
        raise ValueError("input_energy must be nonnegative")
    convert_energy(energy, unit, unit)
    context = dict(estimate_context or {})
    for key, value in context.items():
        _nonempty(key, "estimate_context field")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            _finite(value, f"estimate_context[{key!r}]")

    default_parameter = profile.parameter(parameter_name, context=context)
    if performance is None:
        parameter = default_parameter
        if parameter is None:
            raise ValueError(
                f"technology {profile.id!r} has no published {parameter_name} "
                "default; provide performance"
            )
        if strict:
            raise ValueError(
                f"strict mode rejects the published {parameter_name} estimate; "
                "provide performance"
            )
    else:
        value = _finite(performance, "performance")
        parameter = Parameter(
            value=value,
            unit=str(default_parameter.unit if default_parameter else parameter_name),
            status=ValueStatus.PROVIDED,
            confidence="user-provided",
            note="Caller override; applicability and measurement status were not inferred.",
        )
    model.validate_performance(parameter.value)
    value = _finite(parameter.value, parameter_name)
    low = float(parameter.low) if parameter.low is not None else value
    high = float(parameter.high) if parameter.high is not None else value
    output = Estimate(
        value=energy * value,
        unit=unit,
        low=energy * low,
        high=energy * high,
        confidence=parameter.confidence,
    )
    warnings = [
        "Energy-performance screening result; it is not a measurement or site-specific design guarantee.",
        "No exergy, emissions, pollutant exposure, or economics result is implied; calculate those with their own boundary-compatible inputs.",
    ]
    if parameter_name == "cop":
        warnings.append(
            "COP output can exceed the supplied input energy because source or ambient heat crosses the system boundary; this result is not a complete energy balance."
        )
    if parameter.status == ValueStatus.PUBLISHED_ESTIMATE:
        warnings.append(
            f"Using published F1 {parameter_name} estimate from {parameter.source_id}; "
            "provide performance or use strict mode when it is not applicable."
        )
    elif parameter.status != ValueStatus.PROVIDED:
        warnings.append(
            f"Using an F1 pack {parameter_name} default from {parameter.source_id}; "
            "provide performance or use strict mode when it is not applicable."
        )
    if parameter.selection_basis == "family_fallback":
        warnings.append(
            "No conditional performance variant matched; using the documented family fallback. Available context fields: "
            + ", ".join(parameter.available_context or ())
            + "."
        )
    elif parameter.selection_basis == "conditional_context":
        warnings.append(
            f"Selected conditional performance variant {parameter.estimate_variant!r}."
        )
    source_catalog = (
        {parameter.source_id: definition.sources[parameter.source_id]}
        if parameter.source_id in definition.sources
        else {}
    )
    return PerformanceAssessment(
        technology=profile.id,
        model=model_name,
        input_carrier=str(profile.metadata.get("input_carrier", "unspecified")),
        output_carrier=str(profile.metadata.get("output_carrier", "unspecified")),
        input_energy=Estimate(value=energy, unit=unit),
        performance_parameter=parameter_name,
        performance=parameter,
        output_energy=output,
        boundary=str(profile.metadata["boundary"]),
        tier=(
            FidelityTier.F2
            if parameter.status == ValueStatus.PROVIDED
            else FidelityTier.F1
        ),
        warnings=tuple(warnings),
        source_catalog=source_catalog,
    )


def assess_process_with_pack(
    pack: TechnologyPack | Mapping[str, Any] | str | Path,
    template: str,
    energy: float | None = None,
    **options: Any,
) -> ProcessAssessment:
    """Run an integrated process assessment against one explicitly loaded pack."""

    definition = load_technology_pack(pack)
    registry = definition.registry()
    catalog = definition.process_catalog(registry=registry)
    return assess_process(
        template,
        energy,
        registry=registry,
        catalog=catalog,
        **options,
    )


def assess_intensity_with_pack(
    pack: TechnologyPack | Mapping[str, Any] | str | Path,
    technology: str,
    output_mass: float,
    *,
    output_unit: str = "t",
    specific_energy_mwh_per_tonne: float | None = None,
    estimate_context: Mapping[str, Any] | None = None,
    strict: bool = False,
) -> IntensityAssessment:
    """Estimate input energy from a published mass-normalized process intensity.

    This result intentionally does not report useful energy or exergy efficiency.
    It assumes linear scaling over the cited process and product boundary.
    """

    definition = load_technology_pack(pack)
    profile = definition.registry().get("intensity", technology)
    mass = _finite(output_mass, "output_mass")
    if mass <= 0.0:
        raise ValueError("output_mass must be positive")
    tonnes = convert_mass(mass, output_unit, "t")
    context = dict(estimate_context or {})
    for key, value in context.items():
        _nonempty(key, "estimate_context field")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            _finite(value, f"estimate_context[{key!r}]")

    if specific_energy_mwh_per_tonne is None:
        parameter = profile.parameter("specific_energy", context=context)
        if parameter is None:  # guarded by pack validation
            raise ValueError(f"intensity profile {profile.id!r} has no default")
        if strict:
            raise ValueError(
                "strict mode rejects the published specific-energy estimate; "
                "provide specific_energy_mwh_per_tonne"
            )
    else:
        value = _finite(specific_energy_mwh_per_tonne, "specific_energy_mwh_per_tonne")
        if value <= 0.0:
            raise ValueError("specific_energy_mwh_per_tonne must be positive")
        parameter = Parameter(
            value=value,
            unit="MWh/t",
            status=ValueStatus.PROVIDED,
            confidence="user-provided",
            note="Caller override; applicability and measurement status were not inferred.",
        )

    value = _finite(parameter.value, "specific_energy")
    low = float(parameter.low) if parameter.low is not None else value
    high = float(parameter.high) if parameter.high is not None else value
    energy = Estimate(
        value=tonnes * value,
        unit="MWh",
        low=tonnes * low,
        high=tonnes * high,
        confidence=parameter.confidence,
    )
    warnings = [
        "Mass-normalized screening estimate; it is not a site measurement, design guarantee, or conversion efficiency.",
        "Input energy scales linearly with declared product mass over the cited boundary; yield, utilization, and product specification must match the source or be overridden.",
        "No useful-energy, exergy-efficiency, emissions, pollutant exposure, or economics result is implied.",
    ]
    if parameter.status == ValueStatus.PUBLISHED_ESTIMATE:
        warnings.append(
            f"Using published F1 specific-energy estimate from {parameter.source_id}; "
            "provide specific_energy_mwh_per_tonne or use strict mode when it is not applicable."
        )
    elif parameter.status != ValueStatus.PROVIDED:
        warnings.append(
            f"Using an F1 pack specific-energy default from {parameter.source_id}; "
            "provide specific_energy_mwh_per_tonne or use strict mode when it is not applicable."
        )
    if parameter.selection_basis == "family_fallback":
        warnings.append(
            "No conditional intensity variant matched; using the documented family fallback. "
            "Available context fields: "
            + ", ".join(parameter.available_context or ())
            + "."
        )
    elif parameter.selection_basis == "conditional_context":
        warnings.append(
            f"Selected conditional intensity variant {parameter.estimate_variant!r}."
        )
    source_catalog = (
        {parameter.source_id: definition.sources[parameter.source_id]}
        if parameter.source_id in definition.sources
        else {}
    )
    return IntensityAssessment(
        technology=normalize_id(str(profile.metadata["technology"])),
        output_material=str(profile.metadata["output_material"]),
        output_mass=Estimate(value=mass, unit=output_unit),
        energy_carrier=str(profile.metadata["energy_carrier"]),
        specific_energy=parameter,
        input_energy=energy,
        boundary=str(profile.metadata["boundary"]),
        tier=(
            FidelityTier.F2
            if parameter.status == ValueStatus.PROVIDED
            else FidelityTier.F1
        ),
        warnings=tuple(warnings),
        source_catalog=source_catalog,
    )
