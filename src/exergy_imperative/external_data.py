"""Opt-in connectors and local normalizers for external public datasets.

No publisher values are bundled here. Network access and file writes occur only
when a caller invokes the corresponding function explicitly.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .ingestion import read_records

WORLD_BANK_DEFAULT_INDICATORS = (
    "FP.CPI.TOTL",
    "NY.GDP.DEFL.ZS",
    "PA.NUS.FCRF",
)
"""WDI indicators for inflation and currency normalization."""

ERA5_LAND_DEFAULT_VARIABLES = (
    "2m_temperature",
    "2m_dewpoint_temperature",
    "surface_solar_radiation_downwards",
    "total_precipitation",
)
"""Small, energy-relevant ERA5-Land variable set used by default."""

_WORLD_BANK_URL = "https://api.worldbank.org/v2"
_EDGAR_URL = "https://edgar.jrc.ec.europa.eu/dataset_ap81"
_EGRID_URL = "https://www.epa.gov/egrid/summary-data"
_IAC_URL = "https://itac.university/download"
_FIED_URL = "https://doi.org/10.25984/2437657"
_ERA5_URL = "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land"


@dataclass(frozen=True)
class DataIntegrationResult:
    """Normalized records plus enough source metadata for an audit trail."""

    dataset_id: str
    source_name: str
    source_url: str
    license_notice: str
    records: tuple[Mapping[str, Any], ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    source_path: str | None = None
    source_sha256: str | None = None
    source_size_bytes: int | None = None

    def to_dict(self, *, include_records: bool = True) -> dict[str, Any]:
        source: dict[str, Any] = {
            "name": self.source_name,
            "url": self.source_url,
            "license_notice": self.license_notice,
        }
        if self.source_path is not None:
            source.update(
                {
                    "path": self.source_path,
                    "sha256": self.source_sha256,
                    "size_bytes": self.source_size_bytes,
                }
            )
        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "dataset_id": self.dataset_id,
            "source": source,
            "record_count": len(self.records),
            "metadata": dict(self.metadata),
            "warnings": list(self.warnings),
        }
        if include_records:
            payload["records"] = [dict(item) for item in self.records]
        return payload


def _local_result(
    path: str | Path,
    *,
    dataset_id: str,
    source_name: str,
    source_url: str,
    license_notice: str,
    records: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
    warnings: Sequence[str],
) -> DataIntegrationResult:
    source = Path(path)
    fingerprint = _file_fingerprint(source)
    return DataIntegrationResult(
        dataset_id=dataset_id,
        source_name=source_name,
        source_url=source_url,
        license_notice=license_notice,
        records=tuple(dict(item) for item in records),
        metadata=dict(metadata),
        warnings=tuple(warnings),
        source_path=fingerprint["path"],
        source_sha256=fingerprint["sha256"],
        source_size_bytes=fingerprint["size_bytes"],
    )


def _file_fingerprint(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    hasher = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return {
        "path": str(source.resolve()),
        "sha256": hasher.hexdigest(),
        "size_bytes": source.stat().st_size,
    }


def _finite_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _optional_number(value: Any, field_name: str) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _finite_number(value, field_name)


def _optional_year(value: Any, field_name: str, *, minimum: int = 1) -> int | None:
    if value is None:
        return None
    number = _finite_number(value, field_name)
    if isinstance(value, bool) or not number.is_integer() or number < minimum:
        qualifier = f" of {minimum} or later"
        raise ValueError(f"{field_name} must be a whole calendar year{qualifier}")
    return int(number)


_SUBSCRIPT_TRANSLATION = str.maketrans("₀₁₂₃₄₅₆₇₈₉ₓ", "0123456789x")


def _header_key(value: Any) -> str:
    text = str(value).translate(_SUBSCRIPT_TRANSLATION).strip().lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def _column_index(records: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in records:
        for column in row:
            result.setdefault(_header_key(column), str(column))
    return result


def _find_column(
    records: Sequence[Mapping[str, Any]],
    candidates: Sequence[str],
    *,
    override: str | None = None,
    required: bool = False,
    label: str,
) -> str | None:
    available = _column_index(records)
    if override is not None:
        selected = available.get(_header_key(override))
        if selected is None:
            raise ValueError(f"configured {label} column {override!r} is missing")
        return selected
    for candidate in candidates:
        selected = available.get(_header_key(candidate))
        if selected is not None:
            return selected
    if required:
        raise ValueError(
            f"could not identify the {label} column; pass columns={{'{label}': 'source column'}}"
        )
    return None


def _parse_iso_date(value: str, field_name: str) -> date:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD") from exc


def fetch_world_bank_indicators(
    country: str,
    *,
    indicators: Sequence[str] = WORLD_BANK_DEFAULT_INDICATORS,
    start_year: int | None = None,
    end_year: int | None = None,
    cache_dir: str | Path | None = None,
    timeout: float = 30.0,
    retries: int = 2,
) -> DataIntegrationResult:
    """Fetch WDI observations using the World Bank's unauthenticated API.

    This is an explicit opt-in to network access. The defaults provide CPI, GDP
    deflator, and official exchange-rate series useful for economic scenarios.
    """

    country_id = str(country).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{2,10}", country_id):
        raise ValueError("country must be a World Bank country or aggregate code")
    requested = tuple(dict.fromkeys(str(item).strip().upper() for item in indicators))
    if not requested:
        raise ValueError("at least one World Bank indicator is required")
    if any(not re.fullmatch(r"[A-Z0-9_.-]+", item) for item in requested):
        raise ValueError("World Bank indicator IDs contain unsupported characters")
    resolved_start_year = _optional_year(start_year, "start_year", minimum=1960)
    resolved_end_year = _optional_year(end_year, "end_year", minimum=1960)
    if (
        resolved_start_year is not None
        and resolved_end_year is not None
        and resolved_start_year > resolved_end_year
    ):
        raise ValueError("start_year must be on or before end_year")
    retry_number = _finite_number(retries, "retries")
    if isinstance(retries, bool) or not retry_number.is_integer() or retry_number < 0:
        raise ValueError("retries must be a non-negative integer")
    retry_count = int(retry_number)

    cache_key = json.dumps(
        [country_id, requested, resolved_start_year, resolved_end_year],
        separators=(",", ":"),
    )
    cache_path: Path | None = None
    if cache_dir is not None:
        root = Path(cache_dir)
        root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:20]
        cache_path = root / f"world-bank-wdi-{digest}.json"
        if cache_path.exists():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            return DataIntegrationResult(
                dataset_id=payload["dataset_id"],
                source_name=payload["source"]["name"],
                source_url=payload["source"]["url"],
                license_notice=payload["source"]["license_notice"],
                records=tuple(payload["records"]),
                metadata=payload["metadata"],
                warnings=tuple(payload["warnings"]),
            )

    observations: list[dict[str, Any]] = []
    source_urls: list[str] = []
    for indicator_id in requested:
        parameters: dict[str, Any] = {"format": "json", "per_page": 20000}
        if resolved_start_year is not None or resolved_end_year is not None:
            lower = resolved_start_year if resolved_start_year is not None else 1960
            upper = (
                resolved_end_year
                if resolved_end_year is not None
                else datetime.now().year
            )
            parameters["date"] = f"{lower}:{upper}"
        url = (
            f"{_WORLD_BANK_URL}/country/{quote(country_id)}/indicator/"
            f"{quote(indicator_id)}?{urlencode(parameters)}"
        )
        source_urls.append(url)
        request = Request(url, headers={"User-Agent": "exergy-imperative/0.2"})
        payload: Any = None
        last_error: Exception | None = None
        for attempt in range(retry_count + 1):
            try:
                with urlopen(  # noqa: S310 - fixed World Bank endpoint
                    request, timeout=timeout
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                last_error = None
                break
            except HTTPError as exc:
                last_error = exc
                if exc.code not in {429, 500, 502, 503, 504}:
                    raise ConnectionError(
                        f"World Bank API returned HTTP {exc.code} for {indicator_id}"
                    ) from exc
            except URLError as exc:
                last_error = exc
            if attempt < retry_count:
                time.sleep(0.5 * (2**attempt))
        if last_error is not None:
            raise ConnectionError(
                f"World Bank API is temporarily unavailable for {indicator_id} "
                f"after {retry_count + 1} attempts"
            ) from last_error
        if isinstance(payload, Mapping) and payload.get("message"):
            raise ValueError(
                f"World Bank API rejected {indicator_id}: {payload['message']}"
            )
        if not isinstance(payload, list) or len(payload) < 2:
            raise ValueError(f"unexpected World Bank API response for {indicator_id}")
        for item in payload[1] or ():
            if item.get("value") is None:
                continue
            observations.append(
                {
                    "country_id": item.get("countryiso3code") or country_id,
                    "country_name": (item.get("country") or {}).get("value"),
                    "indicator_id": (item.get("indicator") or {}).get("id")
                    or indicator_id,
                    "indicator_name": (item.get("indicator") or {}).get("value"),
                    "year": int(item["date"]),
                    "value": _finite_number(item["value"], "World Bank value"),
                    "unit": item.get("unit") or None,
                    "observation_status": item.get("obs_status") or None,
                }
            )
    observations.sort(key=lambda row: (row["indicator_id"], row["year"]))
    result = DataIntegrationResult(
        dataset_id="world-bank-wdi",
        source_name="World Development Indicators",
        source_url="https://datacatalog.worldbank.org/search/dataset/0037712",
        license_notice="CC BY 4.0; retain World Bank attribution.",
        records=tuple(observations),
        metadata={
            "country_requested": country_id,
            "indicators_requested": list(requested),
            "start_year": resolved_start_year,
            "end_year": resolved_end_year,
            "api_urls": source_urls,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        },
        warnings=(
            "Indicator values are contextual economic data, not site-specific prices.",
            "Confirm price year, currency basis, and conversion method before using values in investment decisions.",
        ),
    )
    if cache_path is not None:
        cache_path.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return result


def build_era5_land_requests(
    latitude: float,
    longitude: float,
    start: str,
    end: str,
    *,
    variables: Sequence[str] = ERA5_LAND_DEFAULT_VARIABLES,
    data_format: str = "netcdf",
) -> tuple[dict[str, Any], ...]:
    """Build deterministic monthly CDS requests without network access."""

    lat = _finite_number(latitude, "latitude")
    lon = _finite_number(longitude, "longitude")
    if not -90 <= lat <= 90:
        raise ValueError("latitude must be between -90 and 90")
    if not -180 <= lon <= 180:
        raise ValueError("longitude must be between -180 and 180")
    start_date = _parse_iso_date(start, "start")
    end_date = _parse_iso_date(end, "end")
    if start_date > end_date:
        raise ValueError("start must be on or before end")
    selected = tuple(dict.fromkeys(str(item).strip() for item in variables))
    if not selected or any(not re.fullmatch(r"[a-z0-9_]+", item) for item in selected):
        raise ValueError("ERA5-Land variables must be lower-case CDS variable IDs")
    output_format = str(data_format).strip().lower()
    if output_format not in {"netcdf", "grib"}:
        raise ValueError("data_format must be netcdf or grib")

    requests: list[dict[str, Any]] = []
    cursor = date(start_date.year, start_date.month, 1)
    while cursor <= end_date:
        month_end = date(
            cursor.year,
            cursor.month,
            calendar.monthrange(cursor.year, cursor.month)[1],
        )
        first_day = max(start_date, cursor).day
        last_day = min(end_date, month_end).day
        requests.append(
            {
                "dataset": "reanalysis-era5-land",
                "request": {
                    "variable": list(selected),
                    "year": [str(cursor.year)],
                    "month": [f"{cursor.month:02d}"],
                    "day": [f"{day:02d}" for day in range(first_day, last_day + 1)],
                    "time": [f"{hour:02d}:00" for hour in range(24)],
                    "area": [lat, lon, lat, lon],
                    "data_format": output_format,
                    "download_format": "unarchived",
                },
                "suggested_filename": (
                    f"era5-land-{lat:+.4f}-{lon:+.4f}-{cursor:%Y%m}."
                    + ("nc" if output_format == "netcdf" else "grib")
                ),
            }
        )
        cursor = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )
    return tuple(requests)


def retrieve_era5_land(
    latitude: float,
    longitude: float,
    start: str,
    end: str,
    target_dir: str | Path,
    *,
    variables: Sequence[str] = ERA5_LAND_DEFAULT_VARIABLES,
    data_format: str = "netcdf",
    overwrite: bool = False,
    client: Any | None = None,
) -> dict[str, Any]:
    """Retrieve monthly ERA5-Land files after explicit CDS authentication.

    The caller must configure a CDS token and accept the dataset terms first.
    Existing files act as a local cache unless ``overwrite`` is true.
    """

    requests = build_era5_land_requests(
        latitude,
        longitude,
        start,
        end,
        variables=variables,
        data_format=data_format,
    )
    if client is None:
        try:
            import cdsapi
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ImportError(
                'ERA5 retrieval requires `pip install "exergy-imperative[climate]"`'
            ) from exc
        client = cdsapi.Client()
    root = Path(target_dir)
    root.mkdir(parents=True, exist_ok=True)
    outputs: list[dict[str, Any]] = []
    for item in requests:
        destination = root / item["suggested_filename"]
        if destination.exists() and not overwrite:
            status = "cached"
        else:
            client.retrieve(item["dataset"], item["request"], str(destination))
            status = "downloaded"
        outputs.append(
            {
                "path": str(destination.resolve()),
                "status": status,
                "request": item,
            }
        )
    return {
        "schema_version": "1.0",
        "dataset_id": "era5-land",
        "source": {
            "name": "ERA5-Land hourly data",
            "url": _ERA5_URL,
            "license_notice": "Copernicus C3S/ECMWF CC BY 4.0 attribution applies.",
        },
        "outputs": outputs,
        "warnings": [
            "ERA5-Land is reanalysis/model output; it is not a site measurement.",
            "The nearest model grid and local terrain may differ from site conditions.",
        ],
    }


_EDGAR_YEAR = re.compile(r"^(?:Y[_ -]?)?((?:19|20)\d{2})$", re.IGNORECASE)


def _edgar_metadata(
    path: Path, sheet_name: str | int
) -> tuple[str | None, str | None, str | None]:
    if path.suffix.lower() not in {".xlsx", ".xls", ".xlsb"}:
        return None, None, None
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ImportError(
            'EDGAR Excel ingestion requires `pip install "exergy-imperative[data]"`'
        ) from exc
    frame = pd.read_excel(path, sheet_name=sheet_name, header=None, nrows=9)
    values: dict[str, str] = {}
    for row in frame.astype(object).where(frame.notna(), None).values.tolist():
        if len(row) >= 2 and row[0] is not None and row[1] is not None:
            values[str(row[0]).strip().rstrip(":").lower()] = str(row[1]).strip()
    return values.get("compound"), values.get("unit"), values.get("reference")


def _emissions_multiplier(source_unit: str) -> float:
    key = re.sub(r"\s+", "", source_unit).lower().replace("per", "/")
    key = key.replace("yr", "year")
    if key in {"gg", "gg/year", "kt", "kt/year", "kton", "kton/year"}:
        return 1_000_000.0
    if key in {"mg", "mg/year", "t", "t/year", "tonne", "tonne/year"}:
        return 1_000.0
    if key in {"kg", "kg/year"}:
        return 1.0
    raise ValueError(
        "unsupported EDGAR emissions unit; use Gg/year, kt/year, tonne/year, or kg/year"
    )


def load_edgar_inventory(
    path: str | Path,
    *,
    pollutant: str | None = None,
    sheet_name: str | int = "IPCC 2006",
    header_row: int | None = None,
    source_unit: str = "auto",
    start_year: int | None = None,
    end_year: int | None = None,
    columns: Mapping[str, str] | None = None,
) -> DataIntegrationResult:
    """Normalize a user-downloaded EDGAR country/sector time-series workbook."""

    source = Path(path)
    metadata_pollutant, metadata_unit, reference = _edgar_metadata(source, sheet_name)
    resolved_header = header_row
    if resolved_header is None:
        resolved_header = (
            10 if source.suffix.lower() in {".xlsx", ".xls", ".xlsb"} else 1
        )
    rows = read_records(source, sheet_name=sheet_name, header_row=resolved_header)
    if not rows:
        raise ValueError("EDGAR source contains no data records")
    overrides = dict(columns or {})
    country_iso = _find_column(
        rows,
        ("Country_code_A3", "country_iso3", "iso3"),
        override=overrides.get("country_iso3"),
        required=True,
        label="country_iso3",
    )
    country_name = _find_column(
        rows,
        ("Name", "country", "country_name"),
        override=overrides.get("country_name"),
        label="country_name",
    )
    pollutant_column = _find_column(
        rows,
        ("Substance", "pollutant", "gas"),
        override=overrides.get("pollutant"),
        label="pollutant",
    )
    sector_code = _find_column(
        rows,
        (
            "ipcc_code_2006_for_standard_report",
            "ipcc_code_1996_for_standard_report",
            "sector_code",
            "sector",
        ),
        override=overrides.get("sector_code"),
        label="sector_code",
    )
    sector_name = _find_column(
        rows,
        (
            "ipcc_code_2006_for_standard_report_name",
            "ipcc_code_1996_for_standard_report_name",
            "sector_name",
        ),
        override=overrides.get("sector_name"),
        label="sector_name",
    )
    fossil_bio = _find_column(
        rows,
        ("fossil_bio", "fossil or biogenic"),
        override=overrides.get("fossil_bio"),
        label="fossil_bio",
    )
    resolved_pollutant = str(pollutant or metadata_pollutant or "").strip()
    if not resolved_pollutant and pollutant_column is None:
        raise ValueError(
            "pollutant could not be inferred; pass pollutant='NOx', for example"
        )
    resolved_unit = metadata_unit if source_unit == "auto" else source_unit
    if not resolved_unit:
        raise ValueError(
            "source_unit could not be inferred; pass source_unit explicitly"
        )
    multiplier = _emissions_multiplier(resolved_unit)
    resolved_start_year = _optional_year(start_year, "start_year")
    resolved_end_year = _optional_year(end_year, "end_year")
    if (
        resolved_start_year is not None
        and resolved_end_year is not None
        and resolved_start_year > resolved_end_year
    ):
        raise ValueError("start_year must be on or before end_year")

    normalized: list[dict[str, Any]] = []
    for row_number, row in enumerate(rows, start=resolved_header + 1):
        row_pollutant = str(row.get(pollutant_column) or resolved_pollutant).strip()
        if pollutant and row_pollutant.lower() != str(pollutant).strip().lower():
            continue
        for raw_column, value in row.items():
            match = _EDGAR_YEAR.fullmatch(str(raw_column).strip())
            if not match or value is None or value == "":
                continue
            year = int(match.group(1))
            if resolved_start_year is not None and year < resolved_start_year:
                continue
            if resolved_end_year is not None and year > resolved_end_year:
                continue
            source_value = _finite_number(value, f"EDGAR row {row_number} {raw_column}")
            normalized.append(
                {
                    "country_iso3": str(row.get(country_iso) or "").strip(),
                    "country_name": row.get(country_name) if country_name else None,
                    "sector_code": row.get(sector_code) if sector_code else None,
                    "sector_name": row.get(sector_name) if sector_name else None,
                    "fossil_or_biogenic": row.get(fossil_bio) if fossil_bio else None,
                    "pollutant": row_pollutant,
                    "year": year,
                    "source_value": source_value,
                    "source_unit": resolved_unit,
                    "emissions_kg_per_year": source_value * multiplier,
                }
            )
    if not normalized:
        raise ValueError("EDGAR source produced no observations for the selected years")
    return _local_result(
        source,
        dataset_id="edgar",
        source_name="EDGAR emissions inventory",
        source_url=_EDGAR_URL,
        license_notice="EDGAR source acknowledgement is required; dataset-specific and upstream terms apply.",
        records=normalized,
        metadata={
            "pollutant": resolved_pollutant or None,
            "sheet_name": sheet_name,
            "header_row": resolved_header,
            "source_unit": resolved_unit,
            "reference": reference,
            "start_year": resolved_start_year,
            "end_year": resolved_end_year,
        },
        warnings=(
            "Inventory mass is not ambient concentration, exposure, or clinical risk.",
            "EDGAR energy-sector activity may include upstream data subject to additional use conditions; review the selected release terms.",
        ),
    )


_EGRID_FACTORS = (
    "CO2",
    "CH4",
    "N2O",
    "CO2e",
    "NOx",
    "ozone_season_NOx",
    "SO2",
    "PM2.5",
    "NH3",
    "VOC",
)


def _egrid_summary_rows(
    path: Path, geography: str, basis: str, rate_multiplier: float
) -> tuple[list[dict[str, Any]], int | None]:
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ImportError(
            'eGRID Excel ingestion requires `pip install "exergy-imperative[data]"`'
        ) from exc
    if geography == "state" and basis != "total":
        raise ValueError("the eGRID summary workbook has only total state rates")
    sheet = "Table 1" if geography == "subregion" else "Table 3"
    frame = pd.read_excel(path, sheet_name=sheet, header=None)
    raw = frame.astype(object).where(frame.notna(), None).values.tolist()
    title = str(raw[0][1]) if raw and len(raw[0]) > 1 else ""
    match = re.search(r"eGRID\s*(\d{4})", title, re.IGNORECASE)
    year = int(match.group(1)) if match else None
    normalized: list[dict[str, Any]] = []
    start = 2 if geography == "state" else 3 if basis == "total" else 10
    for row in raw[4:]:
        if len(row) <= start or row[1] is None:
            continue
        code = str(row[1]).strip()
        if geography == "subregion" and not re.fullmatch(r"[A-Z]{4}|U\.S\.", code):
            continue
        if geography == "state" and not re.fullmatch(r"[A-Z]{2}|U\.S\.", code):
            continue
        factors = {
            "CO2": row[start],
            "CH4": row[start + 1],
            "N2O": row[start + 2],
            "CO2e": row[start + 3],
            "NOx": row[start + 4],
            "ozone_season_NOx": row[start + 5],
            "SO2": row[start + 6],
        }
        item: dict[str, Any] = {
            "geography_type": geography,
            "geography_code": code,
            "geography_name": row[2] if geography == "subregion" else code,
            "year": year,
            "basis": basis,
        }
        for factor, value in factors.items():
            if value is not None:
                source_value = _finite_number(value, f"eGRID {code} {factor}")
                item[f"{factor}_kg_per_mwh"] = source_value * rate_multiplier
                item[f"{factor}_source_value"] = source_value
        if geography == "subregion" and len(row) > 17 and row[17] is not None:
            item["grid_gross_loss_fraction"] = _finite_number(
                row[17], f"eGRID {code} grid loss"
            )
        normalized.append(item)
    return normalized, year


def _egrid_rate_multiplier(rate_unit: str, columns: Sequence[str]) -> tuple[float, str]:
    selected = str(rate_unit).strip().lower().replace(" ", "")
    if selected == "auto":
        joined = " ".join(str(item).lower() for item in columns)
        if "lb/mwh" in joined or "lb per mwh" in joined:
            selected = "lb/mwh"
        elif "kg/mwh" in joined or "kg per mwh" in joined:
            selected = "kg/mwh"
        else:
            raise ValueError(
                "eGRID rate unit could not be inferred; pass rate_unit='lb/MWh' or 'kg/MWh'"
            )
    if selected in {"lb/mwh", "lbs/mwh"}:
        return 0.45359237, "lb/MWh"
    if selected == "kg/mwh":
        return 1.0, "kg/MWh"
    raise ValueError("rate_unit must be auto, lb/MWh, or kg/MWh")


def load_egrid_emission_rates(
    path: str | Path,
    *,
    geography: str = "subregion",
    basis: str = "total",
    sheet_name: str | int | None = None,
    header_row: int | None = None,
    rate_unit: str = "auto",
    year: int | None = None,
    columns: Mapping[str, str] | None = None,
) -> DataIntegrationResult:
    """Normalize EPA eGRID output emission rates to kg/MWh."""

    source = Path(path)
    resolved_geography = str(geography).strip().lower()
    resolved_basis = str(basis).strip().lower().replace("_", "-")
    if resolved_geography not in {"subregion", "state"}:
        raise ValueError("geography must be subregion or state")
    if resolved_basis not in {"total", "non-baseload"}:
        raise ValueError("basis must be total or non-baseload")
    official_summary = (
        source.suffix.lower() in {".xlsx", ".xls"}
        and sheet_name is None
        and header_row is None
        and not columns
    )
    if official_summary:
        if str(rate_unit).strip().lower() == "auto":
            summary_multiplier, resolved_rate_unit = 0.45359237, "lb/MWh"
        else:
            summary_multiplier, resolved_rate_unit = _egrid_rate_multiplier(
                rate_unit, ()
            )
        normalized, inferred_year = _egrid_summary_rows(
            source, resolved_geography, resolved_basis, summary_multiplier
        )
    else:
        rows = read_records(
            source,
            sheet_name=sheet_name if sheet_name is not None else 0,
            header_row=header_row or 1,
        )
        if not rows:
            raise ValueError("eGRID source contains no data records")
        overrides = dict(columns or {})
        location = _find_column(
            rows,
            (
                "eGRID subregion acronym",
                "subregion",
                "subregion code",
                "state",
                "geography_code",
            ),
            override=overrides.get("geography_code"),
            required=True,
            label="geography_code",
        )
        name_column = _find_column(
            rows,
            ("eGRID subregion name", "subregion name", "geography_name"),
            override=overrides.get("geography_name"),
            label="geography_name",
        )
        aliases = {
            "CO2": (
                "CO2",
                "CO2 (kg/MWh)",
                "CO2 (lb/MWh)",
                "SRCO2RTA",
                "CO2 output emission rate",
            ),
            "CH4": (
                "CH4",
                "CH4 (kg/MWh)",
                "CH4 (lb/MWh)",
                "SRCH4RTA",
                "CH4 output emission rate",
            ),
            "N2O": (
                "N2O",
                "N2O (kg/MWh)",
                "N2O (lb/MWh)",
                "SRN2ORTA",
                "N2O output emission rate",
            ),
            "CO2e": (
                "CO2e",
                "CO2e (kg/MWh)",
                "CO2e (lb/MWh)",
                "SRCO2ERTA",
                "CO2 equivalent output emission rate",
            ),
            "NOx": (
                "Annual NOx",
                "NOx",
                "NOx (kg/MWh)",
                "NOx (lb/MWh)",
                "SRNOXRTA",
            ),
            "ozone_season_NOx": (
                "Ozone Season NOx",
                "Ozone Season NOx (kg/MWh)",
                "Ozone Season NOx (lb/MWh)",
                "SROZNNOXRTA",
            ),
            "SO2": (
                "SO2",
                "SO2 (kg/MWh)",
                "SO2 (lb/MWh)",
                "SRSO2RTA",
            ),
            "PM2.5": (
                "PM2.5",
                "PM2.5 (kg/MWh)",
                "PM2.5 (lb/MWh)",
                "PM25",
                "SRPM25RTA",
            ),
            "NH3": (
                "NH3",
                "NH3 (kg/MWh)",
                "NH3 (lb/MWh)",
                "SRNH3RTA",
            ),
            "VOC": (
                "VOC",
                "VOC (kg/MWh)",
                "VOC (lb/MWh)",
                "NMVOC",
                "SRVOCRTA",
            ),
        }
        factor_columns = {
            factor: _find_column(
                rows,
                candidates,
                override=overrides.get(factor),
                label=factor,
            )
            for factor, candidates in aliases.items()
        }
        if not any(factor_columns.values()):
            raise ValueError("could not identify any eGRID emission-rate columns")
        multiplier, resolved_rate_unit = _egrid_rate_multiplier(
            rate_unit, list(_column_index(rows).values())
        )
        inferred_year = year
        normalized = []
        for row_number, row in enumerate(rows, start=(header_row or 1) + 1):
            code = str(row.get(location) or "").strip()
            if not code:
                continue
            item = {
                "geography_type": resolved_geography,
                "geography_code": code,
                "geography_name": row.get(name_column) if name_column else code,
                "year": year,
                "basis": resolved_basis,
            }
            for factor, column in factor_columns.items():
                if column is None or row.get(column) in {None, ""}:
                    continue
                source_value = _finite_number(
                    row[column], f"eGRID row {row_number} {factor}"
                )
                item[f"{factor}_kg_per_mwh"] = source_value * multiplier
                item[f"{factor}_source_value"] = source_value
            normalized.append(item)
    if not normalized:
        raise ValueError("eGRID source produced no emission-rate records")
    resolved_year = _optional_year(year, "year") if year is not None else inferred_year
    if resolved_year is not None:
        for item in normalized:
            item["year"] = int(resolved_year)
    return _local_result(
        source,
        dataset_id="egrid",
        source_name="EPA eGRID",
        source_url=_EGRID_URL,
        license_notice="United States government public data; cite EPA eGRID and the selected release.",
        records=normalized,
        metadata={
            "geography": resolved_geography,
            "basis": resolved_basis,
            "year": resolved_year,
            "source_rate_unit": resolved_rate_unit,
            "normalized_rate_unit": "kg/MWh",
            "factors_supported": list(_EGRID_FACTORS),
        },
        warnings=(
            "Total output rates are attributional grid averages; non-baseload rates are a screening proxy, not a dispatch model.",
            "Air-pollutant rates are inventory factors and do not estimate local exposure or health outcomes.",
            "eGRID covers the United States and should not be treated as a global electricity default.",
        ),
    )


def load_iac_recommendations(
    path: str | Path,
    *,
    assessment_path: str | Path | None = None,
    recommendation_sheet: str | int = "RECC",
    assessment_sheet: str | int = "ASSESS",
    implemented_only: bool = False,
    include_assessment_data: bool = True,
) -> DataIntegrationResult:
    """Normalize the public DOE ITAC/IAC recommendation database."""

    source = Path(path)
    recommendation_rows = read_records(
        source,
        sheet_name=recommendation_sheet
        if source.suffix.lower() in {".xlsx", ".xls", ".xlsb"}
        else 0,
        header_row=1,
    )
    if not recommendation_rows:
        raise ValueError("ITAC/IAC source contains no recommendation records")
    available = _column_index(recommendation_rows)
    required = ("ID", "AR_NUMBER", "ARC2")
    missing = [name for name in required if _header_key(name) not in available]
    if missing:
        raise ValueError(
            "ITAC/IAC recommendation columns are missing: " + ", ".join(missing)
        )

    assessment_index: dict[str, Mapping[str, Any]] = {}
    assessment_source_metadata: Mapping[str, Any] | None = None
    if include_assessment_data and (
        assessment_path is not None
        or source.suffix.lower() in {".xlsx", ".xls", ".xlsb"}
    ):
        assessment_source = Path(assessment_path) if assessment_path else source
        assessment_rows = read_records(
            assessment_source,
            sheet_name=(
                assessment_sheet
                if assessment_source.suffix.lower() in {".xlsx", ".xls", ".xlsb"}
                else 0
            ),
            header_row=1,
        )
        assessment_index = {
            str(row.get("ID") or "").strip(): row
            for row in assessment_rows
            if row.get("ID") not in {None, ""}
        }
        if assessment_source.resolve() != source.resolve():
            assessment_source_metadata = _file_fingerprint(assessment_source)

    normalized: list[dict[str, Any]] = []
    for row_number, row in enumerate(recommendation_rows, start=2):
        status_code = str(row.get("IMPSTATUS") or "").strip().upper()
        if implemented_only and status_code != "I":
            continue
        assessment_id = str(row.get("ID") or "").strip()
        assessment = assessment_index.get(assessment_id, {})
        savings_values = [
            _optional_number(
                row.get(f"{prefix}SAVED"), f"ITAC row {row_number} {prefix}SAVED"
            )
            for prefix in ("P", "S", "T", "Q")
        ]
        reported_savings = [value for value in savings_values if value is not None]
        annual_savings = sum(reported_savings) if reported_savings else None
        implementation_cost = _optional_number(
            row.get("IMPCOST"), f"ITAC row {row_number} IMPCOST"
        )
        payback = _optional_number(row.get("PAYBACK"), f"ITAC row {row_number} PAYBACK")
        if (
            payback is None
            and implementation_cost is not None
            and annual_savings is not None
            and annual_savings > 0
        ):
            payback = implementation_cost / annual_savings
        streams: list[dict[str, Any]] = []
        for position, prefix in zip(
            ("primary", "secondary", "tertiary", "quaternary"), ("P", "S", "T", "Q")
        ):
            code = row.get(f"{prefix}SOURCCODE")
            conserved = _optional_number(
                row.get(f"{prefix}CONSERVED"),
                f"ITAC row {row_number} {prefix}CONSERVED",
            )
            source_conserved = _optional_number(
                row.get(f"{prefix}SOURCONSV"),
                f"ITAC row {row_number} {prefix}SOURCONSV",
            )
            savings = savings_values[("P", "S", "T", "Q").index(prefix)]
            if any(
                value is not None and value != ""
                for value in (code, conserved, source_conserved, savings)
            ):
                streams.append(
                    {
                        "position": position,
                        "resource_code": code,
                        "units_conserved": conserved,
                        "source_units_conserved": source_conserved,
                        "annual_cost_savings_usd": savings,
                    }
                )
        normalized.append(
            {
                "recommendation_id": row.get("SUPERID")
                or f"{assessment_id}{row.get('AR_NUMBER')}",
                "assessment_id": assessment_id,
                "recommendation_number": row.get("AR_NUMBER"),
                "recommendation_code": row.get("ARC2"),
                "application_code": row.get("APPCODE"),
                "implementation_status": {
                    "I": "implemented",
                    "N": "not implemented",
                }.get(status_code, status_code or "unknown"),
                "implementation_cost_usd": implementation_cost,
                "annual_cost_savings_usd": annual_savings,
                "simple_payback_years": payback,
                "fiscal_year": row.get("FY") or assessment.get("FY"),
                "naics": assessment.get("NAICS"),
                "sic": assessment.get("SIC"),
                "state": assessment.get("STATE"),
                "annual_sales_usd": assessment.get("SALES"),
                "employees": assessment.get("EMPLOYEES"),
                "resource_streams": streams,
            }
        )
    if not normalized:
        raise ValueError("ITAC/IAC source produced no recommendations after filtering")
    return _local_result(
        source,
        dataset_id="doe-iac",
        source_name="DOE Industrial Training and Assessment Centers database",
        source_url=_IAC_URL,
        license_notice="Public DOE program database; review the download terms and cite the ITAC/IAC database.",
        records=normalized,
        metadata={
            "implemented_only": implemented_only,
            "assessment_metadata_joined": bool(assessment_index),
            "currency": "USD",
            "price_basis": "nominal dollars in the assessment fiscal year",
            "assessment_source": assessment_source_metadata,
        },
        warnings=(
            "Historical dollar values are nominal; inflate and convert currencies explicitly before comparison.",
            "The database represents assessed US small and medium manufacturers and is not a representative global prior.",
            "Recommendation outcomes are observational and should not be interpreted as causal performance guarantees.",
        ),
    )


def load_fied_units(
    path: str | Path,
    *,
    sheet_name: str | int = 0,
    header_row: int = 1,
    columns: Mapping[str, str] | None = None,
) -> DataIntegrationResult:
    """Normalize a local FIED unit-level export with energy uncertainty ranges."""

    source = Path(path)
    rows = read_records(source, sheet_name=sheet_name, header_row=header_row)
    if not rows:
        raise ValueError("FIED source contains no data records")
    overrides = dict(columns or {})
    aliases = {
        "registry_id": ("registryID", "registry_id"),
        "facility_name": ("name", "facility_name"),
        "naics": ("naicsCode", "naics"),
        "state": ("stateCode", "state"),
        "latitude": ("latitude",),
        "longitude": ("longitude",),
        "unit_id": ("eisUnitID", "unit_id"),
        "unit_name": ("unitName", "unit_name"),
        "unit_type": ("unitTypeStd", "unitType", "unit_type"),
        "fuel_type": ("fuelTypeStd", "fuelType", "fuel_type"),
        "energy_source": ("energyEstimateSource", "energy_source"),
        "energy_mj": ("energyMJ", "energy_mj"),
        "energy_mj_low": ("energyMJq0", "energyMJ0", "energy_mj_low"),
        "energy_mj_median": ("energyMJq2", "energy_mj_median"),
        "energy_mj_high": ("energyMJq3", "energy_mj_high"),
        "ghg_tonnes_low": ("ghgsTonneCO2eQ0", "ghg_tonnes_low"),
        "ghg_tonnes_median": ("ghgsTonneCO2eQ2", "ghg_tonnes_median"),
        "ghg_tonnes_high": ("ghgsTonneCO2eQ3", "ghg_tonnes_high"),
    }
    resolved = {
        field_name: _find_column(
            rows,
            candidates,
            override=overrides.get(field_name),
            required=field_name == "registry_id",
            label=field_name,
        )
        for field_name, candidates in aliases.items()
    }
    normalized: list[dict[str, Any]] = []
    numeric_fields = {
        "latitude",
        "longitude",
        "energy_mj",
        "energy_mj_low",
        "energy_mj_median",
        "energy_mj_high",
        "ghg_tonnes_low",
        "ghg_tonnes_median",
        "ghg_tonnes_high",
    }
    for row_number, row in enumerate(rows, start=header_row + 1):
        item: dict[str, Any] = {}
        for field_name, column in resolved.items():
            value = row.get(column) if column else None
            if field_name in numeric_fields:
                value = _optional_number(value, f"FIED row {row_number} {field_name}")
            item[field_name] = value
        for suffix in ("", "_low", "_median", "_high"):
            mj = item.get(f"energy_mj{suffix}")
            if mj is not None:
                item[f"energy_mwh{suffix}"] = mj / 3600.0
        for suffix in ("_low", "_median", "_high"):
            tonnes = item.get(f"ghg_tonnes{suffix}")
            if tonnes is not None:
                item[f"ghg_kg_co2e{suffix}"] = tonnes * 1000.0
        normalized.append(item)
    return _local_result(
        source,
        dataset_id="fied",
        source_name="Foundational Industry Energy Dataset",
        source_url=_FIED_URL,
        license_notice="Review the FIED release and each upstream agency source term; retain source attribution.",
        records=normalized,
        metadata={
            "normalized_energy_unit": "MWh",
            "normalized_ghg_unit": "kg CO2e",
            "sheet_name": sheet_name,
            "header_row": header_row,
        },
        warnings=(
            "Many FIED energy and emissions fields are estimates or ranges, not measurements.",
            "FIED covers US industrial facilities for selected vintages and is not a global default.",
            "Temperature grade and process-boundary detail remain sparse; use FIED to seed, not replace, site refinement.",
        ),
    )
