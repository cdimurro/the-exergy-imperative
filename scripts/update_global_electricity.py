"""Build the bundled country electricity-intensity history.

The generated file is a curated derivative of the Our World in Data energy
dataset. The ``carbon_intensity_elec`` indicator is sourced from Ember's
Yearly Electricity Data. Run this script deliberately when updating the data
pack; normal library use never performs this network request.
"""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

SOURCE_URL = "https://owid-public.owid.io/data/energy/owid-energy-data.csv"
OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "exergy_imperative"
    / "data"
    / "global_electricity.json"
)
YEARS_PER_LOCATION = 6


def download_rows() -> list[dict[str, str]]:
    request = Request(
        SOURCE_URL,
        headers={
            "User-Agent": (
                "exergy-imperative-data-builder/0.2 "
                "(+https://github.com/cdimurro/the-exergy-imperative)"
            )
        },
    )
    with urlopen(request, timeout=90) as response:  # noqa: S310 - fixed source
        text = io.TextIOWrapper(response, encoding="utf-8")
        return list(csv.DictReader(text))


def build_payload(rows: list[dict[str, str]]) -> dict[str, object]:
    by_location: dict[tuple[str, str], list[tuple[int, float]]] = defaultdict(list)
    for row in rows:
        raw = row.get("carbon_intensity_elec", "")
        country = row.get("country", "").strip()
        iso3 = row.get("iso_code", "").strip()
        if not raw or not country:
            continue
        if country == "World":
            iso3 = "WORLD"
        if len(iso3) != 3 and iso3 != "WORLD":
            continue
        by_location[(iso3, country)].append((int(row["year"]), float(raw)))

    records: list[dict[str, object]] = []
    for (iso3, country), values in sorted(by_location.items()):
        for year, value in sorted(values)[-YEARS_PER_LOCATION:]:
            records.append(
                {
                    "iso3": iso3,
                    "country": country,
                    "year": year,
                    "kg_co2e_per_mwh": round(value, 3),
                }
            )

    generated_on = date.today().isoformat()
    return {
        "schema_version": "1.0",
        "data_version": f"owid-ember-{generated_on}",
        "generated_on": generated_on,
        "license": "CC-BY-4.0; retain attribution to Ember and OWID",
        "indicator": "carbon_intensity_elec",
        "unit": "kg CO2e/MWh",
        "scope": "lifecycle electricity-generation intensity",
        "sources": {
            "ember-yearly-electricity": {
                "title": "Ember Yearly Electricity Data",
                "url": "https://ember-energy.org/data/yearly-electricity-data/",
                "methodology": (
                    "https://files.ember-energy.org/public-downloads/"
                    "ember_electricity_data_methodology.pdf"
                ),
                "license": "CC-BY-4.0",
            },
            "owid-energy": {
                "title": "Our World in Data complete Energy dataset",
                "url": SOURCE_URL,
                "repository": "https://github.com/owid/energy-data",
                "note": "OWID standardizes location names and republishes the Ember indicator.",
            },
        },
        "records": records,
    }


def main() -> None:
    payload = build_payload(download_rows())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(payload['records'])} records to {OUTPUT}")


if __name__ == "__main__":
    main()
