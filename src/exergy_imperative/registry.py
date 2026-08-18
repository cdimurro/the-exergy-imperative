"""Versioned, inspectable profiles used to fill optional inputs."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from difflib import get_close_matches
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping

from .models import Parameter, ValueStatus


class ProfileNotFoundError(KeyError):
    """Raised when a requested profile or alias is unknown."""


def normalize_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def _context_equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, str) and isinstance(expected, str):
        return normalize_id(actual) == normalize_id(expected)
    return actual == expected


def _condition_matches(actual: Any, condition: Any) -> bool:
    if not isinstance(condition, Mapping):
        return _context_equal(actual, condition)
    if "in" in condition:
        values = condition["in"]
        if not isinstance(values, (list, tuple)):
            return False
        if not any(_context_equal(actual, item) for item in values):
            return False
    if "eq" in condition and not _context_equal(actual, condition["eq"]):
        return False
    comparisons = {
        "gt": lambda value, limit: value > limit,
        "gte": lambda value, limit: value >= limit,
        "lt": lambda value, limit: value < limit,
        "lte": lambda value, limit: value <= limit,
    }
    for operator, compare in comparisons.items():
        if operator not in condition:
            continue
        try:
            value = float(actual)
            limit = float(condition[operator])
        except (TypeError, ValueError, OverflowError):
            return False
        if (
            not math.isfinite(value)
            or not math.isfinite(limit)
            or not compare(value, limit)
        ):
            return False
    return True


def _select_parameter_spec(
    spec: Mapping[str, Any], context: Mapping[str, Any] | None
) -> tuple[dict[str, Any], str | None, tuple[str, ...]]:
    variants = spec.get("variants", ())
    if not isinstance(variants, (list, tuple)) or not variants:
        return dict(spec), None, ()
    context_fields = tuple(
        sorted(
            {
                str(field_name)
                for variant in variants
                if isinstance(variant, Mapping)
                for field_name in variant.get("when", {})
            }
        )
    )
    matches: list[tuple[float, int, Mapping[str, Any]]] = []
    supplied = context or {}
    for index, variant in enumerate(variants):
        when = variant.get("when", {})
        if not isinstance(when, Mapping) or not all(
            field in supplied and _condition_matches(supplied[field], condition)
            for field, condition in when.items()
        ):
            continue
        priority = float(variant.get("priority", len(when)))
        matches.append((priority, -index, variant))
    selected = max(matches, default=None, key=lambda item: (item[0], item[1]))
    base = {key: value for key, value in spec.items() if key != "variants"}
    if selected is None:
        return base, "family_fallback", context_fields
    variant = selected[2]
    variant_id = str(variant["id"])
    base.update(
        {
            key: value
            for key, value in variant.items()
            if key not in {"id", "when", "priority"}
        }
    )
    return base, variant_id, context_fields


@dataclass(frozen=True)
class Profile:
    category: str
    id: str
    label: str
    aliases: tuple[str, ...]
    source_id: str
    parameters: Mapping[str, Mapping[str, Any]]
    metadata: Mapping[str, Any]

    def parameter(
        self,
        name: str,
        *,
        status: ValueStatus = ValueStatus.PROFILE,
        source_version: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> Parameter | None:
        spec = self.parameters.get(name)
        if spec is None:
            return None
        selected_spec, estimate_variant, available_context = _select_parameter_spec(
            spec, context
        )
        spec = selected_spec
        resolved_status = status
        if (
            status == ValueStatus.PROFILE
            and spec.get("evidence_kind") == "published_estimate"
        ):
            resolved_status = ValueStatus.PUBLISHED_ESTIMATE
        return Parameter(
            value=spec.get("value"),
            unit=spec.get("unit"),
            status=resolved_status,
            source_id=spec.get("source_id", self.source_id),
            source_version=spec.get("source_version", source_version),
            method_id=spec.get("method_id"),
            low=spec.get("low"),
            high=spec.get("high"),
            confidence=spec.get("confidence"),
            note=spec.get("note"),
            evidence_kind=spec.get("evidence_kind"),
            statistic=spec.get("statistic"),
            range_basis=spec.get("range_basis"),
            applicability=spec.get("applicability"),
            estimate_variant=estimate_variant,
            selection_basis=(
                "conditional_context"
                if estimate_variant not in {None, "family_fallback"}
                else estimate_variant
            ),
            selection_context=(
                {
                    key: context[key]
                    for key in available_context
                    if context is not None and key in context
                }
                if available_context
                else None
            ),
            available_context=available_context or None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "id": self.id,
            "label": self.label,
            "aliases": list(self.aliases),
            "source_id": self.source_id,
            "parameters": {
                name: dict(value) for name, value in self.parameters.items()
            },
            **dict(self.metadata),
        }


class Registry:
    """Profile lookup with deterministic aliases and custom-pack overlays."""

    def __init__(self, payload: Mapping[str, Any]):
        self.schema_version = str(payload.get("schema_version", "1.0"))
        self.data_version = str(payload.get("data_version", "unknown"))
        self.license = str(payload.get("license", "unknown"))
        self.sources = dict(payload.get("sources", {}))
        self._profiles: dict[str, dict[str, Profile]] = {}
        self._aliases: dict[str, dict[str, str]] = {}
        for category, records in payload.get("profiles", {}).items():
            for raw in records:
                self._add_profile(str(category), raw)

    def _add_profile(self, category: str, raw: Mapping[str, Any]) -> None:
        profile_id = normalize_id(str(raw["id"]))
        known = {
            "id",
            "label",
            "aliases",
            "source_id",
            "parameters",
        }
        profile = Profile(
            category=category,
            id=profile_id,
            label=str(raw.get("label", raw["id"])),
            aliases=tuple(str(item) for item in raw.get("aliases", ())),
            source_id=str(raw.get("source_id", "unspecified")),
            parameters=dict(raw.get("parameters", {})),
            metadata={key: value for key, value in raw.items() if key not in known},
        )
        category_profiles = self._profiles.setdefault(category, {})
        category_aliases = self._aliases.setdefault(category, {})
        category_profiles[profile_id] = profile
        for alias in (profile_id, profile.label, *profile.aliases):
            key = normalize_id(alias)
            existing = category_aliases.get(key)
            if existing is not None and existing != profile_id:
                raise ValueError(
                    f"profile alias {alias!r} in {category!r} maps to both "
                    f"{existing!r} and {profile_id!r}"
                )
            category_aliases[key] = profile_id

    def categories(self) -> tuple[str, ...]:
        return tuple(sorted(self._profiles))

    def list(self, category: str | None = None) -> tuple[Profile, ...]:
        if category is not None:
            return tuple(self._profiles.get(category, {}).values())
        return tuple(
            profile
            for category_name in sorted(self._profiles)
            for profile in self._profiles[category_name].values()
        )

    def get(self, category: str, value: str) -> Profile:
        key = normalize_id(value)
        profile_id = self._aliases.get(category, {}).get(key)
        if profile_id is None:
            choice_ids = sorted(self._profiles.get(category, {}))
            choices = ", ".join(choice_ids)
            suggestions = get_close_matches(key, choice_ids, n=3, cutoff=0.45)
            suffix = (
                f"; closest matches: {', '.join(suggestions)}" if suggestions else ""
            )
            raise ProfileNotFoundError(
                f"unknown {category} profile {value!r}; available profiles: "
                f"{choices or 'none'}{suffix}"
            )
        return self._profiles[category][profile_id]

    def find(self, category: str, value: str | None) -> Profile | None:
        if value is None:
            return None
        try:
            return self.get(category, value)
        except ProfileNotFoundError:
            return None

    def with_pack(self, path: str | Path) -> "Registry":
        """Return a new registry with a JSON profile pack overlaid by ID."""

        custom = json.loads(Path(path).read_text(encoding="utf-8"))
        return self.with_payload(custom)

    def with_payload(self, custom: Mapping[str, Any]) -> "Registry":
        """Return a registry with an in-memory profile pack overlaid by ID."""

        payload = self.to_payload()
        payload["data_version"] = (
            f"{self.data_version}+{custom.get('data_version', 'custom')}"
        )
        payload["sources"].update(custom.get("sources", {}))
        for category, records in custom.get("profiles", {}).items():
            existing = {
                normalize_id(str(record["id"])): record
                for record in payload["profiles"].setdefault(category, [])
            }
            for record in records:
                existing[normalize_id(str(record["id"]))] = record
            payload["profiles"][category] = list(existing.values())
        return Registry(payload)

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "data_version": self.data_version,
            "license": self.license,
            "sources": dict(self.sources),
            "profiles": {
                category: [profile.to_dict() for profile in profiles.values()]
                for category, profiles in self._profiles.items()
            },
        }


def _load_default() -> Registry:
    resource = files("exergy_imperative").joinpath("data/profiles.json")
    return Registry(json.loads(resource.read_text(encoding="utf-8")))


DEFAULT_REGISTRY = _load_default()


def get_default_registry() -> Registry:
    return DEFAULT_REGISTRY


def list_profiles(category: str | None = None) -> tuple[Profile, ...]:
    return DEFAULT_REGISTRY.list(category)


def load_registry_pack(path: str | Path) -> Registry:
    return DEFAULT_REGISTRY.with_pack(path)
