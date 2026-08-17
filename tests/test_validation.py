import pytest
from jsonschema import validate

import exergy_imperative as xi


def test_bundled_reference_validation_passes_and_has_citations():
    result = xi.run_bundled_validation_suite()
    assert result.passed
    assert len(result.outcomes) >= 5
    assert all(outcome.citation for outcome in result.outcomes)
    assert xi.load_schema("validation")["$id"] == xi.VALIDATION_RESULT_SCHEMA_ID
    assert xi.load_schema("engineering")["$id"] == xi.ENGINEERING_RESULT_SCHEMA_ID
    assert (
        xi.load_schema("local-dataset-adapter")["$id"]
        == xi.LOCAL_DATASET_ADAPTER_SCHEMA_ID
    )
    validate(result.to_dict(), xi.load_schema("validation"))
    validate(
        xi.analyze_heat_pump(
            delivered_heat_mwh=1,
            source_temperature_c=10,
            sink_temperature_c=60,
            cop=3,
        ).to_dict(),
        xi.load_schema("engineering"),
    )


def test_example_local_adapters_validate_against_schema():
    import json
    from pathlib import Path

    schema = xi.load_schema("local-dataset-adapter")
    root = Path(__file__).parents[1] / "examples" / "adapters"
    for path in root.glob("*.json"):
        validate(json.loads(path.read_text(encoding="utf-8")), schema)
    for name in xi.list_bundled_adapters():
        validate(xi.load_bundled_adapter(name).to_dict(), schema)


def test_xai4heat_published_summary_comparison_passes_exact_fixture():
    expected = {
        "primary_supply_ambient": (0.216, 51_592),
        "primary_supply_return_integrated": (0.172, 46_434),
        "secondary_supply_return_integrated": (0.125, 49_385),
        "primary_return_as_sink": (0.106, 51_592),
        "primary_supply_fixed_reference": (0.173, 51_592),
    }
    summary = {
        "source": "local fixture",
        "models": {
            name: {"weighted_factor": factor, "valid_intervals": intervals}
            for name, (factor, intervals) in expected.items()
        },
    }
    result = xi.validate_xai4heat_summary(summary)
    assert result.passed
    assert len(result.outcomes) == 10


def test_xai4heat_published_summary_comparison_reports_mismatch():
    result = xi.validate_xai4heat_summary({"models": {}})
    assert not result.passed
    assert all(outcome.actual is None for outcome in result.outcomes)


@pytest.mark.parametrize("tolerance", [-1, float("nan"), float("inf"), "invalid"])
def test_xai4heat_validation_rejects_invalid_factor_tolerance(tolerance):
    with pytest.raises(ValueError, match="finite and nonnegative"):
        xi.validate_xai4heat_summary({"models": {}}, factor_tolerance=tolerance)


def test_unknown_validation_method_is_rejected():
    case = xi.ValidationCase(
        id="unsafe",
        title="Unsupported",
        method="eval",
        inputs={},
        expected=0,
        absolute_tolerance=0,
        citation={"title": "test"},
    )
    with pytest.raises(ValueError, match="unsupported validation method"):
        xi.run_validation_case(case)
