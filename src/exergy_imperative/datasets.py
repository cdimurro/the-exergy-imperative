"""Explicit, cacheable connectors for public datasets."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class DatasetCatalogEntry:
    id: str
    name: str
    url: str
    license: str
    geography: str
    capabilities: tuple[str, ...]
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "license": self.license,
            "geography": self.geography,
            "capabilities": list(self.capabilities),
            "note": self.note,
        }


DATASET_CATALOG = (
    DatasetCatalogEntry(
        id="xai4heat",
        name="XAI4HEAT SCADA Dataset 2024",
        url="https://data.mendeley.com/datasets/2mwc6x6kwb/1",
        license="CC-BY-4.0",
        geography="Nis, Serbia",
        capabilities=(
            "district-heating temperatures",
            "thermal delivery",
            "ambient temperature",
            "F3 interval analysis",
        ),
        note="Use preprocess.enrich_xai4heat_records after downloading the source dataset.",
    ),
    DatasetCatalogEntry(
        id="fied",
        name="Foundational Industry Energy Dataset",
        url="https://github.com/NatLabRockies/foundational-industry-energy-data",
        license="See source dataset and upstream agency terms",
        geography="United States",
        capabilities=(
            "industrial facility identifiers",
            "unit types",
            "fuel types",
            "energy estimate ranges",
        ),
        note="Useful for selecting equipment and industry priors; temperature-grade data remain sparse.",
    ),
    DatasetCatalogEntry(
        id="nasa-power",
        name="NASA POWER meteorology",
        url="https://power.larc.nasa.gov/docs/services/api/",
        license="NASA open data terms",
        geography="Global",
        capabilities=(
            "ambient temperature",
            "solar resource",
            "hourly and daily time series",
        ),
        note="Network access is explicit and responses can be cached locally.",
    ),
    DatasetCatalogEntry(
        id="ember-electricity",
        name="Ember Yearly Electricity Data",
        url="https://ember-energy.org/data/yearly-electricity-data/",
        license="CC-BY-4.0",
        geography="Global",
        capabilities=(
            "country electricity generation",
            "lifecycle grid carbon intensity",
            "annual history",
        ),
        note="A recent six-year country intensity history is bundled with attribution; run the update script deliberately to refresh it.",
    ),
    DatasetCatalogEntry(
        id="owid-energy",
        name="Our World in Data complete Energy dataset",
        url="https://github.com/owid/energy-data",
        license="OWID CC-BY-4.0 plus underlying source terms",
        geography="Global",
        capabilities=(
            "standardized country names",
            "energy and electricity indicators",
            "documented source lineage",
        ),
        note="The bundled electricity pack uses OWID's standardized publication of the Ember indicator.",
    ),
    DatasetCatalogEntry(
        id="emep-eea-2023",
        name="EMEP/EEA Air Pollutant Emission Inventory Guidebook 2023",
        url="https://www.eea.europa.eu/en/analysis/publications/emep-eea-guidebook-2023",
        license="European Environment Agency reuse terms",
        geography="Europe with broadly useful inventory methods",
        capabilities=(
            "air pollutant inventory methods",
            "technology-specific factors",
            "uncertainty and QA guidance",
        ),
        note="Use technology- and control-specific factors where available; mass emissions alone do not determine health exposure.",
    ),
)


def list_datasets() -> tuple[DatasetCatalogEntry, ...]:
    return DATASET_CATALOG


def dataset_info(dataset_id: str) -> DatasetCatalogEntry:
    key = dataset_id.strip().lower()
    for record in DATASET_CATALOG:
        if record.id == key:
            return record
    raise KeyError(f"unknown dataset {dataset_id!r}")


def fetch_nasa_power_weather(
    latitude: float,
    longitude: float,
    start: str,
    end: str,
    *,
    parameters: tuple[str, ...] = (
        "T2M",
        "RH2M",
        "PRECTOTCORR",
        "ALLSKY_SFC_SW_DWN",
    ),
    cache_dir: str | Path | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Fetch selected daily weather variables from NASA POWER.

    Calling this function is an explicit opt-in to network access. ``start`` and
    ``end`` use ``YYYYMMDD``. The raw JSON response is cached when ``cache_dir``
    is supplied. Common parameters include ``T2M``, ``RH2M``,
    ``PRECTOTCORR``, and ``ALLSKY_SFC_SW_DWN``.
    """

    if not -90.0 <= float(latitude) <= 90.0:
        raise ValueError("latitude must be between -90 and 90")
    if not -180.0 <= float(longitude) <= 180.0:
        raise ValueError("longitude must be between -180 and 180")
    if (
        not isinstance(start, str)
        or not isinstance(end, str)
        or len(start) != 8
        or len(end) != 8
        or not start.isdigit()
        or not end.isdigit()
    ):
        raise ValueError("start and end must use YYYYMMDD")
    try:
        start_date = datetime.strptime(start, "%Y%m%d").date()
        end_date = datetime.strptime(end, "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError(
            "start and end must be valid calendar dates using YYYYMMDD"
        ) from exc
    if start_date > end_date:
        raise ValueError("start must be on or before end")
    requested = tuple(dict.fromkeys(str(item).strip().upper() for item in parameters))
    if not requested:
        raise ValueError("at least one NASA POWER parameter is required")
    if any(not re.fullmatch(r"[A-Z0-9_]+", item) for item in requested):
        raise ValueError("NASA POWER parameters may contain only A-Z, 0-9, and _")
    query = urlencode(
        {
            "parameters": ",".join(requested),
            "community": "SB",
            "longitude": float(longitude),
            "latitude": float(latitude),
            "start": start,
            "end": end,
            "format": "JSON",
        }
    )
    url = f"https://power.larc.nasa.gov/api/temporal/daily/point?{query}"
    cache_path: Path | None = None
    if cache_dir is not None:
        root = Path(cache_dir)
        root.mkdir(parents=True, exist_ok=True)
        # Include a cache-format marker so responses created before parameter
        # metadata was retained cannot be mistaken for unit-aware weather data.
        digest = hashlib.sha256(f"v2:{url}".encode("utf-8")).hexdigest()[:20]
        cache_path = root / f"nasa-power-weather-{digest}.json"
        if cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))
    request = Request(url, headers={"User-Agent": "exergy-imperative/0.1"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed NASA endpoint
        payload = json.loads(response.read().decode("utf-8"))
    result = {
        "source": "NASA POWER",
        "source_url": url,
        "parameters": list(requested),
        "latitude": float(latitude),
        "longitude": float(longitude),
        "start": start,
        "end": end,
        "values": {
            parameter: payload.get("properties", {})
            .get("parameter", {})
            .get(parameter, {})
            for parameter in requested
        },
        "parameter_metadata": {
            parameter: payload.get("parameters", {}).get(parameter, {})
            for parameter in requested
        },
        "raw_header": payload.get("header", {}),
    }
    if cache_path is not None:
        cache_path.write_text(
            json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
        )
    return result


def fetch_nasa_power_temperature(
    latitude: float,
    longitude: float,
    start: str,
    end: str,
    *,
    cache_dir: str | Path | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Fetch daily 2 m temperature using the original stable response shape."""

    result = fetch_nasa_power_weather(
        latitude,
        longitude,
        start,
        end,
        parameters=("T2M",),
        cache_dir=cache_dir,
        timeout=timeout,
    )
    result["parameter"] = "T2M"
    result["unit"] = "C"
    result["values"] = result["values"]["T2M"]
    return result
