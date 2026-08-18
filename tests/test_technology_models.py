import json

import jsonschema
import pytest

import exergy_imperative as xi
from exergy_imperative.cli import main


def test_registered_model_evaluates_explicit_energy_and_exergy():
    result = xi.evaluate_technology_model(
        "compressor-pump",
        input_energy=10,
        performance=0.8,
        input_exergy_factor=1,
        output_exergy_factor=1,
    )

    assert result.useful_energy == pytest.approx(8)
    assert result.destroyed_or_unallocated_exergy == pytest.approx(2)
    assert result.exergetic_efficiency == pytest.approx(0.8)
    assert result.to_dict()["schema_version"] == "1.0"
    jsonschema.validate(result.to_dict(), xi.load_schema("technology-model"))
    assert (
        xi.load_schema("technology-model")["$id"]
        == xi.TECHNOLOGY_MODEL_RESULT_SCHEMA_ID
    )


def test_model_registry_supports_declarative_pack_extensions():
    custom = xi.TechnologyModelSpec.from_dict(
        {
            "id": "custom-yield",
            "label": "Custom yield model",
            "performance_parameter": "yield",
            "description": "Test relation.",
            "maximum_performance": 1,
            "aliases": ["yield model"],
        }
    )
    registry = xi.DEFAULT_TECHNOLOGY_MODEL_REGISTRY.with_models([custom])
    assert registry.get("yield model").id == "custom-yield"

    result = xi.evaluate_technology_model(
        "custom-yield",
        input_energy=5,
        performance=0.6,
        input_exergy_factor=1,
        output_exergy_factor=1,
        registry=registry,
    )
    assert result.useful_energy == pytest.approx(3)

    pack = {
        "schema_version": "1.0",
        "id": "yield-pack",
        "version": "1",
        "license": "CC-BY-4.0",
        "description": "Test custom model pack.",
        "domains": ["tests"],
        "sources": {
            "test": {
                "title": "Test record",
                "license": "CC-BY-4.0",
                "applicable_boundary": "Test input to output",
            }
        },
        "technology_models": [custom.to_dict()],
        "profiles": {
            "technology": [
                {
                    "id": "yield-device",
                    "model": "custom-yield",
                    "input_carrier": "electricity",
                    "output_carrier": "shaft-work",
                    "performance_parameter": "yield",
                    "required_inputs": ["yield"],
                    "source_id": "test",
                    "boundary": "Test input to output",
                    "parameters": {},
                }
            ]
        },
    }
    assert xi.validate_technology_pack(pack)["valid"] is True
    assessed = xi.assess_with_pack(
        pack, technology="yield-device", energy=5, performance=0.6
    )
    assert assessed.useful_energy.value == pytest.approx(3)


def test_model_validation_rejects_bad_performance_and_boundaries():
    with pytest.raises(ValueError, match="must not exceed"):
        xi.evaluate_technology_model(
            "converter",
            input_energy=1,
            performance=1.1,
            input_exergy_factor=1,
            output_exergy_factor=1,
        )
    with pytest.raises(ValueError, match="product exergy exceeds"):
        xi.evaluate_technology_model(
            "heat-pump",
            input_energy=1,
            performance=3,
            input_exergy_factor=1,
            output_exergy_factor=0.5,
        )
    with pytest.raises(KeyError, match="unknown technology model"):
        xi.DEFAULT_TECHNOLOGY_MODEL_REGISTRY.get("warp drive")


def test_technology_model_agent_workflow_and_model_search():
    response = xi.safe_run_recipe(
        {
            "workflow": "technology-model",
            "inputs": {
                "model": "storage",
                "input_energy": 20,
                "performance": 0.7,
                "input_exergy_factor": 1,
                "output_exergy_factor": 1,
            },
        }
    )
    assert response["ok"] is True
    assert response["result"]["useful_energy"] == pytest.approx(14)
    matches = xi.search_capabilities("electrolyzer", kind="model")["matches"]
    assert any(item["id"] == "electrolyzer" for item in matches)


def test_technology_model_cli(tmp_path, capsys):
    assert main(["models", "--json"]) == 0
    assert any(item["id"] == "storage" for item in json.loads(capsys.readouterr().out))

    path = tmp_path / "model.json"
    path.write_text(
        json.dumps(
            {
                "model": "storage",
                "input_energy": 10,
                "performance": 0.8,
                "input_exergy_factor": 1,
                "output_exergy_factor": 1,
            }
        ),
        encoding="utf-8",
    )
    assert main(["model-evaluate", str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["useful_energy"] == pytest.approx(8)
