"""Reproducible reference cases and optional local-data validation."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .balance import analyze_balance
from .economics import capital_recovery_factor, net_present_value
from .engineering import (
    analyze_compressed_air,
    analyze_furnace,
    analyze_heat_pump,
    analyze_refrigeration,
)
from .factors import DEFAULT_IMPACT_FACTORS
from .formulas import (
    cooling_exergy_factor_c,
    exergy_destruction,
    ideal_gas_pressure_exergy,
    ideal_mixture_separation_exergy,
    kinetic_exergy,
    petela_exergy_factor,
    physical_flow_exergy,
    potential_exergy,
    sensible_heat_exergy_factor_c,
    thermal_exergy_factor_c,
)
from .ghg import assess_methane_project
from .ingestion import read_records
from .materials import analyze_material_definition
from .models import ExergyStream
from .packs import assess_intensity_with_pack, assess_performance_with_pack
from .preprocess import xai4heat_summary
from .systems import analyze_system_definition
from .technology_models import evaluate_technology_model
from .uncertainty import expected_value_of_perfect_information
from .units import convert_energy
from .weather import add_weather_metrics

VALIDATION_LEVELS = (
    "reference-validated",
    "analytically-validated",
    "cross-implementation-validated",
    "conservation-validated",
    "structural-only",
    "screening-only",
    "external-data-required",
    "interface-only",
)


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
    relative_tolerance: float = 0.0
    validation_type: str = "reference"
    capabilities: tuple[str, ...] = ()

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
            relative_tolerance=float(payload.get("relative_tolerance", 0.0)),
            validation_type=str(payload.get("validation_type", "reference")),
            capabilities=tuple(str(item) for item in payload.get("capabilities", ())),
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
    relative_tolerance: float = 0.0
    validation_type: str = "reference"
    capabilities: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "title": self.title,
            "expected": self.expected,
            "actual": self.actual,
            "absolute_tolerance": self.absolute_tolerance,
            "relative_tolerance": self.relative_tolerance,
            "passed": self.passed,
            "citation": dict(self.citation),
            "validation_type": self.validation_type,
            "capabilities": list(self.capabilities),
            "message": self.message,
        }


@dataclass(frozen=True)
class ValidationCoverageItem:
    """Scientific assurance level for one coherent capability family."""

    id: str
    title: str
    level: str
    public_api: tuple[str, ...]
    tests: tuple[str, ...]
    case_ids: tuple[str, ...]
    evidence: tuple[Mapping[str, str], ...]
    limitations: tuple[str, ...]
    decision_grade: bool = False

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ValidationCoverageItem":
        level = str(payload["level"])
        if level not in VALIDATION_LEVELS:
            raise ValueError(f"unsupported scientific validation level {level!r}")
        return cls(
            id=str(payload["id"]),
            title=str(payload["title"]),
            level=level,
            public_api=tuple(str(item) for item in payload.get("public_api", ())),
            tests=tuple(str(item) for item in payload.get("tests", ())),
            case_ids=tuple(str(item) for item in payload.get("case_ids", ())),
            evidence=tuple(dict(item) for item in payload.get("evidence", ())),
            limitations=tuple(str(item) for item in payload.get("limitations", ())),
            decision_grade=bool(payload.get("decision_grade", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "level": self.level,
            "public_api": list(self.public_api),
            "tests": list(self.tests),
            "case_ids": list(self.case_ids),
            "evidence": [dict(item) for item in self.evidence],
            "limitations": list(self.limitations),
            "decision_grade": self.decision_grade,
        }


@dataclass(frozen=True)
class ScientificValidationCoverage:
    """Machine-readable scientific coverage ledger for the public package."""

    version: str
    generated_on: str
    scope: str
    items: tuple[ValidationCoverageItem, ...]
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "coverage_version": self.version,
            "generated_on": self.generated_on,
            "scope": self.scope,
            "levels": list(VALIDATION_LEVELS),
            "items": [item.to_dict() for item in self.items],
            "notes": list(self.notes),
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

    @property
    def passed_cases(self) -> int:
        return sum(item.passed for item in self.outcomes)

    @property
    def total_cases(self) -> int:
        return len(self.outcomes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "suite_id": self.suite_id,
            "passed": self.passed,
            "passed_cases": self.passed_cases,
            "total_cases": self.total_cases,
            "source": self.source,
            "outcomes": [item.to_dict() for item in self.outcomes],
            "notes": list(self.notes),
        }


def load_validation_cases() -> tuple[ValidationCase, ...]:
    resource = files("exergy_imperative").joinpath("data", "validation_cases.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    cases = tuple(ValidationCase.from_dict(item) for item in payload["cases"])
    ids = [item.id for item in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("bundled scientific validation cases contain duplicate ids")
    return cases


def load_validation_coverage() -> ScientificValidationCoverage:
    resource = files("exergy_imperative").joinpath("data", "validation_coverage.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    items = tuple(ValidationCoverageItem.from_dict(item) for item in payload["items"])
    ids = [item.id for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError("scientific validation coverage contains duplicate item ids")
    return ScientificValidationCoverage(
        version=str(payload["coverage_version"]),
        generated_on=str(payload["generated_on"]),
        scope=str(payload["scope"]),
        items=items,
        notes=tuple(str(item) for item in payload.get("notes", ())),
    )


def _resolve_output(value: Any, path: str) -> float:
    current = value.to_dict() if hasattr(value, "to_dict") else value
    for part in filter(None, path.split(".")):
        if isinstance(current, Mapping):
            current = current[part]
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
            current = current[int(part)]
        else:
            current = getattr(current, part)
    return float(current)


def _gwp(gas: str, horizon: int) -> float:
    return DEFAULT_IMPACT_FACTORS.warming_potential(gas).for_horizon(horizon)


def _fuel_factor(carrier: str, species: str) -> float:
    return DEFAULT_IMPACT_FACTORS.fuel_emissions(carrier).gases_kg_per_mwh[species]


def _methane_combustion_co2(methane_mass_kg: float) -> float:
    result = assess_methane_project(
        annual_methane_mass_kg=methane_mass_kg,
        baseline_mode="vented",
        project_mode="oxidized",
    )
    return result.project.combustion_co2_kg


def _degree_days(temperature_c: float, base_c: float, mode: str) -> float:
    row = add_weather_metrics(
        [{"date": "2026-01-01", "temperature_c": temperature_c}],
        heating_base_c=base_c,
        cooling_base_c=base_c,
    )[0]
    return float(row[f"{mode}_degree_days_c_day"])


def _balance_destruction(input_exergy: float, product_exergy: float) -> float:
    return analyze_balance(
        "validation balance",
        inputs=[ExergyStream("input", input_exergy)],
        products=[ExergyStream("product", product_exergy)],
    ).destruction_exergy


def _system_residual() -> float:
    result = analyze_system_definition(
        {
            "name": "validation system",
            "components": [{"id": "converter", "kind": "converter"}],
            "flows": [
                {
                    "id": "input",
                    "energy": 100.0,
                    "target": "converter",
                    "exergy_factor": 1.0,
                },
                {
                    "id": "product",
                    "energy": 60.0,
                    "source": "converter",
                    "exergy_factor": 1.0,
                },
                {
                    "id": "loss",
                    "energy": 40.0,
                    "source": "converter",
                    "role": "loss",
                    "exergy_factor": 0.25,
                },
            ],
        }
    )
    return result.energy.residual


def _material_residual() -> float:
    result = analyze_material_definition(
        {
            "name": "validation separator",
            "components": [{"id": "separator", "kind": "reactor-separator"}],
            "streams": [
                {
                    "id": "feed",
                    "mass": 100.0,
                    "target": "separator",
                    "composition": {"a": 0.6, "b": 0.4},
                },
                {
                    "id": "product",
                    "mass": 60.0,
                    "source": "separator",
                    "material": "a",
                },
                {
                    "id": "loss",
                    "mass": 40.0,
                    "source": "separator",
                    "role": "loss",
                    "material": "b",
                },
            ],
        }
    )
    return result.balance.residual_mass_kg


def _methods() -> Mapping[str, Callable[..., Any]]:
    return {
        "thermal_exergy_factor_c": thermal_exergy_factor_c,
        "cooling_exergy_factor_c": cooling_exergy_factor_c,
        "sensible_heat_exergy_factor_c": sensible_heat_exergy_factor_c,
        "physical_flow_exergy": physical_flow_exergy,
        "exergy_destruction": exergy_destruction,
        "kinetic_exergy": kinetic_exergy,
        "potential_exergy": potential_exergy,
        "ideal_gas_pressure_exergy": ideal_gas_pressure_exergy,
        "ideal_mixture_separation_exergy": ideal_mixture_separation_exergy,
        "petela_exergy_factor": petela_exergy_factor,
        "convert_energy": convert_energy,
        "capital_recovery_factor": capital_recovery_factor,
        "net_present_value": net_present_value,
        "analyze_heat_pump": analyze_heat_pump,
        "analyze_refrigeration": analyze_refrigeration,
        "analyze_furnace": analyze_furnace,
        "analyze_compressed_air": analyze_compressed_air,
        "gwp": _gwp,
        "fuel_factor": _fuel_factor,
        "methane_combustion_co2": _methane_combustion_co2,
        "degree_days": _degree_days,
        "balance_destruction": _balance_destruction,
        "system_residual": _system_residual,
        "material_residual": _material_residual,
        "expected_value_of_perfect_information": (
            expected_value_of_perfect_information
        ),
        "evaluate_technology_model": evaluate_technology_model,
        "assess_performance_with_pack": assess_performance_with_pack,
        "assess_intensity_with_pack": assess_intensity_with_pack,
    }


def run_validation_case(case: ValidationCase) -> ValidationOutcome:
    if (
        not math.isfinite(case.expected)
        or not math.isfinite(case.absolute_tolerance)
        or not math.isfinite(case.relative_tolerance)
        or case.absolute_tolerance < 0.0
        or case.relative_tolerance < 0.0
    ):
        raise ValueError(
            "validation expected value and tolerances must be finite; tolerances "
            "must be nonnegative"
        )
    try:
        method = _methods()[case.method]
    except KeyError as exc:
        raise ValueError(f"unsupported validation method {case.method!r}") from exc
    actual = _resolve_output(method(**case.inputs), case.output_path)
    if not math.isfinite(actual):
        raise ValueError(
            f"validation method {case.method!r} returned a nonfinite value"
        )
    passed = math.isclose(
        actual,
        case.expected,
        rel_tol=case.relative_tolerance,
        abs_tol=case.absolute_tolerance,
    )
    delta = abs(actual - case.expected)
    return ValidationOutcome(
        case_id=case.id,
        title=case.title,
        expected=case.expected,
        actual=actual,
        absolute_tolerance=case.absolute_tolerance,
        relative_tolerance=case.relative_tolerance,
        passed=passed,
        citation=case.citation,
        validation_type=case.validation_type,
        capabilities=case.capabilities,
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
            "Passing cases establishes agreement only for the declared equations, constants, boundaries, and tolerances.",
            "Screening priors, site measurements, external datasets, exposure, and design fitness require separate evidence; inspect load_validation_coverage().",
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
