"""Utility-data-to-investment-decision example for an industrial pilot.

The bundled CSV is illustrative, not measured plant data. It exists to make the
workflow reproducible; replace the file and mapping inputs with site records.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import exergy_imperative as xi

ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "industrial_pilot_meter_export.csv"

PROCESS_CONFIG = {
    "Steam system": {
        "template": "steam",
        "temperature_fields": (
            "source_temperature",
            "return_temperature",
            "ambient_temperature",
        ),
    },
    "Compressed air": {
        "template": "compressed air",
        "temperature_fields": (),
    },
    "Furnace": {
        "template": "furnace",
        "temperature_fields": ("source_temperature", "ambient_temperature"),
    },
}


def _weighted_average(records: list[dict[str, Any]], field: str) -> float | None:
    values = [
        (float(row["energy"]), float(row[field]))
        for row in records
        if row.get(field) not in (None, "")
    ]
    total_weight = sum(weight for weight, _value in values)
    if total_weight <= 0.0:
        return None
    return sum(weight * value for weight, value in values) / total_weight


def _constant(records: list[dict[str, Any]], field: str) -> float:
    values = {float(row[field]) for row in records if row.get(field) not in (None, "")}
    if len(values) != 1:
        raise ValueError(f"{field} must have one consistent value per equipment group")
    return values.pop()


def build_pilot(
    input_path: str | Path = DEFAULT_INPUT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Ingest a meter export and return the audit trail plus ranked decisions."""

    raw_records = xi.read_records(input_path)
    if not raw_records:
        raise ValueError("the meter export is empty")
    mapping = xi.infer_mapping(raw_records[0], required=("energy", "technology"))
    ingestion = xi.normalize_records(
        raw_records, mapping=mapping, missing_policy="keep"
    )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in ingestion.records:
        grouped[str(record["technology"])].append(record)

    assessments = []
    for equipment, config in PROCESS_CONFIG.items():
        records = grouped.get(equipment)
        if not records:
            raise ValueError(f"meter export has no records for {equipment}")
        energy_mwh = sum(float(row["energy"]) for row in records)
        efficiency = _weighted_average(records, "efficiency")
        assessment_options: dict[str, Any] = {}
        if efficiency is not None:
            assessment_options["efficiency"] = efficiency
        for field in config["temperature_fields"]:
            value = _weighted_average(records, field)
            if value is not None:
                assessment_options[field] = f"{value} C"

        result = xi.assess_process(
            config["template"],
            energy=energy_mwh,
            country="USA",
            year=2025,
            assessment_options=assessment_options,
            economics_options={
                "capital_cost": _constant(records, "capital_cost"),
                "energy_price_per_mwh": _weighted_average(
                    records, "energy_price_per_mwh"
                ),
                "project_life_years": 12,
                "discount_rate": 0.07,
                "currency": "USD",
            },
            annualization_factor=1.0,
        )
        destroyed = result.assessment.exergy_destroyed_or_lost
        reduced = result.opportunity.exergy_destruction_reduction
        assessments.append(
            {
                "equipment": equipment,
                "annual_input_energy_mwh": energy_mwh,
                "annual_input_exergy_mwh": result.assessment.input_exergy.value,
                "annual_exergy_destroyed_or_lost_mwh": (
                    destroyed.value if destroyed is not None else None
                ),
                "screening_energy_savings_mwh": result.opportunity.energy_savings.value,
                "screening_exergy_savings_mwh": (
                    reduced.value if reduced is not None else None
                ),
                "screening_co2e_savings_kg": result.opportunity.co2e100_reduction.value,
                "npv_usd": result.economics.npv if result.economics else None,
                "simple_payback_years": (
                    result.economics.simple_payback_years if result.economics else None
                ),
                "fidelity_tier": result.assessment.tier.value,
                "screening_only": True,
                "result": result,
            }
        )

    assessments.sort(
        key=lambda item: (
            item["npv_usd"] if item["npv_usd"] is not None else float("-inf")
        ),
        reverse=True,
    )
    decision_rows = [
        {key: value for key, value in item.items() if key != "result"}
        for item in assessments
    ]
    decision = {
        "schema_version": "industrial_data_pilot_v1",
        "input": str(Path(input_path)),
        "ranking_basis": "screening NPV using metered annual energy and declared project assumptions",
        "recommended_first_audit": decision_rows[0]["equipment"],
        "opportunities": decision_rows,
        "assumptions": {
            "country": "USA",
            "analysis_year": 2025,
            "project_life_years": 12,
            "discount_rate": 0.07,
            "annualization_factor": 1.0,
            "improvement_fraction": "bundled process-template screening prior",
        },
        "warnings": [
            "The bundled CSV is illustrative and is not measured plant data.",
            "Savings, emissions, and economics are screening estimates, not a site audit, design, bid, or guarantee.",
            "Replace temperatures, efficiencies, tariffs, capital costs, and improvement fractions with site-specific evidence before investment approval.",
        ],
    }
    audit = ingestion.to_dict()
    audit["mapping"] = mapping.to_dict()
    audit["assessment_results"] = {
        item["equipment"]: item["result"] for item in assessments
    }
    return audit, decision


def write_outputs(
    audit: dict[str, Any], decision: dict[str, Any], output_dir: str | Path
) -> None:
    """Write the auditable ingestion bundle, ranking, and top project report."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    ingestion = audit.copy()
    results = ingestion.pop("assessment_results")
    (output / "ingestion-audit.json").write_text(
        json.dumps(ingestion, indent=2) + "\n", encoding="utf-8"
    )
    (output / "portfolio-ranking.json").write_text(
        json.dumps(decision, indent=2) + "\n", encoding="utf-8"
    )
    top = decision["recommended_first_audit"]
    results[top].export_html(output / "recommended-project.html")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", default=str(DEFAULT_INPUT))
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args(argv)
    audit, decision = build_pilot(args.input)
    if args.output_dir:
        write_outputs(audit, decision, args.output_dir)
    print(json.dumps(decision, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
