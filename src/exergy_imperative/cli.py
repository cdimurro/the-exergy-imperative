"""Command-line interface for screening, preprocessing, and balances."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

from .adapters import adapt_local_dataset
from .agent import (
    AgentNativeError,
    describe_target,
    error_response,
    list_capabilities,
    run_recipe,
    search_capabilities,
)
from .assessment import MissingInputError, assess
from .balance import analyze_balance
from .datasets import fetch_nasa_power_temperature, list_datasets
from .economics import evaluate_economics, evaluate_technology_cost_scenario
from .engineering import (
    analyze_compressed_air,
    analyze_furnace,
    analyze_heat_pump,
    analyze_refrigeration,
    analyze_steam_system,
    match_waste_heat,
)
from .excel import create_excel_template, export_xlsx_report, run_excel_template
from .external_data import (
    ERA5_LAND_DEFAULT_VARIABLES,
    WORLD_BANK_DEFAULT_INDICATORS,
    fetch_world_bank_indicators,
    load_edgar_inventory,
    load_egrid_emission_rates,
    load_fied_units,
    load_iac_recommendations,
    retrieve_era5_land,
)
from .factors import DEFAULT_IMPACT_FACTORS
from .ghg import assess_ghg_boundaries, assess_methane_project
from .health import estimate_health_benefits, list_health_benefit_factors
from .impacts import assess_impacts
from .ingestion import (
    export_excel_compatible_bundle,
    infer_mapping,
    load_mapping,
    normalize_records,
    read_records,
    write_mapping,
    write_records,
)
from .materials import analyze_material_definition
from .models import ExergyStream
from .packs import (
    assess_intensity_with_pack,
    assess_performance_with_pack,
    assess_process_with_pack,
    assess_with_pack,
    bundled_technology_pack_info,
    load_technology_pack,
    technology_pack_coverage,
    validate_technology_pack,
    write_technology_pack_template,
)
from .preprocess import enrich_csv, load_csv, xai4heat_summary
from .processes import assess_process, list_process_templates
from .registry import DEFAULT_REGISTRY
from .reporting import export_excel_compatible_report, export_html, export_pdf
from .schema import list_schemas, load_schema
from .systems import analyze_system_definition, analyze_system_timeseries_definition
from .technology_models import (
    DEFAULT_TECHNOLOGY_MODEL_REGISTRY,
    evaluate_technology_model,
)
from .validation import (
    load_cross_product_conformance_contract,
    load_validation_coverage,
    run_bundled_validation_suite,
    validate_xai4heat_file,
)
from .weather import (
    monthly_weather_climatology,
    normalize_weather_performance,
)

_JSON_ERROR_MODE = False


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)


class _AgentArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        if _JSON_ERROR_MODE:
            print(
                _json(
                    error_response(
                        ValueError(message),
                        command="argument-parsing",
                    )
                ),
                file=sys.stderr,
            )
            raise SystemExit(2)
        super().error(message)


def _assignments(values: Sequence[str] | None, *, label: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for raw in values or ():
        if "=" not in raw:
            raise ValueError(f"{label} must use NAME=VALUE")
        name, value = raw.split("=", 1)
        if not name.strip():
            raise ValueError(f"{label} name must not be empty")
        result[name.strip()] = float(value)
    return result


def _integration_payload(result: Any, output: Path | None) -> dict[str, Any]:
    if output is not None:
        write_records(result.records, output)
    payload = result.to_dict(include_records=output is None)
    payload["output"] = str(output) if output is not None else None
    return payload


def _json_object_argument(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError("must be a valid JSON object") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("must be a JSON object")
    return parsed


def _add_assessment_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--pack", help="Bundled technology-pack name or explicit local JSON path"
    )
    parser.add_argument("--technology", help="Technology profile or alias")
    parser.add_argument("--service", help="Useful service profile or alias")
    parser.add_argument("--carrier", help="Input carrier profile or alias")
    parser.add_argument(
        "--energy", type=float, help="Energy quantity; omit for a per-MWh result"
    )
    parser.add_argument(
        "--unit", default="MWh", help="Energy unit, for example MWh, GJ, or MMBtu"
    )
    parser.add_argument("--basis", choices=("HHV", "LHV", "hhv", "lhv"))
    parser.add_argument(
        "--source-temperature", help="Source temperature, such as '80 C'"
    )
    parser.add_argument(
        "--return-temperature", help="Return temperature, such as '50 C'"
    )
    parser.add_argument(
        "--ambient-temperature", help="Reference temperature, such as '20 C'"
    )
    parser.add_argument("--cold-temperature", help="Cooling-service temperature")
    parser.add_argument("--temperature-unit", default="C", choices=("C", "F", "K"))
    parser.add_argument("--efficiency", type=float)
    parser.add_argument("--cop", type=float)
    parser.add_argument(
        "--performance",
        type=float,
        help="Generic performance parameter for a custom registered model",
    )
    parser.add_argument("--exergy-factor", type=float)
    parser.add_argument("--input-exergy-factor", type=float)
    parser.add_argument("--output-exergy-factor", type=float)
    parser.add_argument("--location", help="Location label retained in provenance")
    parser.add_argument(
        "--estimate-context",
        type=_json_object_argument,
        help='JSON object used to select a conditional published prior, for example {"capacity_kva":500}',
    )
    parser.add_argument(
        "--strict", action="store_true", help="Reject required assumed inputs"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        default=argparse.SUPPRESS,
    )


def _assessment_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "technology": args.technology,
        "service": args.service,
        "carrier": args.carrier,
        "energy": args.energy,
        "unit": args.unit,
        "basis": args.basis,
        "source_temperature": args.source_temperature,
        "return_temperature": args.return_temperature,
        "ambient_temperature": args.ambient_temperature,
        "cold_temperature": args.cold_temperature,
        "temperature_unit": args.temperature_unit,
        "efficiency": args.efficiency,
        "cop": args.cop,
        "performance": args.performance,
        "exergy_factor": args.exergy_factor,
        "input_exergy_factor": args.input_exergy_factor,
        "output_exergy_factor": args.output_exergy_factor,
        "location": args.location,
        "estimate_context": args.estimate_context,
        "strict": args.strict,
    }


def _stream(raw: dict[str, Any]) -> ExergyStream:
    return ExergyStream(
        name=str(raw["name"]),
        exergy=float(raw["exergy"]),
        unit=str(raw.get("unit", "MWh_ex")),
        energy=float(raw["energy"]) if raw.get("energy") is not None else None,
        exergy_factor=(
            float(raw["exergy_factor"])
            if raw.get("exergy_factor") is not None
            else None
        ),
        metadata=dict(raw.get("metadata", {})),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = _AgentArgumentParser(
        prog="exergy",
        description="Progressive-fidelity exergy screening and system analysis.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        default=argparse.SUPPRESS,
        help="Emit machine-readable JSON and structured JSON errors",
    )
    parser.add_argument(
        "--version", action="version", version="exergy-imperative 0.7.0"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    assess_parser = commands.add_parser("assess", help="Assess a stream or technology")
    _add_assessment_arguments(assess_parser)

    profile_parser = commands.add_parser("profiles", help="List bundled defaults")
    profile_parser.add_argument(
        "--category", choices=DEFAULT_REGISTRY.categories(), help="Filter profiles"
    )
    profile_parser.add_argument(
        "--pack", help="Overlay a bundled pack name or explicit local JSON path"
    )
    profile_parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        default=argparse.SUPPRESS,
    )

    enrich_parser = commands.add_parser(
        "enrich", help="Enrich thermal telemetry in a CSV"
    )
    enrich_parser.add_argument("input", type=Path)
    enrich_parser.add_argument("--output", type=Path, required=True)
    enrich_parser.add_argument("--profile", default="xai4heat")
    enrich_parser.add_argument("--fixed-reference-c", type=float, default=20.0)

    summary_parser = commands.add_parser(
        "xai-summary", help="Summarize XAI4Heat-compatible telemetry"
    )
    summary_parser.add_argument("input", type=Path)
    summary_parser.add_argument("--fixed-reference-c", type=float, default=20.0)

    balance_parser = commands.add_parser(
        "balance", help="Analyze a JSON exergy balance"
    )
    balance_parser.add_argument("input", type=Path)

    commands.add_parser("datasets", help="List supported public-data connectors")

    weather_parser = commands.add_parser(
        "weather", help="Explicitly fetch NASA POWER daily ambient temperature"
    )
    weather_parser.add_argument("--latitude", type=float, required=True)
    weather_parser.add_argument("--longitude", type=float, required=True)
    weather_parser.add_argument("--start", required=True, help="YYYYMMDD")
    weather_parser.add_argument("--end", required=True, help="YYYYMMDD")
    weather_parser.add_argument("--cache-dir", type=Path)

    world_bank_parser = commands.add_parser(
        "world-bank", help="Explicitly fetch World Bank economic indicators"
    )
    world_bank_parser.add_argument(
        "country", help="World Bank country or aggregate code"
    )
    world_bank_parser.add_argument(
        "--indicator",
        action="append",
        help="WDI indicator ID; repeat as needed (defaults to CPI, deflator, and exchange rate)",
    )
    world_bank_parser.add_argument("--start-year", type=int)
    world_bank_parser.add_argument("--end-year", type=int)
    world_bank_parser.add_argument("--cache-dir", type=Path)
    world_bank_parser.add_argument("--output", type=Path)

    era5_parser = commands.add_parser(
        "era5-land", help="Explicitly retrieve authenticated ERA5-Land files"
    )
    era5_parser.add_argument("--latitude", type=float, required=True)
    era5_parser.add_argument("--longitude", type=float, required=True)
    era5_parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    era5_parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    era5_parser.add_argument("--target-dir", type=Path, required=True)
    era5_parser.add_argument(
        "--variable",
        action="append",
        help="CDS variable ID; repeat as needed",
    )
    era5_parser.add_argument("--format", choices=("netcdf", "grib"), default="netcdf")
    era5_parser.add_argument("--overwrite", action="store_true")

    edgar_parser = commands.add_parser(
        "edgar", help="Normalize a local EDGAR country/sector workbook"
    )
    edgar_parser.add_argument("input", type=Path)
    edgar_parser.add_argument("--pollutant")
    edgar_parser.add_argument("--sheet", default="IPCC 2006")
    edgar_parser.add_argument("--header-row", type=int)
    edgar_parser.add_argument("--source-unit", default="auto")
    edgar_parser.add_argument("--start-year", type=int)
    edgar_parser.add_argument("--end-year", type=int)
    edgar_parser.add_argument("--output", type=Path)

    egrid_parser = commands.add_parser(
        "egrid", help="Normalize a local EPA eGRID workbook or export"
    )
    egrid_parser.add_argument("input", type=Path)
    egrid_parser.add_argument(
        "--geography", choices=("subregion", "state"), default="subregion"
    )
    egrid_parser.add_argument(
        "--basis", choices=("total", "non-baseload"), default="total"
    )
    egrid_parser.add_argument("--sheet")
    egrid_parser.add_argument("--header-row", type=int)
    egrid_parser.add_argument("--rate-unit", default="auto")
    egrid_parser.add_argument("--year", type=int)
    egrid_parser.add_argument("--output", type=Path)

    iac_parser = commands.add_parser(
        "iac", help="Normalize a local DOE ITAC/IAC recommendation database"
    )
    iac_parser.add_argument("input", type=Path)
    iac_parser.add_argument("--assessment-file", type=Path)
    iac_parser.add_argument("--recommendation-sheet", default="RECC")
    iac_parser.add_argument("--assessment-sheet", default="ASSESS")
    iac_parser.add_argument("--implemented-only", action="store_true")
    iac_parser.add_argument("--no-assessment-data", action="store_true")
    iac_parser.add_argument("--output", type=Path)

    fied_parser = commands.add_parser(
        "fied", help="Normalize a local FIED unit-level export"
    )
    fied_parser.add_argument("input", type=Path)
    fied_parser.add_argument("--sheet", default=0)
    fied_parser.add_argument("--header-row", type=int, default=1)
    fied_parser.add_argument("--output", type=Path)

    factor_parser = commands.add_parser(
        "factors", help="Inspect grid, fuel, GWP, and pollutant-health factors"
    )
    factor_parser.add_argument("category", choices=("grid", "fuel", "gwp", "health"))
    factor_parser.add_argument("--location")
    factor_parser.add_argument("--year", type=int)

    impact_parser = commands.add_parser(
        "impacts", help="Screen greenhouse-gas and air-pollutant impacts"
    )
    impact_parser.add_argument("--energy", type=float)
    impact_parser.add_argument("--unit", default="MWh")
    impact_parser.add_argument("--carrier")
    impact_parser.add_argument("--country")
    impact_parser.add_argument("--year", type=int)
    impact_parser.add_argument(
        "--gas", action="append", help="Additional gas mass as GAS=KG"
    )
    impact_parser.add_argument(
        "--refrigerant",
        action="append",
        help="Refrigerant leakage as GAS=KG",
    )
    impact_parser.add_argument(
        "--pollutant", action="append", help="Pollutant mass as NAME=KG"
    )
    impact_parser.add_argument(
        "--damage-cost",
        action="append",
        help="Optional user factor as POLLUTANT=CURRENCY_PER_KG",
    )
    impact_parser.add_argument("--currency", default="USD")

    health_factor_parser = commands.add_parser(
        "health-factors",
        help="List sourced EPA public-health benefit screening factors",
    )
    health_factor_parser.add_argument("--region")
    health_factor_parser.add_argument("--project-type")
    health_factor_parser.add_argument("--available-only", action="store_true")

    health_parser = commands.add_parser(
        "health-benefits",
        help="Estimate monetized outdoor-air public-health benefits",
    )
    health_parser.add_argument("--region", required=True, help="EPA AVERT region")
    health_parser.add_argument("--project-type", required=True)
    health_parser.add_argument(
        "--energy", type=float, help="Annual intervention energy"
    )
    health_parser.add_argument("--unit", default="MWh")
    health_parser.add_argument("--analysis-year", type=int)
    health_parser.add_argument("--low-cents-per-kwh", type=float)
    health_parser.add_argument("--high-cents-per-kwh", type=float)

    processes_parser = commands.add_parser(
        "processes", help="List industry process templates"
    )
    processes_parser.add_argument(
        "--pack", help="Overlay a bundled pack name or explicit local JSON path"
    )
    process_parser = commands.add_parser(
        "process", help="Assess an industry process template"
    )
    process_parser.add_argument("template")
    process_parser.add_argument(
        "--pack", help="Bundled technology-pack name or explicit local JSON path"
    )
    process_parser.add_argument("--energy", type=float)
    process_parser.add_argument("--unit", default="MWh")
    process_parser.add_argument("--country")
    process_parser.add_argument("--year", type=int)
    process_parser.add_argument("--improvement-fraction", type=float)
    process_parser.add_argument("--capital-cost", type=float)
    process_parser.add_argument(
        "--annualization-factor",
        type=float,
        help="Reporting periods per year; use 1 when --energy is already annual.",
    )
    process_parser.add_argument("--energy-price", type=float, default=0.0)
    process_parser.add_argument("--discount-rate", type=float, default=0.07)
    process_parser.add_argument("--project-life", type=int, default=20)
    process_parser.add_argument("--carbon-price", type=float, default=0.0)
    process_parser.add_argument("--currency", default="USD")
    process_parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        default=argparse.SUPPRESS,
    )

    run_parser = commands.add_parser("run", help="Run a stable agent recipe from JSON")
    run_parser.add_argument("input", type=Path, help="Agent recipe JSON file")
    run_mode = run_parser.add_mutually_exclusive_group()
    run_mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Calculate results but suppress every requested file write",
    )
    run_mode.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate the recipe contract without calculating or writing",
    )

    commands.add_parser(
        "capabilities", help="List agent workflows, contracts, and safety behavior"
    )
    search_parser = commands.add_parser(
        "search",
        help="Search workflows, profiles, models, materials, packs, and schemas",
    )
    search_parser.add_argument("query")
    search_parser.add_argument(
        "--kind",
        choices=(
            "auto",
            "workflow",
            "process",
            "profile",
            "component",
            "model",
            "material",
            "pack",
            "schema",
        ),
        default="auto",
    )
    search_parser.add_argument("--limit", type=int, default=10)
    packs_parser = commands.add_parser(
        "packs", help="List or describe bundled data-only technology packs"
    )
    packs_parser.add_argument("name", nargs="?")
    pack_coverage_parser = commands.add_parser(
        "pack-coverage",
        help="Show automatic estimates and explicit-input gaps for every technology",
    )
    pack_coverage_parser.add_argument("source")
    commands.add_parser("models", help="List registered technology-model contracts")
    model_evaluate_parser = commands.add_parser(
        "model-evaluate", help="Evaluate a registered technology model from JSON"
    )
    model_evaluate_parser.add_argument("input", type=Path)
    pack_validate_parser = commands.add_parser(
        "pack-validate", help="Validate a bundled or local technology pack"
    )
    pack_validate_parser.add_argument("source")
    pack_scaffold_parser = commands.add_parser(
        "pack-scaffold", help="Write a safe technology-pack JSON scaffold"
    )
    pack_scaffold_parser.add_argument("output", type=Path)
    intensity_parser = commands.add_parser(
        "intensity", help="Estimate process input energy from a pack intensity prior"
    )
    intensity_parser.add_argument("pack")
    intensity_parser.add_argument("technology")
    intensity_parser.add_argument("output_mass", type=float)
    intensity_parser.add_argument("--unit", default="t")
    intensity_parser.add_argument("--specific-energy", type=float)
    intensity_parser.add_argument("--estimate-context", type=_json_object_argument)
    intensity_parser.add_argument("--strict", action="store_true")
    performance_parser = commands.add_parser(
        "performance",
        help="Estimate technology energy output without assuming exergy quality",
    )
    performance_parser.add_argument("pack")
    performance_parser.add_argument("technology")
    performance_parser.add_argument("input_energy", type=float)
    performance_parser.add_argument("--unit", default="MWh")
    performance_parser.add_argument("--performance", type=float)
    performance_parser.add_argument("--estimate-context", type=_json_object_argument)
    performance_parser.add_argument("--strict", action="store_true")
    schema_parser = commands.add_parser(
        "schema", help="List schemas or print one packaged JSON Schema"
    )
    schema_parser.add_argument("name", nargs="?")
    describe_parser = commands.add_parser(
        "describe", help="Describe a workflow, process template, or profile"
    )
    describe_parser.add_argument("name")
    describe_parser.add_argument(
        "--kind",
        choices=(
            "auto",
            "workflow",
            "process",
            "profile",
            "component",
            "model",
            "material",
            "pack",
            "schema",
        ),
        default="auto",
    )

    economic_parser = commands.add_parser(
        "economics", help="Evaluate a JSON project-economic case"
    )
    economic_parser.add_argument("input", type=Path)

    technology_cost_parser = commands.add_parser(
        "technology-cost", help="Evaluate a user-supplied technology cost scenario"
    )
    technology_cost_parser.add_argument("input", type=Path)

    ghg_parser = commands.add_parser(
        "ghg-boundaries", help="Evaluate a JSON GHG inventory with explicit boundaries"
    )
    ghg_parser.add_argument("input", type=Path)

    methane_parser = commands.add_parser(
        "methane", help="Evaluate a JSON methane venting, flaring, or recovery project"
    )
    methane_parser.add_argument("input", type=Path)

    weather_normalize_parser = commands.add_parser(
        "weather-normalize",
        help="Weather-normalize a metric in daily CSV data",
    )
    weather_normalize_parser.add_argument("input", type=Path)
    weather_normalize_parser.add_argument("--value-field", required=True)
    weather_normalize_parser.add_argument("--unit", default="")
    weather_normalize_parser.add_argument("--date-field")
    weather_normalize_parser.add_argument("--temperature-field")
    weather_normalize_parser.add_argument("--heating-base-c", type=float, default=18.0)
    weather_normalize_parser.add_argument("--cooling-base-c", type=float, default=18.0)
    weather_normalize_parser.add_argument("--normal-hdd", type=float)
    weather_normalize_parser.add_argument("--normal-cdd", type=float)
    weather_normalize_parser.add_argument(
        "--climatology",
        type=Path,
        help="Optional daily CSV used to calculate monthly normal weather",
    )

    ingest_parser = commands.add_parser(
        "ingest", help="Normalize CSV, Excel, Parquet, JSON, or JSONL records"
    )
    ingest_parser.add_argument("input", type=Path)
    ingest_parser.add_argument("--output", type=Path)
    ingest_parser.add_argument("--excel-bundle", type=Path)
    ingest_parser.add_argument("--mapping", type=Path)
    ingest_parser.add_argument("--mapping-out", type=Path)
    ingest_parser.add_argument("--required", action="append", default=[])
    ingest_parser.add_argument("--timezone")
    ingest_parser.add_argument(
        "--missing-policy",
        choices=("keep", "drop", "raise", "forward-fill", "interpolate"),
    )
    ingest_parser.add_argument("--sheet", default=0)

    report_parser = commands.add_parser(
        "report", help="Export a process recipe to HTML, PDF, and/or tabular files"
    )
    report_parser.add_argument("input", type=Path, help="JSON process recipe")
    report_parser.add_argument("--html", type=Path)
    report_parser.add_argument("--pdf", type=Path)
    report_parser.add_argument("--excel-dir", type=Path)

    excel_template_parser = commands.add_parser(
        "excel-template", help="Create an editable native Excel input template"
    )
    excel_template_parser.add_argument("kind")
    excel_template_parser.add_argument("output", type=Path)

    excel_run_parser = commands.add_parser(
        "excel-run", help="Run a native Excel input template"
    )
    excel_run_parser.add_argument("input", type=Path)
    excel_run_parser.add_argument("--output", type=Path)

    adapter_parser = commands.add_parser(
        "adapt-local", help="Apply a JSON adapter to a user-owned local dataset"
    )
    adapter_parser.add_argument("input", type=Path)
    adapter_parser.add_argument("adapter", type=Path)
    adapter_parser.add_argument("--output", type=Path)
    adapter_parser.add_argument(
        "--missing-policy",
        default="drop",
        choices=("keep", "drop", "raise", "forward-fill", "interpolate"),
    )

    engineering_parser = commands.add_parser(
        "engineering", help="Run a detailed industrial engineering screen from JSON"
    )
    engineering_parser.add_argument(
        "model",
        choices=("steam", "heat-pump", "furnace", "refrigeration", "compressed-air"),
    )
    engineering_parser.add_argument("input", type=Path)

    waste_heat_parser = commands.add_parser(
        "waste-heat", help="Match waste-heat sources to compatible demands from JSON"
    )
    waste_heat_parser.add_argument("input", type=Path)

    system_parser = commands.add_parser(
        "system", help="Analyze a connected component system from JSON"
    )
    system_parser.add_argument("input", type=Path)
    system_parser.add_argument(
        "--pack", help="Optional bundled pack name or explicit local JSON path"
    )
    system_timeseries_parser = commands.add_parser(
        "system-timeseries",
        help="Aggregate chronological connected-system interval records from JSON",
    )
    system_timeseries_parser.add_argument("input", type=Path)
    system_timeseries_parser.add_argument(
        "--pack", help="Optional bundled pack name or explicit local JSON path"
    )
    material_parser = commands.add_parser(
        "material-balance",
        help="Analyze mass, composition, and explicit chemical exergy from JSON",
    )
    material_parser.add_argument("input", type=Path)

    validate_parser = commands.add_parser(
        "validate", help="Run bundled reference validation or a local XAI4Heat check"
    )
    validate_parser.add_argument("--xai4heat", type=Path)
    validate_parser.add_argument(
        "--coverage",
        action="store_true",
        help="Show scientific assurance levels and limitations for every capability",
    )
    validate_parser.add_argument(
        "--conformance",
        action="store_true",
        help="Show the vendored cross-product physics and reporting contract",
    )
    validate_parser.add_argument("--sheet", default=0)
    validate_parser.add_argument("--header-row", type=int, default=1)
    for command_parser in commands.choices.values():
        if not any(
            "--json" in action.option_strings for action in command_parser._actions
        ):
            command_parser.add_argument(
                "--json",
                action="store_true",
                dest="as_json",
                default=argparse.SUPPRESS,
                help="Emit machine-readable JSON and structured JSON errors",
            )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    global _JSON_ERROR_MODE
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    _JSON_ERROR_MODE = "--json" in raw_arguments
    parser = build_parser()
    args = parser.parse_args(raw_arguments)
    if not hasattr(args, "as_json"):
        args.as_json = False
    try:
        if args.command == "run":
            recipe = json.loads(args.input.read_text(encoding="utf-8"))
            mode = (
                "validate-only"
                if args.validate_only
                else "dry-run"
                if args.dry_run
                else None
            )
            print(_json(run_recipe(recipe, mode=mode).to_dict()))
            return 0
        if args.command == "capabilities":
            print(_json(list_capabilities()))
            return 0
        if args.command == "search":
            print(
                _json(search_capabilities(args.query, kind=args.kind, limit=args.limit))
            )
            return 0
        if args.command == "packs":
            if args.name:
                print(_json(load_technology_pack(args.name).to_dict()))
            else:
                print(_json(list(bundled_technology_pack_info())))
            return 0
        if args.command == "pack-validate":
            print(_json(validate_technology_pack(args.source)))
            return 0
        if args.command == "pack-coverage":
            print(_json(technology_pack_coverage(args.source)))
            return 0
        if args.command == "pack-scaffold":
            output = write_technology_pack_template(args.output)
            print(_json({"output": str(output)}))
            return 0
        if args.command == "intensity":
            result = assess_intensity_with_pack(
                args.pack,
                args.technology,
                args.output_mass,
                output_unit=args.unit,
                specific_energy_mwh_per_tonne=args.specific_energy,
                estimate_context=args.estimate_context,
                strict=args.strict,
            )
            print(_json(result.to_dict()))
            return 0
        if args.command == "performance":
            result = assess_performance_with_pack(
                args.pack,
                args.technology,
                args.input_energy,
                unit=args.unit,
                performance=args.performance,
                estimate_context=args.estimate_context,
                strict=args.strict,
            )
            print(_json(result.to_dict()))
            return 0
        if args.command == "schema":
            print(_json(load_schema(args.name) if args.name else list_schemas()))
            return 0
        if args.command == "describe":
            print(_json(describe_target(args.name, kind=args.kind)))
            return 0
        if args.command == "assess":
            result = (
                assess_with_pack(args.pack, **_assessment_kwargs(args))
                if args.pack
                else assess(**_assessment_kwargs(args))
            )
            print(_json(result.to_dict()) if args.as_json else result.summary())
            return 0
        if args.command == "profiles":
            registry = (
                load_technology_pack(args.pack).registry()
                if args.pack
                else DEFAULT_REGISTRY
            )
            profiles = registry.list(args.category)
            if args.as_json:
                print(_json([profile.to_dict() for profile in profiles]))
            else:
                for profile in profiles:
                    print(f"{profile.category:10} {profile.id:35} {profile.label}")
            return 0
        if args.command == "enrich":
            rows = enrich_csv(
                args.input,
                args.output,
                profile=args.profile,
                fixed_reference_c=args.fixed_reference_c,
            )
            if args.as_json:
                print(
                    _json(
                        {
                            "record_count": len(rows),
                            "output": str(args.output),
                        }
                    )
                )
            else:
                print(f"Wrote {len(rows)} enriched records to {args.output}")
            return 0
        if args.command == "xai-summary":
            print(
                _json(
                    xai4heat_summary(
                        load_csv(args.input), fixed_reference_c=args.fixed_reference_c
                    )
                )
            )
            return 0
        if args.command == "balance":
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            result = analyze_balance(
                str(payload.get("name", args.input.stem)),
                inputs=(_stream(item) for item in payload.get("inputs", [])),
                products=(_stream(item) for item in payload.get("products", [])),
                losses=(_stream(item) for item in payload.get("losses", [])),
                destructions=(
                    (_stream(item) for item in payload["destructions"])
                    if "destructions" in payload
                    else None
                ),
                unit=str(payload.get("unit", "MWh_ex")),
            )
            print(_json(result.to_dict()))
            return 0
        if args.command == "datasets":
            print(_json([record.to_dict() for record in list_datasets()]))
            return 0
        if args.command == "weather":
            print(
                _json(
                    fetch_nasa_power_temperature(
                        args.latitude,
                        args.longitude,
                        args.start,
                        args.end,
                        cache_dir=args.cache_dir,
                    )
                )
            )
            return 0
        if args.command == "world-bank":
            result = fetch_world_bank_indicators(
                args.country,
                indicators=args.indicator or WORLD_BANK_DEFAULT_INDICATORS,
                start_year=args.start_year,
                end_year=args.end_year,
                cache_dir=args.cache_dir,
            )
            print(_json(_integration_payload(result, args.output)))
            return 0
        if args.command == "era5-land":
            print(
                _json(
                    retrieve_era5_land(
                        args.latitude,
                        args.longitude,
                        args.start,
                        args.end,
                        args.target_dir,
                        variables=args.variable or ERA5_LAND_DEFAULT_VARIABLES,
                        data_format=args.format,
                        overwrite=args.overwrite,
                    )
                )
            )
            return 0
        if args.command == "edgar":
            sheet = int(args.sheet) if str(args.sheet).isdigit() else args.sheet
            result = load_edgar_inventory(
                args.input,
                pollutant=args.pollutant,
                sheet_name=sheet,
                header_row=args.header_row,
                source_unit=args.source_unit,
                start_year=args.start_year,
                end_year=args.end_year,
            )
            print(_json(_integration_payload(result, args.output)))
            return 0
        if args.command == "egrid":
            sheet = (
                int(args.sheet)
                if args.sheet is not None and str(args.sheet).isdigit()
                else args.sheet
            )
            result = load_egrid_emission_rates(
                args.input,
                geography=args.geography,
                basis=args.basis,
                sheet_name=sheet,
                header_row=args.header_row,
                rate_unit=args.rate_unit,
                year=args.year,
            )
            print(_json(_integration_payload(result, args.output)))
            return 0
        if args.command == "iac":
            recommendation_sheet = (
                int(args.recommendation_sheet)
                if str(args.recommendation_sheet).isdigit()
                else args.recommendation_sheet
            )
            assessment_sheet = (
                int(args.assessment_sheet)
                if str(args.assessment_sheet).isdigit()
                else args.assessment_sheet
            )
            result = load_iac_recommendations(
                args.input,
                assessment_path=args.assessment_file,
                recommendation_sheet=recommendation_sheet,
                assessment_sheet=assessment_sheet,
                implemented_only=args.implemented_only,
                include_assessment_data=not args.no_assessment_data,
            )
            print(_json(_integration_payload(result, args.output)))
            return 0
        if args.command == "fied":
            sheet = int(args.sheet) if str(args.sheet).isdigit() else args.sheet
            result = load_fied_units(
                args.input,
                sheet_name=sheet,
                header_row=args.header_row,
            )
            print(_json(_integration_payload(result, args.output)))
            return 0
        if args.command == "factors":
            if args.category == "grid":
                if args.location:
                    payload = DEFAULT_IMPACT_FACTORS.grid_emissions(
                        args.location, args.year
                    ).to_dict()
                else:
                    payload = [
                        DEFAULT_IMPACT_FACTORS.grid_emissions(iso3, args.year).to_dict()
                        for iso3, _ in DEFAULT_IMPACT_FACTORS.grid_locations()
                    ]
            elif args.category == "fuel":
                payload = [
                    item.to_dict()
                    for item in DEFAULT_IMPACT_FACTORS.list_fuel_emissions()
                ]
            elif args.category == "gwp":
                payload = [
                    item.to_dict()
                    for item in DEFAULT_IMPACT_FACTORS.list_warming_potentials()
                ]
            else:
                payload = [
                    item.to_dict()
                    for item in DEFAULT_IMPACT_FACTORS.list_pollutant_health()
                ]
            print(_json(payload))
            return 0
        if args.command == "impacts":
            result = assess_impacts(
                args.energy,
                unit=args.unit,
                carrier=args.carrier,
                country=args.country,
                year=args.year,
                gases_kg=_assignments(args.gas, label="gas"),
                refrigerant_leakage_kg=_assignments(
                    args.refrigerant, label="refrigerant"
                ),
                pollutant_masses_kg=_assignments(args.pollutant, label="pollutant"),
                damage_costs_per_kg=_assignments(args.damage_cost, label="damage cost"),
                currency=args.currency,
            )
            print(_json(result.to_dict()))
            return 0
        if args.command == "health-factors":
            factors = list_health_benefit_factors(
                region=args.region,
                project_type=args.project_type,
                include_unavailable=not args.available_only,
            )
            print(_json([item.to_dict() for item in factors]))
            return 0
        if args.command == "health-benefits":
            result = estimate_health_benefits(
                region=args.region,
                project_type=args.project_type,
                energy=args.energy,
                unit=args.unit,
                analysis_year=args.analysis_year,
                low_cents_per_kwh=args.low_cents_per_kwh,
                high_cents_per_kwh=args.high_cents_per_kwh,
            )
            print(_json(result.to_dict()))
            return 0
        if args.command == "processes":
            catalog = (
                load_technology_pack(args.pack).process_catalog() if args.pack else None
            )
            print(
                _json(
                    [item.to_dict() for item in list_process_templates(catalog=catalog)]
                )
            )
            return 0
        if args.command == "process":
            economics_options = None
            if args.capital_cost is not None:
                economics_options = {
                    "capital_cost": args.capital_cost,
                    "energy_price_per_mwh": args.energy_price,
                    "discount_rate": args.discount_rate,
                    "project_life_years": args.project_life,
                    "carbon_price_per_tonne": args.carbon_price,
                    "currency": args.currency,
                }
            process_options = {
                "unit": args.unit,
                "country": args.country,
                "year": args.year,
                "improvement_fraction": args.improvement_fraction,
                "economics_options": economics_options,
                "annualization_factor": args.annualization_factor,
            }
            result = (
                assess_process_with_pack(
                    args.pack,
                    args.template,
                    args.energy,
                    **process_options,
                )
                if args.pack
                else assess_process(
                    args.template,
                    args.energy,
                    **process_options,
                )
            )
            print(_json(result.to_dict()) if args.as_json else result.summary())
            return 0
        if args.command == "economics":
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            print(_json(evaluate_economics(**payload).to_dict()))
            return 0
        if args.command == "technology-cost":
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            print(_json(evaluate_technology_cost_scenario(payload).to_dict()))
            return 0
        if args.command == "ghg-boundaries":
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            print(_json(assess_ghg_boundaries(**payload).to_dict()))
            return 0
        if args.command == "methane":
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            print(_json(assess_methane_project(**payload).to_dict()))
            return 0
        if args.command == "weather-normalize":
            records = load_csv(args.input)
            climatology = None
            if args.climatology is not None:
                climatology = monthly_weather_climatology(
                    load_csv(args.climatology),
                    date_field=args.date_field,
                    temperature_field=args.temperature_field,
                    heating_base_c=args.heating_base_c,
                    cooling_base_c=args.cooling_base_c,
                    source=str(args.climatology),
                )
            result = normalize_weather_performance(
                records,
                value_field=args.value_field,
                unit=args.unit,
                climatology=climatology,
                normal_heating_degree_days=args.normal_hdd,
                normal_cooling_degree_days=args.normal_cdd,
                date_field=args.date_field,
                temperature_field=args.temperature_field,
                heating_base_c=args.heating_base_c,
                cooling_base_c=args.cooling_base_c,
            )
            print(_json(result.to_dict()))
            return 0
        if args.command == "ingest":
            if (
                args.output is None
                and args.excel_bundle is None
                and args.mapping_out is None
            ):
                raise ValueError(
                    "ingest requires --output, --excel-bundle, and/or --mapping-out"
                )
            sheet = int(args.sheet) if str(args.sheet).isdigit() else args.sheet
            rows = read_records(args.input, sheet_name=sheet)
            if args.mapping:
                mapping = load_mapping(args.mapping)
                if args.timezone is not None:
                    mapping = replace(mapping, timezone=args.timezone)
                if args.required:
                    mapping = replace(
                        mapping,
                        required=tuple(
                            dict.fromkeys((*mapping.required, *args.required))
                        ),
                    )
            else:
                columns = tuple(dict.fromkeys(key for row in rows for key in row))
                mapping = infer_mapping(
                    columns,
                    required=args.required,
                    timezone=args.timezone,
                )
            result = normalize_records(
                rows, mapping=mapping, missing_policy=args.missing_policy
            )
            if args.output:
                write_records(result.records, args.output)
            if args.excel_bundle:
                export_excel_compatible_bundle(result, args.excel_bundle)
            if args.mapping_out:
                write_mapping(result.mapping, args.mapping_out)
            print(_json(result.to_dict(include_records=False)))
            return 0
        if args.command == "report":
            if args.html is None and args.pdf is None and args.excel_dir is None:
                raise ValueError("report requires --html, --pdf, and/or --excel-dir")
            recipe = json.loads(args.input.read_text(encoding="utf-8"))
            result = assess_process(**recipe)
            outputs: list[str] = []
            if args.html:
                outputs.append(str(export_html(result, args.html)))
            if args.pdf:
                outputs.append(str(export_pdf(result, args.pdf)))
            if args.excel_dir:
                outputs.extend(
                    str(path)
                    for path in export_excel_compatible_report(result, args.excel_dir)
                )
            print(_json({"outputs": outputs}))
            return 0
        if args.command == "excel-template":
            output = create_excel_template(args.kind, args.output)
            print(_json({"output": str(output)}))
            return 0
        if args.command == "excel-run":
            result = run_excel_template(args.input)
            output = None
            if args.output is not None:
                output = export_xlsx_report(result, args.output)
            print(
                _json(
                    {
                        "result": result.to_dict(),
                        "output": str(output) if output is not None else None,
                    }
                )
            )
            return 0
        if args.command == "adapt-local":
            result = adapt_local_dataset(
                args.input,
                args.adapter,
                missing_policy=args.missing_policy,
            )
            output = None
            if args.output is not None:
                if args.output.suffix.lower() == ".xlsx":
                    output = result.export_xlsx(str(args.output))
                else:
                    write_records(result.records, args.output)
                    output = args.output
            payload = result.to_dict(include_records=args.output is None)
            payload["output"] = str(output) if output is not None else None
            print(_json(payload))
            return 0
        if args.command == "engineering":
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            dispatch = {
                "steam": analyze_steam_system,
                "heat-pump": analyze_heat_pump,
                "furnace": analyze_furnace,
                "refrigeration": analyze_refrigeration,
                "compressed-air": analyze_compressed_air,
            }
            print(_json(dispatch[args.model](**payload).to_dict()))
            return 0
        if args.command == "waste-heat":
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            sources = payload.pop("sources")
            demands = payload.pop("demands")
            print(_json(match_waste_heat(sources, demands, **payload).to_dict()))
            return 0
        if args.command in {"system", "system-timeseries"}:
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            pack_source = args.pack or payload.pop("pack", None)
            registry = (
                load_technology_pack(pack_source).registry()
                if pack_source is not None
                else None
            )
            result = (
                analyze_system_definition(payload, registry=registry)
                if args.command == "system"
                else analyze_system_timeseries_definition(payload, registry=registry)
            )
            print(_json(result.to_dict()))
            return 0
        if args.command == "models":
            print(
                _json(
                    [
                        item.to_dict()
                        for item in DEFAULT_TECHNOLOGY_MODEL_REGISTRY.list()
                    ]
                )
            )
            return 0
        if args.command == "model-evaluate":
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            print(_json(evaluate_technology_model(**payload).to_dict()))
            return 0
        if args.command == "material-balance":
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            print(_json(analyze_material_definition(payload).to_dict()))
            return 0
        if args.command == "validate":
            selected_views = sum(
                (bool(args.coverage), bool(args.conformance), args.xai4heat is not None)
            )
            if selected_views > 1:
                raise ValueError(
                    "--coverage, --conformance, and --xai4heat cannot be combined"
                )
            if args.coverage:
                print(_json(load_validation_coverage().to_dict()))
                return 0
            if args.conformance:
                print(_json(load_cross_product_conformance_contract()))
                return 0
            if args.xai4heat is None:
                result = run_bundled_validation_suite()
            else:
                sheet = int(args.sheet) if str(args.sheet).isdigit() else args.sheet
                result = validate_xai4heat_file(
                    args.xai4heat,
                    sheet_name=sheet,
                    header_row=args.header_row,
                )
            print(_json(result.to_dict()))
            return 0 if result.passed else 1
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        ImportError,
        MissingInputError,
        AgentNativeError,
    ) as exc:
        if args.as_json:
            print(
                _json(error_response(exc, command=args.command)),
                file=sys.stderr,
            )
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2
    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
