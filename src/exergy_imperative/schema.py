"""Access packaged, machine-readable contracts and profile data."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

ASSESSMENT_SCHEMA_ID = "https://github.com/cdimurro/the-exergy-imperative/schemas/assessment-result-v1.json"
ENVIRONMENTAL_SCHEMA_ID = "https://github.com/cdimurro/the-exergy-imperative/schemas/environmental-result-v1.json"
ECONOMIC_SCHEMA_ID = (
    "https://github.com/cdimurro/the-exergy-imperative/schemas/economic-result-v1.json"
)
PROCESS_SCHEMA_ID = "https://github.com/cdimurro/the-exergy-imperative/schemas/process-assessment-v1.json"
GHG_BOUNDARY_SCHEMA_ID = "https://github.com/cdimurro/the-exergy-imperative/schemas/ghg-boundary-result-v1.json"
METHANE_PROJECT_SCHEMA_ID = "https://github.com/cdimurro/the-exergy-imperative/schemas/methane-project-result-v1.json"
TECHNOLOGY_ECONOMIC_SCHEMA_ID = "https://github.com/cdimurro/the-exergy-imperative/schemas/technology-economic-result-v1.json"
WEATHER_NORMALIZATION_SCHEMA_ID = "https://github.com/cdimurro/the-exergy-imperative/schemas/weather-normalization-result-v1.json"
LOCAL_DATASET_ADAPTER_SCHEMA_ID = "https://github.com/cdimurro/the-exergy-imperative/schemas/local-dataset-adapter-v1.json"
ENGINEERING_RESULT_SCHEMA_ID = "https://github.com/cdimurro/the-exergy-imperative/schemas/engineering-result-v1.json"
VALIDATION_RESULT_SCHEMA_ID = "https://github.com/cdimurro/the-exergy-imperative/schemas/validation-result-v1.json"
AGENT_RECIPE_SCHEMA_ID = (
    "https://github.com/cdimurro/the-exergy-imperative/schemas/agent-recipe-v1.json"
)
AGENT_RESPONSE_SCHEMA_ID = (
    "https://github.com/cdimurro/the-exergy-imperative/schemas/agent-response-v1.json"
)
AGENT_CAPABILITIES_SCHEMA_ID = "https://github.com/cdimurro/the-exergy-imperative/schemas/agent-capabilities-v1.json"

_SCHEMA_FILES = {
    "assessment": "assessment-result.schema.json",
    "environmental": "environmental-result.schema.json",
    "economic": "economic-result.schema.json",
    "process": "process-assessment.schema.json",
    "ghg-boundary": "ghg-boundary-result.schema.json",
    "methane-project": "methane-project-result.schema.json",
    "technology-economic": "technology-economic-result.schema.json",
    "weather-normalization": "weather-normalization-result.schema.json",
    "local-dataset-adapter": "local-dataset-adapter.schema.json",
    "engineering": "engineering-result.schema.json",
    "validation": "validation-result.schema.json",
    "agent-recipe": "agent-recipe.schema.json",
    "agent-response": "agent-response.schema.json",
    "agent-capabilities": "agent-capabilities.schema.json",
}


def load_schema(name: str) -> dict[str, Any]:
    try:
        filename = _SCHEMA_FILES[name.strip().lower()]
    except KeyError as exc:
        raise KeyError(
            f"unknown schema {name!r}; choose from {', '.join(_SCHEMA_FILES)}"
        ) from exc
    resource = files("exergy_imperative").joinpath("data", "schemas", filename)
    return json.loads(resource.read_text(encoding="utf-8"))


def list_schemas() -> list[dict[str, Any]]:
    """List stable names and identifiers for every packaged JSON Schema."""

    return [
        {
            "name": name,
            "$id": load_schema(name).get("$id"),
            "filename": filename,
        }
        for name, filename in _SCHEMA_FILES.items()
    ]


def load_assessment_schema() -> dict[str, Any]:
    return load_schema("assessment")


def load_bundled_profiles() -> dict[str, Any]:
    resource = files("exergy_imperative").joinpath("data/profiles.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def load_bundled_impact_factors() -> dict[str, Any]:
    resource = files("exergy_imperative").joinpath("data", "impact_factors.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def load_bundled_grid_factors() -> dict[str, Any]:
    resource = files("exergy_imperative").joinpath("data", "global_electricity.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def load_bundled_process_templates() -> dict[str, Any]:
    resource = files("exergy_imperative").joinpath("data", "process_templates.json")
    return json.loads(resource.read_text(encoding="utf-8"))
