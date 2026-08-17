"""Schema-driven adapters for user-owned local datasets."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping

from .ingestion import (
    FieldMapping,
    IngestionResult,
    MappingPlan,
    normalize_records,
    read_records,
)


def _positive_integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive one-based integer")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a positive one-based integer") from exc
    if not math.isfinite(number) or not number.is_integer() or number <= 0:
        raise ValueError(f"{name} must be a positive one-based integer")
    return int(number)


@dataclass(frozen=True)
class LocalDatasetAdapter:
    """Declarative instructions for a local file the user may lawfully access."""

    id: str
    source_name: str
    license_notice: str
    fields: tuple[FieldMapping, ...]
    source_url: str | None = None
    sheet_name: str | int = 0
    header_row: int = 1
    layout: str = "records"
    id_columns: tuple[str, ...] = ()
    year_column_pattern: str = r"^(?:19|20)\d{2}$"
    year_field: str = "year"
    value_field: str = "value"
    filters: Mapping[str, tuple[Any, ...]] = field(default_factory=dict)
    defaults: Mapping[str, Any] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    preserve_unmapped: bool = True
    notes: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("adapter id must not be empty")
        if not self.source_name.strip():
            raise ValueError("source_name must not be empty")
        if not self.license_notice.strip():
            raise ValueError("license_notice must not be empty")
        if self.layout not in {"records", "wide-years"}:
            raise ValueError("layout must be records or wide-years")
        object.__setattr__(
            self, "header_row", _positive_integer(self.header_row, "header_row")
        )
        try:
            re.compile(self.year_column_pattern)
        except re.error as exc:
            raise ValueError(
                "year_column_pattern must be a valid regular expression"
            ) from exc

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LocalDatasetAdapter":
        payload = {
            key: value for key, value in payload.items() if key != "schema_version"
        }
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError("unknown local-adapter fields: " + ", ".join(unknown))
        data = dict(payload)
        data["fields"] = tuple(FieldMapping(**item) for item in data.get("fields", ()))
        data["id_columns"] = tuple(str(item) for item in data.get("id_columns", ()))
        data["required"] = tuple(str(item) for item in data.get("required", ()))
        data["filters"] = {
            str(name): tuple(values if isinstance(values, (list, tuple)) else [values])
            for name, values in data.get("filters", {}).items()
        }
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "id": self.id,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "license_notice": self.license_notice,
            "sheet_name": self.sheet_name,
            "header_row": self.header_row,
            "layout": self.layout,
            "id_columns": list(self.id_columns),
            "year_column_pattern": self.year_column_pattern,
            "year_field": self.year_field,
            "value_field": self.value_field,
            "filters": {name: list(values) for name, values in self.filters.items()},
            "fields": [item.to_dict() for item in self.fields],
            "defaults": dict(self.defaults),
            "required": list(self.required),
            "preserve_unmapped": self.preserve_unmapped,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class LocalDatasetResult:
    adapter: LocalDatasetAdapter
    source_path: str
    source_sha256: str
    source_size_bytes: int
    source_records: tuple[Mapping[str, Any], ...]
    ingestion: IngestionResult
    warnings: tuple[str, ...] = ()

    @property
    def records(self) -> tuple[Mapping[str, Any], ...]:
        return self.ingestion.records

    def to_dict(self, *, include_records: bool = True) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "adapter": self.adapter.to_dict(),
            "source": {
                "path": self.source_path,
                "sha256": self.source_sha256,
                "size_bytes": self.source_size_bytes,
                "raw_record_count": len(self.source_records),
            },
            "ingestion": self.ingestion.to_dict(include_records=include_records),
            "warnings": list(self.warnings),
        }

    def export_xlsx(self, path: str) -> Any:
        from .excel import export_xlsx_ingestion

        return export_xlsx_ingestion(
            self.ingestion,
            path,
            source_records=self.source_records,
            metadata={
                "adapter_id": self.adapter.id,
                "source_name": self.adapter.source_name,
                "source_url": self.adapter.source_url,
                "license_notice": self.adapter.license_notice,
                "source_path": self.source_path,
                "source_sha256": self.source_sha256,
                "source_size_bytes": self.source_size_bytes,
                "adapter_notes": self.adapter.notes,
                "warnings": self.warnings,
            },
        )


_BUNDLED_ADAPTER_FILES = {
    "ei-total-energy-supply": "ei_total_energy_supply.json",
    "energy-institute-total-energy-supply-long-v1": "ei_total_energy_supply.json",
    "iea-ghg-energy": "iea_ghg_energy.json",
    "iea-ghg-energy-highlights-long-v1": "iea_ghg_energy.json",
}


def list_bundled_adapters() -> tuple[str, ...]:
    """Return the stable short names of installable local-data adapters."""

    return "ei-total-energy-supply", "iea-ghg-energy"


def load_bundled_adapter(name: str) -> LocalDatasetAdapter:
    """Load a field-only adapter distributed with the Python package."""

    key = str(name).strip().lower().replace("_", "-")
    if key.endswith(".json"):
        key = key[:-5]
    filename = _BUNDLED_ADAPTER_FILES.get(key)
    if filename is None:
        raise KeyError(
            f"unknown bundled adapter {name!r}; available adapters: "
            + ", ".join(list_bundled_adapters())
        )
    resource = (
        files("exergy_imperative")
        .joinpath("data")
        .joinpath("adapters")
        .joinpath(filename)
    )
    payload = json.loads(resource.read_text(encoding="utf-8"))
    return LocalDatasetAdapter.from_dict(payload)


def load_local_adapter(path: str | Path) -> LocalDatasetAdapter:
    source = Path(path)
    if not source.is_file():
        try:
            return load_bundled_adapter(str(path))
        except KeyError:
            raise FileNotFoundError(source) from None
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("local adapter must be a JSON object")
    payload = dict(payload)
    payload.pop("schema_version", None)
    return LocalDatasetAdapter.from_dict(payload)


def write_local_adapter(adapter: LocalDatasetAdapter, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(adapter.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination


def _filter_records(
    records: list[dict[str, Any]], filters: Mapping[str, tuple[Any, ...]]
) -> list[dict[str, Any]]:
    if not filters:
        return records
    missing = sorted(
        name for name in filters if records and all(name not in row for row in records)
    )
    if missing:
        raise ValueError("adapter filter columns are missing: " + ", ".join(missing))
    return [
        row
        for row in records
        if all(row.get(name) in allowed for name, allowed in filters.items())
    ]


def _reshape_wide_years(
    records: list[dict[str, Any]],
    adapter: LocalDatasetAdapter,
    *,
    schema_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    pattern = re.compile(adapter.year_column_pattern)
    columns_to_check = schema_records if schema_records is not None else records
    if columns_to_check and not any(
        pattern.fullmatch(str(name).strip()) for row in columns_to_check for name in row
    ):
        raise ValueError(
            "wide-years adapter found no year columns matching "
            f"{adapter.year_column_pattern!r}"
        )
    reshaped: list[dict[str, Any]] = []
    for row in records:
        year_columns = [
            (name, str(name).strip())
            for name in row
            if pattern.fullmatch(str(name).strip())
        ]
        year_names = {name for _, name in year_columns}
        id_columns = (
            adapter.id_columns
            if adapter.id_columns
            else tuple(str(name) for name in row if str(name).strip() not in year_names)
        )
        for raw_column, column in year_columns:
            value = row.get(raw_column)
            if value in {None, ""}:
                continue
            item = {name: row.get(name) for name in id_columns}
            item[adapter.year_field] = int(column)
            item[adapter.value_field] = value
            reshaped.append(item)
    return reshaped


def adapt_local_dataset(
    path: str | Path,
    adapter: LocalDatasetAdapter | Mapping[str, Any] | str | Path,
    *,
    missing_policy: str = "keep",
) -> LocalDatasetResult:
    """Read and normalize a local file without uploading or redistributing it."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    if isinstance(adapter, (str, Path)):
        definition = load_local_adapter(adapter)
    elif isinstance(adapter, LocalDatasetAdapter):
        definition = adapter
    else:
        definition = LocalDatasetAdapter.from_dict(adapter)
    raw = read_records(
        source,
        sheet_name=definition.sheet_name,
        header_row=definition.header_row,
    )
    selected = _filter_records(raw, definition.filters)
    if definition.layout == "wide-years":
        selected = _reshape_wide_years(selected, definition, schema_records=raw)
    mapping = MappingPlan(
        fields=definition.fields,
        defaults=definition.defaults,
        required=definition.required,
        preserve_unmapped=definition.preserve_unmapped,
    )
    ingestion = normalize_records(
        selected,
        mapping=mapping,
        missing_policy=missing_policy,
    )
    hasher = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    warnings = (
        "The source file remains local. The user is responsible for its licence, access rights, and permitted use.",
        "Adapter output preserves source identity and file hash but does not imply publisher endorsement.",
    )
    return LocalDatasetResult(
        adapter=definition,
        source_path=str(source.resolve()),
        source_sha256=digest,
        source_size_bytes=source.stat().st_size,
        source_records=tuple(dict(record) for record in raw),
        ingestion=ingestion,
        warnings=warnings,
    )
