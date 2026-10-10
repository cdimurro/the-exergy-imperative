import json
from importlib import resources

import pytest
from jsonschema import Draft202012Validator, ValidationError

from exergy_imperative import assess_exergy_reference

SCHEMA = json.loads(
    resources.files("exergy_imperative")
    .joinpath("data/schemas/exergy_reference_assessment_v1.schema.json")
    .read_text(encoding="utf-8")
)
VALIDATOR = Draft202012Validator(SCHEMA)


@pytest.mark.parametrize("index", range(20))
def test_twenty_recorded_missing_reference_patterns(index):
    # Twenty historical cases reduce to 12 partial tuples and 8 absent tuples.
    # This synthetic regression encodes those patterns, not new measured data.
    environment = {"T0_K": 283.15} if index < 12 else None
    result = assess_exergy_reference(environment)
    VALIDATOR.validate(result)
    assert result["reference_gate"] == "unresolved"
    assert result["physical_exergy_status"] == "unresolved"
    assert result["reference_carried"] == (environment or {})
    assert result["missing_reference_fields"] == (
        ["P0_Pa", "composition"] if index < 12 else ["T0_K", "P0_Pa", "composition"]
    )


def test_complete_reference_is_not_a_closed_account():
    declaration = {
        "T0_K": 298.15,
        "P0_Pa": 101325,
        "composition": "declared water reference",
    }
    result = assess_exergy_reference(declaration)
    VALIDATOR.validate(result)
    assert result["reference_gate"] == "passed"
    assert result["missing_reference_fields"] == []
    assert result["physical_exergy_status"] == "unresolved"
    assert result["physical_account_verified"] is False
    assert result["claim_permitted"] is False


def test_self_awarded_authority_is_ignored_and_schema_rejects_promotion():
    result = assess_exergy_reference(
        {"physical_account_verified": True, "claim_permitted": True}
    )
    VALIDATOR.validate(result)
    assert result["physical_account_verified"] is False
    dirty = dict(result, physical_exergy_status="settled")
    with pytest.raises(ValidationError):
        VALIDATOR.validate(dirty)


@pytest.mark.parametrize("field", ["T0_K", "P0_Pa"])
@pytest.mark.parametrize(
    "value", [True, False, 0, -1, float("nan"), float("inf"), "298.15"]
)
def test_invalid_numeric_declarations_refused(field, value):
    with pytest.raises(ValueError, match=field):
        assess_exergy_reference({field: value})


@pytest.mark.parametrize("value", ["", " ", {}, [], False])
def test_invalid_composition_refused(value):
    with pytest.raises(ValueError, match="composition"):
        assess_exergy_reference({"composition": value})


def test_null_is_missing_and_input_is_not_mutated():
    assert assess_exergy_reference({"T0_K": None})["missing_reference_fields"] == [
        "T0_K",
        "P0_Pa",
        "composition",
    ]
    declaration = {"T0_K": 298.15, "P0_Pa": 101325, "composition": {"water": 1}}
    result = assess_exergy_reference(declaration)
    result["reference_carried"]["composition"]["water"] = 2
    assert declaration["composition"] == {"water": 1}
    with pytest.raises(ValueError, match="mapping"):
        assess_exergy_reference([])


def test_nonfinite_nested_metadata_refused():
    with pytest.raises(ValueError, match="JSON-compatible"):
        assess_exergy_reference({"composition": {"water": float("nan")}})
