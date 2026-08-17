"""Weather preprocessing and degree-day normalization for operational data."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

_DATE_FIELDS = ("date", "timestamp", "datetime", "weather_date")
_TEMPERATURE_FIELDS = (
    "temperature_c",
    "ambient_temperature_c",
    "t2m",
    "T2M",
)
_NASA_FIELDS = {
    "T2M": "temperature_c",
    "RH2M": "relative_humidity_percent",
    "PRECTOTCORR": "precipitation_mm_day",
    "ALLSKY_SFC_SW_DWN": "solar_irradiance_kwh_m2_day",
}


def _finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _record_value(record: Mapping[str, Any], candidates: Iterable[str]) -> Any:
    for name in candidates:
        value = record.get(name)
        if value not in {None, ""}:
            return value
    return None


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise ValueError(f"unsupported date or timestamp {value!r}") from exc


def _nasa_parameter_unit(payload: Mapping[str, Any], parameter: str) -> str | None:
    metadata = payload.get("parameter_metadata", {})
    if not isinstance(metadata, Mapping):
        return None
    details = metadata.get(parameter)
    if isinstance(details, str):
        return details
    if not isinstance(details, Mapping):
        return None
    unit = details.get("units", details.get("unit"))
    return str(unit).strip() if unit not in {None, ""} else None


def _solar_irradiance_kwh_m2_day(value: Any, unit: str | None) -> float:
    irradiance = _finite(value, "NASA POWER ALLSKY_SFC_SW_DWN value")
    if unit is None:
        raise ValueError(
            "NASA POWER solar irradiance unit metadata is required; refetch the "
            "weather data to replace a legacy cache"
        )
    normalized = (
        unit.lower()
        .replace("²", "2")
        .replace("^", "")
        .replace(" ", "")
        .replace("_", "")
    )
    if normalized in {"wm-2", "w/m2"}:
        return irradiance * 24.0 / 1000.0
    if normalized in {"mj/m2/day", "mjm-2day-1"}:
        return irradiance / 3.6
    if normalized in {
        "kwh/m2/day",
        "kw-hr/m2/day",
        "kwhm-2day-1",
    }:
        return irradiance
    raise ValueError(
        f"unsupported NASA POWER ALLSKY_SFC_SW_DWN unit {unit!r}; expected "
        "W/m2, MJ/m2/day, or kWh/m2/day"
    )


@dataclass(frozen=True)
class MonthlyWeatherClimatology:
    """Typical daily weather metrics for one calendar month."""

    month: int
    observations: int
    mean_temperature_c: float
    mean_heating_degree_days_c_day: float
    mean_cooling_degree_days_c_day: float
    mean_relative_humidity_percent: float | None = None
    mean_precipitation_mm_day: float | None = None
    mean_solar_irradiance_kwh_m2_day: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "month": self.month,
                "observations": self.observations,
                "mean_temperature_c": self.mean_temperature_c,
                "mean_heating_degree_days_c_day": self.mean_heating_degree_days_c_day,
                "mean_cooling_degree_days_c_day": self.mean_cooling_degree_days_c_day,
                "mean_relative_humidity_percent": self.mean_relative_humidity_percent,
                "mean_precipitation_mm_day": self.mean_precipitation_mm_day,
                "mean_solar_irradiance_kwh_m2_day": self.mean_solar_irradiance_kwh_m2_day,
            }.items()
            if value is not None
        }


@dataclass(frozen=True)
class WeatherClimatology:
    """A versioned monthly climatology suitable for local normalization."""

    months: Mapping[int, MonthlyWeatherClimatology]
    heating_base_c: float
    cooling_base_c: float
    reference_start: str | None = None
    reference_end: str | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "heating_base_c": self.heating_base_c,
            "cooling_base_c": self.cooling_base_c,
            "reference_start": self.reference_start,
            "reference_end": self.reference_end,
            "source": self.source,
            "months": {
                str(month): value.to_dict()
                for month, value in sorted(self.months.items())
            },
        }


@dataclass(frozen=True)
class WeatherNormalizationResult:
    """Regression-based weather adjustment for an additive operating metric."""

    metric: str
    unit: str
    observations: int
    actual_total: float
    normalized_total: float
    weather_adjustment: float
    intercept_per_observation: float
    heating_sensitivity_per_degree_day: float
    cooling_sensitivity_per_degree_day: float
    actual_heating_degree_days: float
    actual_cooling_degree_days: float
    normal_heating_degree_days: float
    normal_cooling_degree_days: float
    r_squared: float | None
    assumptions: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "metric": self.metric,
            "unit": self.unit,
            "observations": self.observations,
            "actual_total": self.actual_total,
            "normalized_total": self.normalized_total,
            "weather_adjustment": self.weather_adjustment,
            "model": {
                "intercept_per_observation": self.intercept_per_observation,
                "heating_sensitivity_per_degree_day": self.heating_sensitivity_per_degree_day,
                "cooling_sensitivity_per_degree_day": self.cooling_sensitivity_per_degree_day,
                "r_squared": self.r_squared,
            },
            "degree_days": {
                "actual_heating": self.actual_heating_degree_days,
                "actual_cooling": self.actual_cooling_degree_days,
                "normal_heating": self.normal_heating_degree_days,
                "normal_cooling": self.normal_cooling_degree_days,
            },
            "assumptions": dict(self.assumptions),
            "warnings": list(self.warnings),
        }

    def export_html(self, path: str, **options: Any) -> Any:
        from .reporting import export_html

        return export_html(self, path, **options)

    def export_pdf(self, path: str, **options: Any) -> Any:
        from .reporting import export_pdf

        return export_pdf(self, path, **options)

    def export_excel_compatible(self, directory: str, **options: Any) -> Any:
        from .reporting import export_excel_compatible_report

        return export_excel_compatible_report(self, directory, **options)

    def export_xlsx(self, path: str, **options: Any) -> Any:
        from .excel import export_xlsx_report

        return export_xlsx_report(self, path, **options)


def nasa_power_weather_records(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Convert a cached NASA POWER response into date-aligned daily records."""

    raw_values = payload.get("values", {})
    if not isinstance(raw_values, Mapping):
        raise ValueError("NASA POWER payload does not contain a values mapping")
    if raw_values and all(
        not isinstance(value, Mapping) for value in raw_values.values()
    ):
        raw_values = {str(payload.get("parameter", "T2M")): raw_values}
    dates = sorted(
        {
            str(day)
            for values in raw_values.values()
            if isinstance(values, Mapping)
            for day in values
        }
    )
    records: list[dict[str, Any]] = []
    for day in dates:
        record: dict[str, Any] = {
            "date": _date(day).isoformat(),
            "source": payload.get("source", "NASA POWER"),
        }
        for parameter, values in raw_values.items():
            if not isinstance(values, Mapping) or day not in values:
                continue
            value = values[day]
            if value in {None, -999, -999.0}:
                continue
            field_name = _NASA_FIELDS.get(str(parameter), str(parameter).lower())
            if str(parameter) == "ALLSKY_SFC_SW_DWN":
                record[field_name] = _solar_irradiance_kwh_m2_day(
                    value, _nasa_parameter_unit(payload, str(parameter))
                )
            else:
                record[field_name] = _finite(value, f"NASA POWER {parameter} value")
        if len(record) > 2:
            records.append(record)
    return records


def add_weather_metrics(
    records: Iterable[Mapping[str, Any]],
    *,
    date_field: str | None = None,
    temperature_field: str | None = None,
    heating_base_c: float = 18.0,
    cooling_base_c: float = 18.0,
    duration_days: float = 1.0,
) -> list[dict[str, Any]]:
    """Add daily heating/cooling degree days without discarding source fields."""

    heating_base = _finite(heating_base_c, "heating_base_c")
    cooling_base = _finite(cooling_base_c, "cooling_base_c")
    duration = _finite(duration_days, "duration_days")
    if duration <= 0.0:
        raise ValueError("duration_days must be greater than zero")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(records):
        raw_date = _record_value(raw, (date_field,) if date_field else _DATE_FIELDS)
        raw_temperature = _record_value(
            raw,
            (temperature_field,) if temperature_field else _TEMPERATURE_FIELDS,
        )
        if raw_date is None:
            raise ValueError(f"record {index} has no date or timestamp")
        if raw_temperature is None:
            raise ValueError(f"record {index} has no ambient temperature")
        day = _date(raw_date)
        temperature = _finite(raw_temperature, f"record {index} temperature")
        enriched = dict(raw)
        enriched.update(
            {
                "weather_date": day.isoformat(),
                "temperature_c": temperature,
                "heating_base_c": heating_base,
                "cooling_base_c": cooling_base,
                "heating_degree_days_c_day": max(heating_base - temperature, 0.0)
                * duration,
                "cooling_degree_days_c_day": max(temperature - cooling_base, 0.0)
                * duration,
            }
        )
        result.append(enriched)
    return result


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def monthly_weather_climatology(
    records: Iterable[Mapping[str, Any]],
    *,
    date_field: str | None = None,
    temperature_field: str | None = None,
    heating_base_c: float = 18.0,
    cooling_base_c: float = 18.0,
    reference_start: str | date | None = None,
    reference_end: str | date | None = None,
    source: str | None = None,
) -> WeatherClimatology:
    """Calculate typical daily weather values for each available month."""

    start = _date(reference_start) if reference_start is not None else None
    end = _date(reference_end) if reference_end is not None else None
    if start and end and start > end:
        raise ValueError("reference_start must not be after reference_end")
    selected_records: list[Mapping[str, Any]] = []
    for index, record in enumerate(records):
        raw_date = _record_value(record, (date_field,) if date_field else _DATE_FIELDS)
        if raw_date is None:
            raise ValueError(f"record {index} has no date or timestamp")
        day = _date(raw_date)
        if (start is None or day >= start) and (end is None or day <= end):
            selected_records.append(record)
    if not selected_records:
        raise ValueError("no weather records fall inside the reference period")
    rows = add_weather_metrics(
        selected_records,
        date_field=date_field,
        temperature_field=temperature_field,
        heating_base_c=heating_base_c,
        cooling_base_c=cooling_base_c,
    )
    months: dict[int, MonthlyWeatherClimatology] = {}
    for month in range(1, 13):
        group = [row for row in rows if _date(row["weather_date"]).month == month]
        if not group:
            continue

        def optional_mean(field_name: str) -> float | None:
            values = [
                _finite(row[field_name], field_name)
                for row in group
                if row.get(field_name) not in {None, ""}
            ]
            return _mean(values)

        months[month] = MonthlyWeatherClimatology(
            month=month,
            observations=len(group),
            mean_temperature_c=sum(row["temperature_c"] for row in group) / len(group),
            mean_heating_degree_days_c_day=sum(
                row["heating_degree_days_c_day"] for row in group
            )
            / len(group),
            mean_cooling_degree_days_c_day=sum(
                row["cooling_degree_days_c_day"] for row in group
            )
            / len(group),
            mean_relative_humidity_percent=optional_mean("relative_humidity_percent"),
            mean_precipitation_mm_day=optional_mean("precipitation_mm_day"),
            mean_solar_irradiance_kwh_m2_day=optional_mean(
                "solar_irradiance_kwh_m2_day"
            ),
        )
    return WeatherClimatology(
        months=months,
        heating_base_c=_finite(heating_base_c, "heating_base_c"),
        cooling_base_c=_finite(cooling_base_c, "cooling_base_c"),
        reference_start=start.isoformat() if start else None,
        reference_end=end.isoformat() if end else None,
        source=source,
    )


def weather_anomalies(
    records: Iterable[Mapping[str, Any]],
    climatology: WeatherClimatology,
    *,
    date_field: str | None = None,
    temperature_field: str | None = None,
) -> list[dict[str, Any]]:
    """Add observation-minus-climatology anomalies for temperature and degree days."""

    rows = add_weather_metrics(
        records,
        date_field=date_field,
        temperature_field=temperature_field,
        heating_base_c=climatology.heating_base_c,
        cooling_base_c=climatology.cooling_base_c,
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        month = _date(row["weather_date"]).month
        normal = climatology.months.get(month)
        if normal is None:
            raise ValueError(f"climatology has no values for calendar month {month}")
        enriched = dict(row)
        enriched.update(
            {
                "temperature_anomaly_c": row["temperature_c"]
                - normal.mean_temperature_c,
                "heating_degree_day_anomaly_c_day": row["heating_degree_days_c_day"]
                - normal.mean_heating_degree_days_c_day,
                "cooling_degree_day_anomaly_c_day": row["cooling_degree_days_c_day"]
                - normal.mean_cooling_degree_days_c_day,
            }
        )
        result.append(enriched)
    return result


def _fit_univariate(x: list[float], y: list[float]) -> tuple[float, float, float]:
    mean_x = sum(x) / len(x)
    mean_y = sum(y) / len(y)
    variance = sum((item - mean_x) ** 2 for item in x)
    slope = (
        sum((item - mean_x) * (target - mean_y) for item, target in zip(x, y))
        / variance
        if variance > 0.0
        else 0.0
    )
    intercept = mean_y - slope * mean_x
    sse = sum((target - (intercept + slope * item)) ** 2 for item, target in zip(x, y))
    return intercept, slope, sse


def _weather_fit(
    heating: list[float], cooling: list[float], values: list[float]
) -> tuple[float, float, float, float, tuple[str, ...]]:
    mean_h = sum(heating) / len(heating)
    mean_c = sum(cooling) / len(cooling)
    mean_y = sum(values) / len(values)
    candidates: list[tuple[float, float, float, float, str]] = [
        (
            mean_y,
            0.0,
            0.0,
            sum((value - mean_y) ** 2 for value in values),
            "intercept-only",
        )
    ]
    for predictor, kind in ((heating, "heating"), (cooling, "cooling")):
        intercept, slope, sse = _fit_univariate(predictor, values)
        if slope >= 0.0:
            candidates.append(
                (
                    intercept,
                    slope if kind == "heating" else 0.0,
                    slope if kind == "cooling" else 0.0,
                    sse,
                    kind,
                )
            )
    var_h = sum((value - mean_h) ** 2 for value in heating)
    var_c = sum((value - mean_c) ** 2 for value in cooling)
    cov_hc = sum(
        (h_value - mean_h) * (c_value - mean_c)
        for h_value, c_value in zip(heating, cooling)
    )
    cov_hy = sum(
        (h_value - mean_h) * (target - mean_y)
        for h_value, target in zip(heating, values)
    )
    cov_cy = sum(
        (c_value - mean_c) * (target - mean_y)
        for c_value, target in zip(cooling, values)
    )
    determinant = var_h * var_c - cov_hc**2
    if determinant > 1e-12:
        heating_slope = (cov_hy * var_c - cov_cy * cov_hc) / determinant
        cooling_slope = (cov_cy * var_h - cov_hy * cov_hc) / determinant
        if heating_slope >= 0.0 and cooling_slope >= 0.0:
            intercept = mean_y - heating_slope * mean_h - cooling_slope * mean_c
            sse = sum(
                (
                    target
                    - (intercept + heating_slope * h_value + cooling_slope * c_value)
                )
                ** 2
                for h_value, c_value, target in zip(heating, cooling, values)
            )
            candidates.append(
                (intercept, heating_slope, cooling_slope, sse, "heating+cooling")
            )
    intercept, heating_slope, cooling_slope, sse, model = min(
        candidates, key=lambda item: item[3]
    )
    total_variance = sum((value - mean_y) ** 2 for value in values)
    r_squared = 1.0 - sse / total_variance if total_variance > 0.0 else 1.0
    warnings: list[str] = []
    if model == "intercept-only":
        warnings.append(
            "No positive weather sensitivity was identifiable; the normalized total equals the actual total."
        )
    if intercept < 0.0:
        warnings.append(
            "The fitted non-weather base load is negative; review the period, bases, and data quality."
        )
    return intercept, heating_slope, cooling_slope, r_squared, tuple(warnings)


def normalize_weather_performance(
    records: Iterable[Mapping[str, Any]],
    *,
    value_field: str,
    climatology: WeatherClimatology | None = None,
    normal_heating_degree_days: float | None = None,
    normal_cooling_degree_days: float | None = None,
    metric: str | None = None,
    unit: str = "",
    date_field: str | None = None,
    temperature_field: str | None = None,
    heating_base_c: float | None = None,
    cooling_base_c: float | None = None,
) -> WeatherNormalizationResult:
    """Normalize daily energy, exergy, output, or cost to declared normal weather."""

    if climatology is not None:
        if heating_base_c is not None and not math.isclose(
            heating_base_c, climatology.heating_base_c, rel_tol=0.0, abs_tol=1e-12
        ):
            raise ValueError(
                "heating_base_c conflicts with the supplied climatology base"
            )
        if cooling_base_c is not None and not math.isclose(
            cooling_base_c, climatology.cooling_base_c, rel_tol=0.0, abs_tol=1e-12
        ):
            raise ValueError(
                "cooling_base_c conflicts with the supplied climatology base"
            )
        heating_base_c = climatology.heating_base_c
        cooling_base_c = climatology.cooling_base_c
    else:
        heating_base_c = 18.0 if heating_base_c is None else heating_base_c
        cooling_base_c = 18.0 if cooling_base_c is None else cooling_base_c
    rows = add_weather_metrics(
        records,
        date_field=date_field,
        temperature_field=temperature_field,
        heating_base_c=heating_base_c,
        cooling_base_c=cooling_base_c,
    )
    if len(rows) < 2:
        raise ValueError("weather normalization requires at least two observations")
    values: list[float] = []
    for index, row in enumerate(rows):
        if row.get(value_field) in {None, ""}:
            raise ValueError(f"record {index} has no value for {value_field!r}")
        value = _finite(row[value_field], f"record {index} {value_field}")
        if value < 0.0:
            raise ValueError(f"record {index} {value_field} must be nonnegative")
        values.append(value)
    heating = [float(row["heating_degree_days_c_day"]) for row in rows]
    cooling = [float(row["cooling_degree_days_c_day"]) for row in rows]
    if climatology is not None:
        month_counts: dict[int, int] = {}
        for row in rows:
            month = _date(row["weather_date"]).month
            month_counts[month] = month_counts.get(month, 0) + 1
        missing = sorted(set(month_counts) - set(climatology.months))
        if missing:
            raise ValueError(
                "climatology is missing calendar months: "
                + ", ".join(str(month) for month in missing)
            )
        if normal_heating_degree_days is None:
            normal_heating_degree_days = sum(
                climatology.months[month].mean_heating_degree_days_c_day * count
                for month, count in month_counts.items()
            )
        if normal_cooling_degree_days is None:
            normal_cooling_degree_days = sum(
                climatology.months[month].mean_cooling_degree_days_c_day * count
                for month, count in month_counts.items()
            )
    if normal_heating_degree_days is None or normal_cooling_degree_days is None:
        raise ValueError(
            "supply a climatology or both normal_heating_degree_days and normal_cooling_degree_days"
        )
    normal_hdd = _finite(normal_heating_degree_days, "normal_heating_degree_days")
    normal_cdd = _finite(normal_cooling_degree_days, "normal_cooling_degree_days")
    if normal_hdd < 0.0 or normal_cdd < 0.0:
        raise ValueError("normal degree-day totals must be nonnegative")
    intercept, heating_slope, cooling_slope, r_squared, warnings = _weather_fit(
        heating, cooling, values
    )
    actual_hdd = sum(heating)
    actual_cdd = sum(cooling)
    actual_total = sum(values)
    normalized_total = (
        actual_total
        + heating_slope * (normal_hdd - actual_hdd)
        + cooling_slope * (normal_cdd - actual_cdd)
    )
    normalization_scale = max(
        actual_total,
        abs(heating_slope * (normal_hdd - actual_hdd)),
        abs(cooling_slope * (normal_cdd - actual_cdd)),
        1.0,
    )
    if normalized_total < -1e-12 * normalization_scale:
        raise ValueError(
            "weather-normalized total is negative; review the period, bases, "
            "normal degree days, and data quality"
        )
    normalized_total = max(normalized_total, 0.0)
    assumptions: dict[str, Any] = {
        "heating_base_c": heating_base_c,
        "cooling_base_c": cooling_base_c,
        "normal_source": (
            climatology.source or "unspecified monthly climatology"
            if climatology is not None
            else "provided degree-day totals"
        ),
        "model": "nonnegative degree-day sensitivity with intercept",
    }
    if climatology is not None:
        assumptions.update(
            {
                "normal_source_type": "monthly climatology",
                "normal_reference_start": climatology.reference_start,
                "normal_reference_end": climatology.reference_end,
            }
        )
    return WeatherNormalizationResult(
        metric=metric or value_field,
        unit=unit,
        observations=len(rows),
        actual_total=actual_total,
        normalized_total=normalized_total,
        weather_adjustment=normalized_total - actual_total,
        intercept_per_observation=intercept,
        heating_sensitivity_per_degree_day=heating_slope,
        cooling_sensitivity_per_degree_day=cooling_slope,
        actual_heating_degree_days=actual_hdd,
        actual_cooling_degree_days=actual_cdd,
        normal_heating_degree_days=normal_hdd,
        normal_cooling_degree_days=normal_cdd,
        r_squared=r_squared,
        assumptions=assumptions,
        warnings=warnings,
    )
