"""Preprocessing for real-world thermal telemetry, including XAI4Heat."""

from __future__ import annotations

import csv
import math
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .formulas import sensible_heat_exergy_factor_c, thermal_exergy_factor_c
from .ingestion import _spreadsheet_safe_value, _validate_tabular_headers
from .registry import DEFAULT_REGISTRY

_ALIASES = {
    "timestamp": {
        "timestamp",
        "datetime",
        "date_time",
        "time",
        "date",
    },
    "ambient_temperature_c": {
        "t_amb",
        "tamb",
        "ambient_temperature",
        "ambient_temperature_c",
        "outside_temperature",
        "outdoor_temperature",
        "outdoor_air_temperature",
    },
    "primary_supply_temperature_c": {
        "t_sup_prim",
        "tsupprim",
        "primary_supply_temperature",
        "primary_supply_temperature_c",
        "supply_temperature",
        "supply_temperature_c",
        "t_supply",
    },
    "primary_return_temperature_c": {
        "t_ret_prim",
        "tretprim",
        "primary_return_temperature",
        "primary_return_temperature_c",
        "return_temperature",
        "return_temperature_c",
        "t_return",
    },
    "secondary_supply_temperature_c": {
        "t_sup_sec",
        "tsupsec",
        "secondary_supply_temperature",
        "secondary_supply_temperature_c",
    },
    "secondary_return_temperature_c": {
        "t_ret_sec",
        "tretsec",
        "secondary_return_temperature",
        "secondary_return_temperature_c",
    },
    "thermal_delivery": {
        "qizm",
        "thermal_delivery",
        "heat_delivery",
        "energy",
        "energy_kwh",
        "energy_mwh",
        "heat_energy",
    },
}

# Explicit unit-bearing delivery aliases are normalized to MWh before they are
# used as weights or multiplied by an exergy factor. Unitless aliases retain
# their source unit because guessing a scale would be less safe than preserving
# it; they can still be used for internally consistent weighted summaries.
_THERMAL_DELIVERY_TO_MWH = {
    "energy_kwh": 0.001,
    "energy_mwh": 1.0,
}


def normalize_field_name(value: str) -> str:
    normalized = value.strip().lower().replace("°", "")
    normalized = re.sub(r"\bdeg(?:ree)?s?\b", "", normalized)
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return normalized


_ALIAS_INDEX = {
    normalize_field_name(alias): canonical
    for canonical, aliases in _ALIASES.items()
    for alias in aliases | {canonical}
}


def canonicalize_record(
    record: Mapping[str, Any],
    aliases: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Map common historian and XAI4Heat names into canonical fields."""

    custom = {
        normalize_field_name(source): target
        for source, target in (aliases or {}).items()
    }
    result: dict[str, Any] = {}
    source_names: dict[str, str] = {}
    for name, value in record.items():
        normalized = normalize_field_name(str(name))
        canonical = custom.get(normalized) or _ALIAS_INDEX.get(normalized)
        if canonical is None and normalized.endswith("_c"):
            without_celsius = normalized[:-2]
            canonical = custom.get(without_celsius) or _ALIAS_INDEX.get(without_celsius)
        canonical = canonical or str(name)
        if canonical == "thermal_delivery" and normalized in _THERMAL_DELIVERY_TO_MWH:
            try:
                value = float(value) * _THERMAL_DELIVERY_TO_MWH[normalized]
            except (TypeError, ValueError):
                # Preserve invalid source values so the normal data-quality path
                # can classify them as missing rather than failing ingestion.
                pass
        if canonical not in result or result[canonical] in {None, ""}:
            result[canonical] = value
            source_names[canonical] = str(name)
        elif value not in {None, ""} and result[canonical] != value:
            raise ValueError(
                f"conflicting values for canonical field {canonical!r} from "
                f"{source_names[canonical]!r} and {str(name)!r}"
            )
    return result


def _optional_float(record: Mapping[str, Any], field: str) -> float | None:
    value = record.get(field)
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _try_factor(function: Any, *values: float | None) -> float | None:
    if any(value is None for value in values):
        return None
    try:
        return float(function(*values))
    except ValueError:
        return None


def _valid_timestamp(value: Any) -> bool:
    """Return whether a telemetry timestamp identifies a parseable date/time."""

    if isinstance(value, (datetime, date)):
        return True
    if value is None or not str(value).strip():
        return False
    try:
        datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return True


def _validated_fixed_reference_c(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("fixed_reference_c must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError("fixed_reference_c must be finite")
    if number <= -273.15:
        raise ValueError("fixed_reference_c must be above absolute zero")
    return number


def enrich_xai4heat_record(
    record: Mapping[str, Any],
    *,
    fixed_reference_c: float = 20.0,
    aliases: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Add all thermal factors supported by one telemetry record."""

    fixed_reference_c = _validated_fixed_reference_c(fixed_reference_c)
    canonical = canonicalize_record(record, aliases)
    ambient = _optional_float(canonical, "ambient_temperature_c")
    supply = _optional_float(canonical, "primary_supply_temperature_c")
    return_ = _optional_float(canonical, "primary_return_temperature_c")
    secondary_supply = _optional_float(canonical, "secondary_supply_temperature_c")
    secondary_return = _optional_float(canonical, "secondary_return_temperature_c")
    raw_weight = _optional_float(canonical, "thermal_delivery")
    weight = max(0.0, raw_weight) if raw_weight is not None else None

    dynamic = _try_factor(thermal_exergy_factor_c, supply, ambient)
    fixed = _try_factor(thermal_exergy_factor_c, supply, fixed_reference_c)
    primary_integrated = _try_factor(
        sensible_heat_exergy_factor_c, supply, return_, ambient
    )
    secondary_integrated = _try_factor(
        sensible_heat_exergy_factor_c, secondary_supply, secondary_return, ambient
    )
    return_sink = _try_factor(thermal_exergy_factor_c, supply, return_)

    issues: list[str] = []
    if supply is None:
        issues.append("missing_or_invalid_primary_supply_temperature")
    if ambient is None:
        issues.append("missing_or_invalid_ambient_temperature")
    if raw_weight is not None and raw_weight < 0.0:
        issues.append("negative_thermal_delivery_clipped_to_zero")
    if return_ is None:
        issues.append("primary_integrated_model_unavailable_without_return_temperature")

    timestamp = canonical.get("timestamp")
    timestamp_present = timestamp is not None and str(timestamp).strip() != ""
    timestamp_valid = _valid_timestamp(timestamp)
    if timestamp_present and not timestamp_valid:
        issues.append("invalid_timestamp_fidelity_downgraded")

    tier = "F3" if timestamp_valid and dynamic is not None else "F2"
    if dynamic is None:
        tier = "F0"
    enriched = dict(record)
    enriched.update(
        {
            "exergy_tier": tier,
            "exergy_method_id": "thermal.carnot.dynamic-ambient.v1"
            if dynamic is not None
            else None,
            "exergy_registry_version": DEFAULT_REGISTRY.data_version,
            "fx_dynamic_ambient": dynamic,
            "fx_fixed_reference": fixed,
            "fx_primary_integrated": primary_integrated,
            "fx_secondary_integrated": secondary_integrated,
            "fx_primary_return_sink": return_sink,
            "thermal_delivery_weight": weight,
            "accessible_exergy_dynamic": (
                weight * dynamic if weight is not None and dynamic is not None else None
            ),
            "exergy_data_quality": "valid" if dynamic is not None else "insufficient",
            "exergy_issues": ";".join(issues),
        }
    )
    return enriched


def enrich_xai4heat_records(
    records: Iterable[Mapping[str, Any]],
    *,
    fixed_reference_c: float = 20.0,
    aliases: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    fixed_reference_c = _validated_fixed_reference_c(fixed_reference_c)
    return [
        enrich_xai4heat_record(
            record,
            fixed_reference_c=fixed_reference_c,
            aliases=aliases,
        )
        for record in records
    ]


def _weighted_metric(
    records: Iterable[Mapping[str, Any]], field: str
) -> dict[str, Any]:
    values: list[tuple[float, float | None]] = []
    for record in records:
        value = _optional_float(record, field)
        weight = _optional_float(record, "thermal_delivery_weight")
        if value is None:
            continue
        values.append((value, weight))
    known_weights = [(value, weight) for value, weight in values if weight is not None]
    if known_weights:
        weighted_sum = sum(
            value * max(0.0, float(weight)) for value, weight in known_weights
        )
        weight_sum = sum(max(0.0, float(weight)) for _, weight in known_weights)
        factor = weighted_sum / weight_sum if weight_sum > 0.0 else None
        weighting = "thermal_delivery"
        weighted_intervals = len(known_weights)
    else:
        weight_sum = float(len(values))
        factor = sum(value for value, _ in values) / len(values) if values else None
        weighting = "equal_interval_fallback"
        weighted_intervals = len(values)
    return {
        "weighted_factor": factor,
        "valid_intervals": len(values),
        "weighted_intervals": weighted_intervals,
        "total_weight": weight_sum,
        "weighting": weighting,
    }


def xai4heat_summary(
    records: Iterable[Mapping[str, Any]],
    *,
    fixed_reference_c: float = 20.0,
) -> dict[str, Any]:
    """Return the weighted model-sensitivity summary used by the paper."""

    fixed_reference_c = _validated_fixed_reference_c(fixed_reference_c)
    metrics = {
        "primary_supply_ambient": "fx_dynamic_ambient",
        "primary_supply_fixed_reference": "fx_fixed_reference",
        "primary_supply_return_integrated": "fx_primary_integrated",
        "secondary_supply_return_integrated": "fx_secondary_integrated",
        "primary_return_as_sink": "fx_primary_return_sink",
    }
    rows = [
        enrich_xai4heat_record(record, fixed_reference_c=fixed_reference_c)
        for record in records
    ]
    issue_counts: dict[str, int] = {}
    for record in rows:
        for issue in str(record.get("exergy_issues", "")).split(";"):
            if issue:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
    return {
        "schema_version": "1.0",
        "profile": "xai4heat",
        "intervals": len(rows),
        "fixed_reference_c": fixed_reference_c,
        "models": {
            name: _weighted_metric(rows, field) for name, field in metrics.items()
        },
        "issue_counts": issue_counts,
    }


def xai4heat_temperature_sensitivity(
    records: Iterable[Mapping[str, Any]],
    *,
    uncertainty_c: float = 0.5,
    fixed_reference_c: float = 20.0,
) -> dict[str, Any]:
    """Simple symmetric temperature perturbation sensitivity for the base model."""

    try:
        uncertainty_c = float(uncertainty_c)
    except (TypeError, ValueError) as exc:
        raise ValueError("uncertainty_c must be numeric") from exc
    if not math.isfinite(uncertainty_c) or uncertainty_c < 0.0:
        raise ValueError("uncertainty_c must be finite and nonnegative")
    fixed_reference_c = _validated_fixed_reference_c(fixed_reference_c)
    base_rows = []
    low_rows = []
    high_rows = []
    for raw in records:
        canonical = canonicalize_record(raw)
        supply = _optional_float(canonical, "primary_supply_temperature_c")
        ambient = _optional_float(canonical, "ambient_temperature_c")
        if supply is None or ambient is None:
            continue
        weight = _optional_float(canonical, "thermal_delivery")
        weight = max(0.0, weight) if weight is not None else None
        base = _try_factor(thermal_exergy_factor_c, supply, ambient)
        low = _try_factor(
            thermal_exergy_factor_c,
            supply - uncertainty_c,
            ambient + uncertainty_c,
        )
        high = _try_factor(
            thermal_exergy_factor_c,
            supply + uncertainty_c,
            ambient - uncertainty_c,
        )
        if base is None or low is None or high is None:
            continue
        base_rows.append({"fx": base, "thermal_delivery_weight": weight})
        low_rows.append({"fx": low, "thermal_delivery_weight": weight})
        high_rows.append({"fx": high, "thermal_delivery_weight": weight})
    base_value = _weighted_metric(base_rows, "fx")["weighted_factor"]
    low_value = _weighted_metric(low_rows, "fx")["weighted_factor"]
    high_value = _weighted_metric(high_rows, "fx")["weighted_factor"]
    return {
        "uncertainty_c": uncertainty_c,
        "fixed_reference_c": fixed_reference_c,
        "base_factor": base_value,
        "low_factor": low_value,
        "high_factor": high_value,
        "approximate_absolute_delta": (
            max(abs(base_value - low_value), abs(high_value - base_value))
            if None not in {base_value, low_value, high_value}
            else None
        ),
    }


def load_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        _validate_tabular_headers(reader.fieldnames or ())
        records: list[dict[str, str]] = []
        for row_number, row in enumerate(reader, start=2):
            surplus = row.get(None)
            if surplus is not None:
                raise ValueError(
                    f"tabular row {row_number} has "
                    f"{len(reader.fieldnames or ()) + len(surplus)} values but the "
                    f"header defines {len(reader.fieldnames or ())} columns"
                )
            records.append(row)
        return records


def write_csv(records: Iterable[Mapping[str, Any]], path: str | Path) -> Path:
    rows = list(records)
    if not rows:
        raise ValueError("cannot write an empty record collection")
    fields: list[str] = []
    for record in rows:
        for field in record:
            if field not in fields:
                fields.append(field)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(_spreadsheet_safe_value(field) for field in fields)
        for row in rows:
            writer.writerow(_spreadsheet_safe_value(row.get(field)) for field in fields)
    return target


def enrich_csv(
    input_path: str | Path,
    output_path: str | Path | None = None,
    *,
    profile: str = "xai4heat",
    fixed_reference_c: float = 20.0,
) -> list[dict[str, Any]]:
    if profile.lower() not in {"xai4heat", "district-heating", "district_heating"}:
        raise ValueError(
            "the first release supports xai4heat/district-heating CSV profiles"
        )
    enriched = enrich_xai4heat_records(
        load_csv(input_path), fixed_reference_c=fixed_reference_c
    )
    if output_path is not None:
        write_csv(enriched, output_path)
    return enriched
