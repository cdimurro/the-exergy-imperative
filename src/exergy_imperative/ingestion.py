"""Auditable ingestion for CSV, Excel, Parquet, JSON, and database records."""

from __future__ import annotations

import csv
import json
import math
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time
from datetime import timezone as datetime_timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .units import (
    SUPPORTED_ENERGY_UNITS,
    UnitError,
    canonical_energy_unit,
    convert_energy,
    energy_basis,
    parse_temperature,
)


def _column_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


_ALIASES: dict[str, tuple[str, ...]] = {
    "timestamp": (
        "timestamp",
        "datetime",
        "date time",
        "time",
        "interval start",
        "interval_start",
    ),
    "energy": (
        "energy",
        "energy use",
        "energy consumption",
        "fuel use",
        "electricity consumption",
        "thermal delivery",
        "heat delivered",
        "mwh",
        "kwh",
        "gj",
    ),
    "unit": ("unit", "energy unit", "energy_unit"),
    "carrier": ("carrier", "fuel", "energy carrier", "fuel type"),
    "technology": ("technology", "equipment", "asset type", "unit type"),
    "service": ("service", "useful service", "end use", "end-use"),
    "country": ("country", "location", "geography", "iso3", "country code"),
    "source_temperature": (
        "source temperature",
        "supply temperature",
        "supply temp",
        "temperature supply",
        "tsupply",
    ),
    "return_temperature": (
        "return temperature",
        "return temp",
        "temperature return",
        "treturn",
    ),
    "ambient_temperature": (
        "ambient temperature",
        "outside temperature",
        "outdoor temperature",
        "air temperature",
        "t2m",
    ),
    "cold_temperature": (
        "cold temperature",
        "cooling temperature",
        "chilled water temperature",
    ),
    "efficiency": ("efficiency", "thermal efficiency", "eta"),
    "cop": ("cop", "coefficient of performance"),
    "capital_cost": ("capital cost", "capex", "investment", "project cost"),
    "energy_price_per_mwh": (
        "energy price",
        "electricity price",
        "fuel price",
        "cost per mwh",
    ),
    "CO2_kg": ("co2 kg", "carbon dioxide kg", "kg co2"),
    "CH4_kg": ("ch4 kg", "methane kg", "kg ch4"),
    "N2O_kg": ("n2o kg", "nitrous oxide kg", "kg n2o"),
    "SO2_kg": ("so2 kg", "sulfur dioxide kg", "sulphur dioxide kg"),
    "NOx_kg": ("nox kg", "nitrogen oxides kg", "no2 kg"),
    "PM2.5_kg": ("pm2.5 kg", "pm25 kg", "fine particulate kg"),
    "CO_kg": ("co kg", "carbon monoxide kg"),
    "VOC_kg": ("voc kg", "nmvoc kg", "volatile organic compounds kg"),
}

_ALIAS_INDEX = {
    _column_key(alias): canonical
    for canonical, aliases in _ALIASES.items()
    for alias in (canonical, *aliases)
}
_GENERIC_ENERGY_ALIASES = {"energy", "mwh", "kwh", "gj"}
_MONETARY_HEADER_HINTS = (
    "cost",
    "price",
    "spend",
    "expense",
    "revenue",
    "budget",
    "tariff",
)
_NUMERIC_FIELDS = {
    "energy",
    "efficiency",
    "cop",
    "capital_cost",
    "energy_price_per_mwh",
    "CO2_kg",
    "CH4_kg",
    "N2O_kg",
    "SO2_kg",
    "NOx_kg",
    "PM2.5_kg",
    "CO_kg",
    "VOC_kg",
}
_TEMPERATURE_FIELDS = {
    "source_temperature",
    "return_temperature",
    "ambient_temperature",
    "cold_temperature",
}
_ENERGY_UNITS = SUPPORTED_ENERGY_UNITS


@dataclass(frozen=True)
class FieldMapping:
    source: str
    target: str
    unit: str | None = None
    multiplier: float = 1.0
    data_type: str | None = None

    def __post_init__(self) -> None:
        try:
            multiplier = float(self.multiplier)
        except (TypeError, ValueError) as exc:
            raise ValueError("mapping multiplier must be numeric") from exc
        if not math.isfinite(multiplier):
            raise ValueError("mapping multiplier must be finite")
        object.__setattr__(self, "multiplier", multiplier)

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "source": self.source,
                "target": self.target,
                "unit": self.unit,
                "multiplier": self.multiplier,
                "data_type": self.data_type,
            }.items()
            if value is not None
        }


@dataclass(frozen=True)
class MappingPlan:
    fields: tuple[FieldMapping, ...]
    defaults: Mapping[str, Any] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    timezone: str | None = None
    preserve_unmapped: bool = True
    missing_policy: str = "keep"

    def __post_init__(self) -> None:
        targets = [item.target for item in self.fields]
        duplicates = sorted({target for target in targets if targets.count(target) > 1})
        if duplicates:
            raise ValueError(
                "mapping targets must be unique; duplicate targets: "
                + ", ".join(duplicates)
            )
        if self.missing_policy not in {
            "keep",
            "drop",
            "raise",
            "forward-fill",
            "interpolate",
        }:
            raise ValueError(
                "missing_policy must be keep, drop, raise, forward-fill, or interpolate"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "fields": [item.to_dict() for item in self.fields],
            "defaults": dict(self.defaults),
            "required": list(self.required),
            "timezone": self.timezone,
            "preserve_unmapped": self.preserve_unmapped,
            "missing_policy": self.missing_policy,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MappingPlan":
        return cls(
            fields=tuple(FieldMapping(**item) for item in payload.get("fields", [])),
            defaults=dict(payload.get("defaults", {})),
            required=tuple(str(item) for item in payload.get("required", [])),
            timezone=str(payload["timezone"]) if payload.get("timezone") else None,
            preserve_unmapped=bool(payload.get("preserve_unmapped", True)),
            missing_policy=str(payload.get("missing_policy", "keep")),
        )


@dataclass(frozen=True)
class IngestionIssue:
    row: int | None
    field: str | None
    code: str
    message: str
    severity: str = "warning"

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in self.__dict__.items() if value is not None}


@dataclass(frozen=True)
class IngestionResult:
    raw_records: tuple[Mapping[str, Any], ...]
    records: tuple[Mapping[str, Any], ...]
    mapping: MappingPlan
    issues: tuple[IngestionIssue, ...]
    dropped_rows: tuple[int, ...] = ()
    missing_policy: str = "keep"

    @property
    def issue_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.issues:
            counts[issue.code] = counts.get(issue.code, 0) + 1
        return counts

    def to_dict(self, *, include_records: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": "1.0",
            "raw_record_count": len(self.raw_records),
            "normalized_record_count": len(self.records),
            "dropped_rows": list(self.dropped_rows),
            "missing_policy": self.missing_policy,
            "mapping": self.mapping.to_dict(),
            "issues": [item.to_dict() for item in self.issues],
            "issue_counts": self.issue_counts,
        }
        if include_records:
            result["records"] = [dict(item) for item in self.records]
        return _json_compatible(result)

    def export_excel_compatible(self, directory: str | Path) -> tuple[Path, ...]:
        return export_excel_compatible_bundle(self, directory)

    def export_xlsx(self, path: str | Path) -> Path:
        from .excel import export_xlsx_ingestion

        return export_xlsx_ingestion(self, path)


def _unit_from_header(header: str) -> str | None:
    basis_match = re.search(
        r"(?<![A-Za-z0-9])(HHV|LHV)(?![A-Za-z0-9])",
        header,
        flags=re.IGNORECASE,
    )
    compact = re.sub(r"[^A-Za-z0-9]+", "", header)
    basis = basis_match.group(1).upper() if basis_match else None
    if basis is None:
        compact_basis = re.search(r"(?:HHV|LHV)(?:[A-Za-z0-9]*)$", compact, re.I)
        basis = compact_basis.group(0)[:3].upper() if compact_basis else None
    for unit in sorted(_ENERGY_UNITS, key=len, reverse=True):
        if re.search(
            rf"(?<![A-Za-z0-9]){re.escape(unit)}(?![A-Za-z0-9])",
            header,
            flags=re.IGNORECASE,
        ):
            return f"{unit}_{basis}" if basis else unit
    for unit in sorted(_ENERGY_UNITS, key=len, reverse=True):
        suffix = f"{unit}{basis or ''}".lower()
        if compact.lower().endswith(suffix) or (
            basis
            and re.search(rf"{re.escape(unit)}{basis}[A-Za-z0-9]*$", compact, re.I)
        ):
            return f"{unit}_{basis}" if basis else unit
    return None


def _temperature_unit_from_header(header: str) -> str | None:
    lowered = header.strip().lower()
    pattern = r"(?:°|deg(?:ree)?s?|_|\(|\[|\s)(c|f|k)(?:\)|\]|\W|$)"
    if re.search(pattern, lowered):
        match = re.search(pattern, lowered)
        return match.group(1).upper() if match else None
    compact = _column_key(header)
    match = re.search(r"(?:temp|temperature)(c|f|k)$", compact)
    if match:
        return match.group(1).upper()
    return None


def _is_energy_rate_header(header: str) -> bool:
    lowered = header.strip().lower()
    separated_watt_hour = re.search(
        r"(?<![a-z0-9])(?:g|m|k)?w[\s-]+h(?![a-z0-9])", lowered
    )
    power_unit = (
        None
        if separated_watt_hour
        else re.search(r"(?<![a-z0-9])(?:gw|mw|kw|w)(?:e|th)?(?![a-z0-9])", lowered)
    )
    per_time = re.search(
        r"(?:/|\bper\s+)(?:s|sec(?:ond)?|min(?:ute)?|h|hr|hour|d|day|yr|year)s?\b",
        lowered,
    )
    inverse_time = re.search(
        r"\b(?:s|sec(?:ond)?|min(?:ute)?|h|hr|hour|d|day|yr|year)s?\s*(?:\^-?1|-1)\b",
        lowered,
    )
    return bool(power_unit or per_time or inverse_time)


def _is_percent_header(header: str) -> bool:
    return "%" in header or bool(
        re.search(r"\b(?:percent|percentage|pct)\b", header, flags=re.IGNORECASE)
    )


def _is_monetary_header(header: str) -> bool:
    key = _column_key(header)
    return any(hint in key for hint in _MONETARY_HEADER_HINTS) or any(
        symbol in header for symbol in "$€£¥"
    )


def infer_mapping(
    columns: Iterable[str],
    *,
    defaults: Mapping[str, Any] | None = None,
    required: Iterable[str] = (),
    timezone: str | None = None,
) -> MappingPlan:
    """Infer a deterministic mapping from common industrial column aliases."""

    mappings: list[FieldMapping] = []
    claimed: set[str] = set()
    for column in columns:
        key = _column_key(str(column))
        target = _ALIAS_INDEX.get(key)
        if target == "energy" and _is_monetary_header(str(column)):
            target = None
        if target is None:
            for alias, candidate in sorted(
                _ALIAS_INDEX.items(), key=lambda item: len(item[0]), reverse=True
            ):
                if len(alias) >= 5 and alias in key:
                    if candidate == "energy" and (
                        _is_monetary_header(str(column))
                        or (
                            alias in _GENERIC_ENERGY_ALIASES
                            and _unit_from_header(str(column)) is None
                        )
                    ):
                        continue
                    target = candidate
                    break
        if target is None:
            continue
        if target == "energy" and _is_energy_rate_header(str(column)):
            continue
        if target in claimed:
            existing = next(item.source for item in mappings if item.target == target)
            raise ValueError(
                f"columns {existing!r} and {str(column)!r} both infer target "
                f"{target!r}; provide an explicit mapping plan"
            )
        unit = None
        multiplier = 1.0
        if target == "energy":
            unit = _unit_from_header(str(column))
        elif target == "energy_price_per_mwh":
            unit = _unit_from_header(str(column))
            if unit is not None:
                multiplier = 1.0 / convert_energy(1.0, unit, "MWh")
        elif target in _TEMPERATURE_FIELDS:
            unit = _temperature_unit_from_header(str(column))
        elif target == "efficiency" and _is_percent_header(str(column)):
            unit = "%"
            multiplier = 0.01
        mappings.append(FieldMapping(str(column), target, unit, multiplier))
        claimed.add(target)
    return MappingPlan(
        fields=tuple(mappings),
        defaults=dict(defaults or {}),
        required=tuple(str(item) for item in required),
        timezone=timezone,
    )


def load_mapping(path: str | Path) -> MappingPlan:
    return MappingPlan.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def write_mapping(
    plan: MappingPlan,
    path: str | Path,
    *,
    missing_policy: str | None = None,
) -> None:
    effective_plan = (
        plan if missing_policy is None else replace(plan, missing_policy=missing_policy)
    )
    payload = effective_plan.to_dict()
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _coerce_float(value: Any, field_name: str) -> float:
    if isinstance(value, str):
        value = value.strip().replace(",", "")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _scaled_float(value: Any, multiplier: Any, field_name: str) -> float:
    number = _coerce_float(value, field_name)
    scale = _coerce_float(multiplier, f"{field_name} multiplier")
    scaled = number * scale
    if not math.isfinite(scaled):
        raise ValueError(f"{field_name} must be finite after scaling")
    return scaled


def _coerce_integer(value: Any, multiplier: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer, not a boolean")
    text_value = str(value).strip().replace(",", "")
    try:
        number = Decimal(text_value)
        scale = Decimal(str(multiplier))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if not number.is_finite() or not scale.is_finite():
        raise ValueError(f"{field_name} must be finite")
    scaled = number * scale
    if scaled != scaled.to_integral_value():
        raise ValueError(f"{field_name} must be an integer")
    return int(scaled)


def _coerce_boolean(value: Any, field_name: str) -> bool:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized not in {"true", "false", "yes", "no", "1", "0"}:
            raise ValueError(f"{field_name} must be boolean")
        return normalized in {"true", "yes", "1"}
    if isinstance(value, bool):
        return value
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be boolean") from exc
    if not number.is_finite() or number not in {Decimal(0), Decimal(1)}:
        raise ValueError(f"{field_name} must be boolean")
    return bool(number)


def _is_missing(value: Any) -> bool:
    if value is None or (isinstance(value, str) and not value.strip()):
        return True
    try:
        return not math.isfinite(value)
    except (TypeError, ValueError):
        return False


def _normalize_timestamp(value: Any, timezone: str | None) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None and timezone:
        try:
            zone = ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone {timezone!r}") from exc
        candidates = (
            parsed.replace(tzinfo=zone, fold=0),
            parsed.replace(tzinfo=zone, fold=1),
        )
        valid = tuple(
            candidate.astimezone(datetime_timezone.utc)
            .astimezone(zone)
            .replace(tzinfo=None)
            == parsed
            for candidate in candidates
        )
        if not any(valid):
            raise ValueError(
                f"nonexistent local timestamp {parsed.isoformat()!r} in {timezone!r}; "
                "supply an offset-aware timestamp"
            )
        if all(valid) and candidates[0].utcoffset() != candidates[1].utcoffset():
            raise ValueError(
                f"ambiguous local timestamp {parsed.isoformat()!r} in {timezone!r}; "
                "supply an offset-aware timestamp"
            )
        parsed = candidates[0] if valid[0] else candidates[1]
    return parsed.isoformat()


def normalize_records(
    records: Iterable[Mapping[str, Any]],
    *,
    mapping: MappingPlan | None = None,
    missing_policy: str | None = None,
) -> IngestionResult:
    """Normalize records while preserving the original rows separately.

    ``missing_policy`` may be ``keep``, ``drop``, ``raise``, ``forward-fill``,
    or ``interpolate``. Only fields declared in ``mapping.required`` determine
    whether a row is missing required data.
    """

    raw = tuple(dict(item) for item in records)
    if mapping is None:
        columns = tuple(dict.fromkeys(key for row in raw for key in row))
        mapping = infer_mapping(columns)
    effective_missing_policy = (
        mapping.missing_policy if missing_policy is None else missing_policy
    )
    if effective_missing_policy not in {
        "keep",
        "drop",
        "raise",
        "forward-fill",
        "interpolate",
    }:
        raise ValueError(
            "missing_policy must be keep, drop, raise, forward-fill, or interpolate"
        )
    if mapping.missing_policy != effective_missing_policy:
        mapping = replace(mapping, missing_policy=effective_missing_policy)
    missing_policy = effective_missing_policy
    mapped_sources = {item.source for item in mapping.fields}
    mapped_target_names = {item.target for item in mapping.fields}
    issues: list[IngestionIssue] = []
    normalized: list[dict[str, Any]] = []

    for row_number, source_row in enumerate(raw, start=1):
        target_row: dict[str, Any] = {}
        failed_targets: set[str] = set()
        mapped_targets: set[str] = set()
        if mapping.preserve_unmapped:
            target_row.update(
                {
                    key: value
                    for key, value in source_row.items()
                    if key not in mapped_sources and key not in mapped_target_names
                }
            )
        for item in mapping.fields:
            value = source_row.get(item.source)
            if _is_missing(value):
                continue
            try:
                if item.target in _TEMPERATURE_FIELDS:
                    if isinstance(value, str) and item.multiplier == 1.0:
                        value = parse_temperature(value, item.unit)
                    else:
                        scaled = _scaled_float(value, item.multiplier, item.target)
                        value = parse_temperature(scaled, item.unit)
                    target_row[item.target] = value
                    continue
                # Coercion, sensor scaling, and semantic conversion are distinct
                # stages.  Keep them composable so, for example, a scaled
                # Fahrenheit sensor is not mistaken for an unscaled Celsius
                # reading merely because its mapping declares a numeric type.
                if item.data_type == "number":
                    value = _coerce_float(value, item.target)
                elif item.data_type == "integer":
                    pass
                elif item.data_type == "boolean":
                    value = _coerce_boolean(value, item.target)
                elif item.data_type == "json":
                    value = json.loads(value) if isinstance(value, str) else value
                elif item.data_type == "string":
                    value = str(value)
                elif item.data_type is not None:
                    raise ValueError(
                        f"unsupported data_type {item.data_type!r} for {item.target}"
                    )

                if item.target == "timestamp":
                    value = _normalize_timestamp(value, mapping.timezone)
                elif item.data_type == "integer":
                    value = _coerce_integer(value, item.multiplier, item.target)
                elif item.data_type == "number" or item.target in _NUMERIC_FIELDS:
                    value = _scaled_float(value, item.multiplier, item.target)
                elif item.multiplier != 1.0:
                    value = _scaled_float(value, item.multiplier, item.target)
                target_row[item.target] = value
                mapped_targets.add(item.target)
            except (TypeError, ValueError, UnitError) as exc:
                failed_targets.add(item.target)
                target_row.pop(item.target, None)
                issues.append(
                    IngestionIssue(
                        row_number,
                        item.target,
                        "conversion_error",
                        str(exc),
                        "error",
                    )
                )

        for name, default in mapping.defaults.items():
            if name not in target_row and name not in failed_targets:
                target_row[name] = default

        if "energy" in target_row:
            header_energy_unit = (
                next(
                    (
                        item.unit
                        for item in mapping.fields
                        if item.target == "energy" and item.unit
                    ),
                    None,
                )
                if "energy" in mapped_targets
                else None
            )
            row_energy_unit = target_row.get("unit")
            energy_unit = header_energy_unit or row_energy_unit or "MWh"
            if header_energy_unit and not _is_missing(row_energy_unit):
                try:
                    header_scale = canonical_energy_unit(str(header_energy_unit))
                    row_scale = canonical_energy_unit(str(row_energy_unit))
                    header_basis = energy_basis(str(header_energy_unit))
                    row_basis = energy_basis(str(row_energy_unit))
                    if header_scale != row_scale or (
                        header_basis is not None
                        and row_basis is not None
                        and header_basis != row_basis
                    ):
                        raise UnitError(
                            f"energy header unit {header_energy_unit!r} conflicts "
                            f"with row unit {row_energy_unit!r}"
                        )
                    if header_basis is None and row_basis is not None:
                        energy_unit = row_energy_unit
                except UnitError as exc:
                    failed_targets.add("energy")
                    target_row.pop("energy", None)
                    issues.append(
                        IngestionIssue(
                            row_number,
                            "energy",
                            "unit_conflict",
                            str(exc),
                            "error",
                        )
                    )
        if "energy" in target_row:
            try:
                target_row["energy"] = convert_energy(
                    target_row["energy"], str(energy_unit), "MWh"
                )
                basis = energy_basis(str(energy_unit))
                target_row["unit"] = f"MWh_{basis}" if basis else "MWh"
            except (ValueError, UnitError) as exc:
                target_row.pop("energy", None)
                issues.append(
                    IngestionIssue(
                        row_number, "energy", "unit_error", str(exc), "error"
                    )
                )
        normalized.append(target_row)

    if missing_policy == "forward-fill":
        prior: dict[str, Any] = {}
        prior_units: dict[str, str] = {}
        for row_number, row in enumerate(normalized, start=1):
            for field_name in mapping.required:
                if _is_missing(row.get(field_name)) and field_name in prior:
                    if field_name == "energy" and not _is_missing(row.get("unit")):
                        try:
                            current_basis = energy_basis(str(row["unit"]))
                            prior_basis = energy_basis(prior_units[field_name])
                        except UnitError as exc:
                            issues.append(
                                IngestionIssue(
                                    row_number,
                                    field_name,
                                    "unit_error",
                                    str(exc),
                                    "error",
                                )
                            )
                            continue
                        if current_basis != prior_basis:
                            issues.append(
                                IngestionIssue(
                                    row_number,
                                    field_name,
                                    "basis_conflict",
                                    "Energy cannot be forward-filled across conflicting HHV/LHV bases.",
                                    "error",
                                )
                            )
                            continue
                    row[field_name] = prior[field_name]
                    if field_name == "energy":
                        row["unit"] = prior_units[field_name]
                    issues.append(
                        IngestionIssue(
                            row_number,
                            field_name,
                            "forward_filled",
                            "Filled from the previous available record.",
                        )
                    )
                elif not _is_missing(row.get(field_name)):
                    prior[field_name] = row[field_name]
                    if field_name == "energy":
                        prior_units[field_name] = str(row.get("unit", "MWh"))
    elif missing_policy == "interpolate":
        mappings_by_target = {item.target: item for item in mapping.fields}
        for field_name in mapping.required:
            field_mapping = mappings_by_target.get(field_name)
            declared_type = field_mapping.data_type if field_mapping else None
            is_numeric_field = (
                declared_type in {"number", "integer"}
                or field_name in _NUMERIC_FIELDS
                or field_name in _TEMPERATURE_FIELDS
            )
            if not is_numeric_field:
                continue
            known: list[tuple[int, int | float, str | None]] = []
            for index, row in enumerate(normalized):
                value = row.get(field_name)
                if _is_missing(value) or isinstance(value, bool):
                    continue
                if declared_type == "integer":
                    if not isinstance(value, int):
                        continue
                    numeric_value: int | float = value
                else:
                    if not isinstance(value, (int, float)):
                        continue
                    numeric_value = float(value)
                known.append(
                    (
                        index,
                        numeric_value,
                        str(row.get("unit", "MWh")) if field_name == "energy" else None,
                    )
                )
            for left, right in zip(known, known[1:]):
                left_index, left_value, left_unit = left
                right_index, right_value, right_unit = right
                gap = right_index - left_index
                for index in range(left_index + 1, right_index):
                    if _is_missing(normalized[index].get(field_name)):
                        if field_name == "energy":
                            row_unit = normalized[index].get("unit")
                            try:
                                left_basis = energy_basis(str(left_unit))
                                right_basis = energy_basis(str(right_unit))
                                row_basis = (
                                    energy_basis(str(row_unit))
                                    if not _is_missing(row_unit)
                                    else left_basis
                                )
                            except UnitError as exc:
                                issues.append(
                                    IngestionIssue(
                                        index + 1,
                                        field_name,
                                        "unit_error",
                                        str(exc),
                                        "error",
                                    )
                                )
                                continue
                            if len({left_basis, row_basis, right_basis}) > 1:
                                issues.append(
                                    IngestionIssue(
                                        index + 1,
                                        field_name,
                                        "basis_conflict",
                                        "Energy cannot be interpolated across conflicting HHV/LHV bases.",
                                        "error",
                                    )
                                )
                                continue
                        if declared_type == "integer":
                            offset = index - left_index
                            numerator = (
                                int(left_value) * (gap - offset)
                                + int(right_value) * offset
                            )
                            interpolated_integer, remainder = divmod(numerator, gap)
                            if remainder:
                                issues.append(
                                    IngestionIssue(
                                        index + 1,
                                        field_name,
                                        "interpolation_type_conflict",
                                        "Interpolation would produce a non-integer value for an integer field.",
                                        "error",
                                    )
                                )
                                continue
                            normalized[index][field_name] = interpolated_integer
                        else:
                            fraction = (index - left_index) / gap
                            interpolated = left_value + fraction * (
                                right_value - left_value
                            )
                            normalized[index][field_name] = interpolated
                        if field_name == "energy":
                            normalized[index]["unit"] = str(left_unit)
                        issues.append(
                            IngestionIssue(
                                index + 1,
                                field_name,
                                "interpolated",
                                "Linearly interpolated between adjacent records.",
                            )
                        )

    dropped: list[int] = []
    retained: list[dict[str, Any]] = []
    for row_number, row in enumerate(normalized, start=1):
        missing = [
            field_name
            for field_name in mapping.required
            if _is_missing(row.get(field_name))
        ]
        if not missing:
            retained.append(row)
            continue
        for field_name in missing:
            issues.append(
                IngestionIssue(
                    row_number,
                    field_name,
                    "missing_required",
                    "Required value is unavailable after preprocessing.",
                    "error" if missing_policy == "raise" else "warning",
                )
            )
        if missing_policy == "raise":
            raise ValueError(
                f"row {row_number} is missing required fields: {', '.join(missing)}"
            )
        if missing_policy == "drop":
            dropped.append(row_number)
        else:
            retained.append(row)

    return IngestionResult(
        raw_records=raw,
        records=tuple(retained),
        mapping=mapping,
        issues=tuple(issues),
        dropped_rows=tuple(dropped),
        missing_policy=missing_policy,
    )


def _validate_tabular_headers(fields: Sequence[Any]) -> None:
    """Reject headers that cannot be represented without losing columns."""

    blank_headers = [
        index + 1 for index, field in enumerate(fields) if _is_missing(field)
    ]
    labels = [str(field).strip() for field in fields]
    duplicate_headers = sorted(
        {label for label in labels if label and labels.count(label) > 1}
    )
    if blank_headers:
        raise ValueError(
            "tabular header names must not be empty; empty columns: "
            + ", ".join(str(index) for index in blank_headers)
        )
    if duplicate_headers:
        raise ValueError(
            "duplicate tabular headers are not supported: "
            + ", ".join(duplicate_headers)
        )


def read_records(
    path: str | Path,
    *,
    sheet_name: str | int = 0,
    header_row: int = 1,
) -> list[dict[str, Any]]:
    """Read tabular records, using pandas only for Excel and Parquet."""

    source = Path(path)
    suffix = source.suffix.lower()
    if isinstance(header_row, bool):
        raise ValueError("header_row must be a positive one-based integer")
    try:
        resolved_header_row = float(header_row)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("header_row must be a positive one-based integer") from exc
    if (
        not math.isfinite(resolved_header_row)
        or not resolved_header_row.is_integer()
        or resolved_header_row <= 0
    ):
        raise ValueError("header_row must be a positive one-based integer")
    header_number = int(resolved_header_row)
    if suffix in {".csv", ".tsv"}:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            delimiter = "\t" if suffix == ".tsv" else ","
            rows = list(csv.reader(handle, delimiter=delimiter))
        header_index = header_number - 1
        if header_index >= len(rows):
            raise ValueError("header_row exceeds the number of rows in the file")
        fields = rows[header_index]
        _validate_tabular_headers(fields)
        records: list[dict[str, Any]] = []
        for row_number, row in enumerate(
            rows[header_index + 1 :], start=header_index + 2
        ):
            if not any(value.strip() for value in row):
                continue
            if len(row) > len(fields):
                raise ValueError(
                    f"tabular row {row_number} has {len(row)} values but the "
                    f"header defines {len(fields)} columns"
                )
            record: dict[str, Any] = {
                field: row[index] if index < len(row) else None
                for index, field in enumerate(fields)
            }
            records.append(record)
        return records
    if suffix == ".json":
        payload = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [dict(item) for item in payload]
        if isinstance(payload, dict) and isinstance(payload.get("records"), list):
            return [dict(item) for item in payload["records"]]
        raise ValueError("JSON input must be an array or contain a records array")
    if suffix in {".jsonl", ".ndjson"}:
        return [
            json.loads(line)
            for line in source.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    if suffix in {".xlsx", ".xls", ".xlsb", ".parquet"}:
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ImportError(
                "Excel and Parquet ingestion require: pip install exergy-imperative[data]"
            ) from exc
        if suffix == ".parquet":
            frame = pd.read_parquet(source)
        else:
            # Read the selected row as data first.  Passing it directly as the
            # header lets pandas silently rename duplicate and blank cells
            # (for example ``Energy.1`` and ``Unnamed: 1``), which can make a
            # mapping target the wrong source column.
            header_probe = pd.read_excel(
                source,
                sheet_name=sheet_name,
                header=None,
                skiprows=header_number - 1,
                nrows=1,
            )
            if header_probe.empty:
                raise ValueError("header_row exceeds the number of rows in the file")
            _validate_tabular_headers(header_probe.iloc[0].tolist())
            frame = pd.read_excel(
                source,
                sheet_name=sheet_name,
                header=header_number - 1,
            )
        # Object dtype is required before replacing nulls.  Numeric pandas
        # columns otherwise coerce ``None`` straight back to NaN.
        return frame.astype(object).where(frame.notna(), None).to_dict(orient="records")
    raise ValueError(f"unsupported input format {suffix!r}")


def read_sql_records(
    connection: Any,
    query: str,
    parameters: Sequence[Any] = (),
) -> list[dict[str, Any]]:
    """Read from any PEP-249 connection without taking ownership of it."""

    cursor = connection.cursor()
    try:
        cursor.execute(query, tuple(parameters))
        columns = [str(item[0]) for item in cursor.description or ()]
        duplicate_columns = sorted(
            {column for column in columns if columns.count(column) > 1}
        )
        if duplicate_columns:
            raise ValueError(
                "duplicate SQL result columns are not supported; alias each "
                "selected column uniquely: " + ", ".join(duplicate_columns)
            )
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        cursor.close()


def read_sqlite_records(
    path: str | Path,
    query: str,
    parameters: Sequence[Any] = (),
) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"SQLite database does not exist: {source}")
    read_only_uri = source.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(read_only_uri, uri=True)) as connection:
        return read_sql_records(connection, query, parameters)


def write_records(records: Iterable[Mapping[str, Any]], path: str | Path) -> None:
    destination = Path(path)
    rows = [dict(item) for item in records]
    suffix = destination.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        columns = list(dict.fromkeys(key for row in rows for key in row))
        with destination.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t" if suffix == ".tsv" else ",")
            writer.writerow(_spreadsheet_safe_value(column) for column in columns)
            for row in rows:
                writer.writerow(
                    _spreadsheet_safe_value(row.get(column)) for column in columns
                )
        return
    if suffix == ".json":
        destination.write_text(
            json.dumps(_json_compatible(rows), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return
    if suffix in {".jsonl", ".ndjson"}:
        destination.write_text(
            "".join(
                json.dumps(_json_compatible(row), ensure_ascii=False) + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )
        return
    if suffix == ".xlsx":
        try:
            from openpyxl import Workbook
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError(
                "Excel output requires: pip install exergy-imperative[data]"
            ) from exc
        columns = list(dict.fromkeys(key for row in rows for key in row))
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Data"
        sheet.append([_spreadsheet_safe_value(column) for column in columns])
        for row in rows:
            sheet.append(
                [_spreadsheet_safe_value(row.get(column)) for column in columns]
            )
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        workbook.save(destination)
        return
    raise ValueError("output format must be CSV, TSV, XLSX, JSON, JSONL, or NDJSON")


def _spreadsheet_safe_value(value: Any) -> Any:
    """Serialize containers and neutralize formula-like spreadsheet text."""

    if (
        isinstance(value, (datetime, time))
        and value.tzinfo is not None
        and value.utcoffset() is not None
    ):
        value = value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _json_compatible(value: Any) -> Any:
    """Convert common tabular scalar types to deterministic JSON values."""

    if isinstance(value, Mapping):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        if value == value.to_integral_value():
            return int(value)
        return _json_compatible(float(value))
    if isinstance(value, float) and not math.isfinite(value):
        return None
    item_method = getattr(value, "item", None)
    if callable(item_method):
        converted = item_method()
        if converted is not value:
            return _json_compatible(converted)
    return value


def export_excel_compatible_bundle(
    result: IngestionResult,
    directory: str | Path,
) -> tuple[Path, ...]:
    """Write an auditable set of UTF-8 CSV/JSON files that opens in Excel."""

    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    raw_path = root / "raw_records.csv"
    normalized_path = root / "normalized_records.csv"
    issues_path = root / "data_quality_issues.csv"
    mapping_path = root / "mapping.json"
    write_records(result.raw_records, raw_path)
    write_records(result.records, normalized_path)
    write_records((item.to_dict() for item in result.issues), issues_path)
    write_mapping(
        result.mapping,
        mapping_path,
        missing_policy=result.missing_policy,
    )
    return raw_path, normalized_path, issues_path, mapping_path
