"""Versioned, inspectable profiles used to fill optional inputs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping

from .models import Parameter, ValueStatus


class ProfileNotFoundError(KeyError):
    """Raised when a requested profile or alias is unknown."""


def normalize_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


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
    ) -> Parameter | None:
        spec = self.parameters.get(name)
        if spec is None:
            return None
        return Parameter(
            value=spec.get("value"),
            unit=spec.get("unit"),
            status=status,
            source_id=self.source_id,
            source_version=source_version,
            method_id=spec.get("method_id"),
            low=spec.get("low"),
            high=spec.get("high"),
            confidence=spec.get("confidence"),
            note=spec.get("note"),
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
            choices = ", ".join(sorted(self._profiles.get(category, {})))
            raise ProfileNotFoundError(
                f"unknown {category} profile {value!r}; available profiles: {choices or 'none'}"
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

        payload = self.to_payload()
        custom = json.loads(Path(path).read_text(encoding="utf-8"))
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
