"""Reproducible reference cases and optional local-data validation."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .engineering import analyze_heat_pump
from .formulas import petela_exergy_factor, thermal_exergy_factor_c
from .ingestion import read_records
from .preprocess import xai4heat_summary


@dataclass(frozen=True)
class ValidationCase:
    id: str
    title: str
    method: str
    inputs: Mapping[str, Any]
    expected: float
    absolute_tolerance: float
    citation: Mapping[str, str]
    output_path: str = ""
    notes: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ValidationCase":
        return cls(
            id=str(payload["id"]),
            title=str(payload["title"]),
            method=str(payload["method"]),
            inputs=dict(payload.get("inputs", {})),
            expected=float(payload["expected"]),
            absolute_tolerance=float(payload.get("absolute_tolerance", 1e-9)),
            citation=dict(payload["citation"]),
            output_path=str(payload.get("output_path", "")),
            notes=str(payload.get("notes", "")),
        )


@dataclass(frozen=True)
class ValidationOutcome:
    case_id: str
    title: str
    expected: float
    actual: float | None
    absolute_tolerance: float
    passed: bool
    citation: Mapping[str, str]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "title": self.title,
            "expected": self.expected,
            "actual": self.actual,
            "absolute_tolerance": self.absolute_tolerance,
            "passed": self.passed,
            "citation": dict(self.citation),
            "message": self.message,
        }


@dataclass(frozen=True)
class ValidationSuiteResult:
    suite_id: str
    outcomes: tuple[ValidationOutcome, ...]
    source: str
    notes: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return bool(self.outcomes) and all(item.passed for item in self.outcomes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "suite_id": self.suite_id,
            "passed": self.passed,
            "passed_cases": sum(item.passed for item in self.outcomes),
            "total_cases": len(self.outcomes),
            "source": self.source,
            "outcomes": [item.to_dict() for item in self.outcomes],
            "notes": list(self.notes),
        }


def load_validation_cases() -> tuple[ValidationCase, ...]:
    resource = files("exergy_imperative").joinpath("data", "validation_cases.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    return tuple(ValidationCase.from_dict(item) for item in payload["cases"])


def _resolve_output(value: Any, path: str) -> float:
    current = value.to_dict() if hasattr(value, "to_dict") else value
    for part in filter(None, path.split(".")):
        if isinstance(current, Mapping):
            current = current[part]
        else:
            current = getattr(current, part)
    return float(current)


def _methods() -> Mapping[str, Callable[..., Any]]:
    return {
        "thermal_exergy_factor_c": thermal_exergy_factor_c,
        "petela_exergy_factor": petela_exergy_factor,
        "analyze_heat_pump": analyze_heat_pump,
    }


def run_validation_case(case: ValidationCase) -> ValidationOutcome:
    try:
        method = _methods()[case.method]
    except KeyError as exc:
        raise ValueError(f"unsupported validation method {case.method!r}") from exc
    actual = _resolve_output(method(**case.inputs), case.output_path)
    passed = math.isclose(
        actual, case.expected, rel_tol=0.0, abs_tol=case.absolute_tolerance
    )
    delta = abs(actual - case.expected)
    return ValidationOutcome(
        case_id=case.id,
        title=case.title,
        expected=case.expected,
        actual=actual,
        absolute_tolerance=case.absolute_tolerance,
        passed=passed,
        citation=case.citation,
        message=(
            f"passed; absolute difference {delta:.6g}"
            if passed
            else f"failed; absolute difference {delta:.6g} exceeds {case.absolute_tolerance:.6g}"
        ),
    )


def run_bundled_validation_suite() -> ValidationSuiteResult:
    cases = load_validation_cases()
    return ValidationSuiteResult(
        suite_id="bundled-reference-cases-v1",
        outcomes=tuple(run_validation_case(case) for case in cases),
        source="packaged reference cases",
        notes=(
            "Passing reference cases checks implementation consistency, not fitness for a particular design or investment decision.",
        ),
    )


_XAI4HEAT_EXPECTED = {
    "primary_supply_ambient": (0.216, 51_592),
    "primary_supply_return_integrated": (0.172, 46_434),
    "secondary_supply_return_integrated": (0.125, 49_385),
    "primary_return_as_sink": (0.106, 51_592),
    "primary_supply_fixed_reference": (0.173, 51_592),
}


def validate_xai4heat_summary(
    summary: Mapping[str, Any], *, factor_tolerance: float = 0.0005
) -> ValidationSuiteResult:
    """Compare an XAI4Heat summary with the published portfolio-level results."""

    try:
        tolerance = float(factor_tolerance)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("factor_tolerance must be finite and nonnegative") from exc
    if not math.isfinite(tolerance) or tolerance < 0.0:
        raise ValueError("factor_tolerance must be finite and nonnegative")
    outcomes: list[ValidationOutcome] = []
    citation = {
        "title": "The Exergy Imperative: A Quantity-and-Quality Standard Reporting Framework",
        "locator": "Section 9, Table 9",
    }
    models = summary.get("models", {})
    for name, (expected_factor, expected_intervals) in _XAI4HEAT_EXPECTED.items():
        model = models.get(name, {})
        factor = model.get("weighted_factor")
        actual = float(factor) if factor is not None else None
        factor_passed = actual is not None and math.isclose(
            actual, expected_factor, rel_tol=0.0, abs_tol=tolerance
        )
        outcomes.append(
            ValidationOutcome(
                case_id=f"xai4heat-{name}-factor",
                title=f"XAI4Heat {name.replace('_', ' ')} weighted factor",
                expected=expected_factor,
                actual=actual,
                absolute_tolerance=tolerance,
                passed=factor_passed,
                citation=citation,
                message="factor agrees" if factor_passed else "factor does not agree",
            )
        )
        intervals = model.get("valid_intervals")
        actual_intervals = float(intervals) if intervals is not None else None
        interval_passed = actual_intervals == float(expected_intervals)
        outcomes.append(
            ValidationOutcome(
                case_id=f"xai4heat-{name}-intervals",
                title=f"XAI4Heat {name.replace('_', ' ')} valid intervals",
                expected=float(expected_intervals),
                actual=actual_intervals,
                absolute_tolerance=0.0,
                passed=interval_passed,
                citation=citation,
                message=(
                    "interval count agrees"
                    if interval_passed
                    else "interval count does not agree"
                ),
            )
        )
    return ValidationSuiteResult(
        suite_id="xai4heat-paper-table-9-v1",
        outcomes=tuple(outcomes),
        source=str(summary.get("source", "user-supplied XAI4Heat records")),
        notes=(
            "The library does not distribute the underlying XAI4Heat data; this comparison runs on records supplied by the user.",
        ),
    )


def validate_xai4heat_records(
    records: Iterable[Mapping[str, Any]],
    *,
    source: str = "user-supplied records",
    fixed_reference_c: float = 20.0,
    factor_tolerance: float = 0.0005,
) -> ValidationSuiteResult:
    summary = xai4heat_summary(records, fixed_reference_c=fixed_reference_c)
    summary["source"] = source
    return validate_xai4heat_summary(summary, factor_tolerance=factor_tolerance)


def validate_xai4heat_file(
    path: str | Path,
    *,
    sheet_name: str | int = 0,
    header_row: int = 1,
    fixed_reference_c: float = 20.0,
    factor_tolerance: float = 0.0005,
) -> ValidationSuiteResult:
    source = Path(path)
    records = read_records(source, sheet_name=sheet_name, header_row=header_row)
    return validate_xai4heat_records(
        records,
        source=str(source.resolve()),
        fixed_reference_c=fixed_reference_c,
        factor_tolerance=factor_tolerance,
    )
