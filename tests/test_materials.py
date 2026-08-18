import json

import jsonschema
import pytest

import exergy_imperative as xi
from exergy_imperative.cli import main


def _separator_definition():
    source = {
        "title": "Synthetic separator conservation fixture",
        "license": "CC0-1.0 test fixture",
        "applicable_boundary": "Exact mass and constituent closure only",
    }
    return {
        "name": "ore separator",
        "components": [{"id": "separator", "kind": "reactor-separator"}],
        "source_catalog": {"campaign": source},
        "streams": [
            {
                "id": "feed",
                "mass": 0.1,
                "unit": "t",
                "target": "separator",
                "composition": {"valuable": 0.8, "gangue": 0.2},
                "specific_chemical_exergy_mj_per_kg": 10,
                "source_id": "campaign",
                "tier": "F3",
            },
            {
                "id": "concentrate",
                "mass": 80,
                "unit": "kg",
                "source": "separator",
                "material": "valuable",
                "specific_chemical_exergy_mj_per_kg": 12.5,
                "source_id": "campaign",
                "tier": "F3",
            },
            {
                "id": "tailings",
                "mass": 20,
                "source": "separator",
                "role": "loss",
                "material": "gangue",
                "specific_chemical_exergy_mj_per_kg": 0,
                "source_id": "campaign",
                "tier": "F3",
            },
        ],
    }


def test_material_balance_closes_mass_constituents_and_explicit_chemical_exergy():
    result = xi.analyze_material_definition(_separator_definition())

    assert result.tier is xi.FidelityTier.F3
    assert result.balance.input_mass_kg == pytest.approx(100)
    assert result.balance.product_mass_kg == pytest.approx(80)
    assert result.balance.loss_mass_kg == pytest.approx(20)
    assert result.balance.residual_mass_kg == pytest.approx(0)
    assert result.balance.constituent_balances["valuable"]["residual_mass_kg"] == 0
    assert result.balance.constituent_balances["gangue"]["residual_mass_kg"] == 0
    assert result.balance.chemical_exergy_complete is True
    assert result.balance.chemical_exergy[
        "unreconciled_chemical_exergy"
    ] == pytest.approx(0)
    assert "campaign" in result.source_catalog
    jsonschema.validate(result.to_dict(), xi.load_schema("material-balance"))
    jsonschema.validate(
        _separator_definition(), xi.load_schema("material-balance-definition")
    )


def test_material_balance_handles_storage_change_without_double_counting():
    result = xi.analyze_material_system(
        "tank fill",
        components=[{"id": "tank", "kind": "storage"}],
        streams=[
            {
                "id": "receipt",
                "mass": 1000,
                "unit": "kg",
                "target": "tank",
                "material": "methanol",
            }
        ],
        accumulations=[
            {
                "component": "tank",
                "mass_change": 1,
                "unit": "t",
                "material": "methanol",
            }
        ],
    )

    assert result.balance.input_mass_kg == pytest.approx(1000)
    assert result.balance.product_mass_kg == pytest.approx(1000)
    assert result.balance.accumulation_mass_kg == pytest.approx(1000)
    assert result.balance.chemical_exergy is None
    assert any("Chemical-exergy balance omitted" in item for item in result.warnings)


def test_material_inputs_reject_ambiguous_or_invalid_inventories():
    with pytest.raises(ValueError, match="sum to one"):
        xi.MaterialStream.from_dict(
            {
                "id": "bad",
                "mass": 1,
                "target": "unit",
                "composition": {"a": 0.2, "b": 0.2},
            }
        )
    with pytest.raises(ValueError, match="material or composition"):
        xi.MaterialStream.from_dict({"id": "bad", "mass": 1, "target": "unit"})
    with pytest.raises(ValueError, match="unknown material source"):
        xi.analyze_material_system(
            "bad source",
            components=[{"id": "unit", "kind": "converter"}],
            streams=[
                {
                    "id": "feed",
                    "mass": 1,
                    "target": "unit",
                    "material": "feed",
                    "source_id": "missing",
                }
            ],
        )
    with pytest.raises(ValueError, match="unknown target"):
        payload = _separator_definition()
        payload["streams"][0]["target"] = "missing"
        xi.analyze_material_definition(payload)


def test_material_recipe_cli_and_capability_discovery(tmp_path, capsys):
    recipe = {
        "workflow": "material-balance",
        "inputs": _separator_definition(),
    }
    response = xi.safe_run_recipe(recipe)
    assert response["ok"] is True
    assert response["result"]["balance"]["residual_mass"] == pytest.approx(0)

    path = tmp_path / "materials.json"
    path.write_text(json.dumps(_separator_definition()), encoding="utf-8")
    assert main(["material-balance", str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["balance"]["residual_mass"] == 0

    matches = xi.search_capabilities("cement clinker", kind="material")["matches"]
    assert any(item["id"] == "cement-clinker" for item in matches)
    described = xi.describe_target("cement-clinker", kind="material")
    assert described["items"][0]["pack"] == "advanced-materials"
