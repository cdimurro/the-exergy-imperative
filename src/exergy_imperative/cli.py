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
from .factors import DEFAULT_IMPACT_FACTORS
from .ghg import assess_ghg_boundaries, assess_methane_project
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
from .models import ExergyStream
from .preprocess import enrich_csv, load_csv, xai4heat_summary
from .processes import assess_process, list_process_templates
from .registry import DEFAULT_REGISTRY
from .reporting import export_excel_compatible_report, export_html, export_pdf
from .schema import list_schemas, load_schema
from .validation import run_bundled_validation_suite, validate_xai4heat_file
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


def _add_assessment_arguments(parser: argparse.ArgumentParser) -> None:
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
    parser.add_argument("--exergy-factor", type=float)
    parser.add_argument("--input-exergy-factor", type=float)
    parser.add_argument("--output-exergy-factor", type=float)
    parser.add_argument("--location", help="Location label retained in provenance")
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
        "exergy_factor": args.exergy_factor,
        "input_exergy_factor": args.input_exergy_factor,
        "output_exergy_factor": args.output_exergy_factor,
        "location": args.location,
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
        "--version", action="version", version="exergy-imperative 0.2.0"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    assess_parser = commands.add_parser("assess", help="Assess a stream or technology")
    _add_assessment_arguments(assess_parser)

    profile_parser = commands.add_parser("profiles", help="List bundled defaults")
    profile_parser.add_argument(
        "--category", choices=DEFAULT_REGISTRY.categories(), help="Filter profiles"
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

    commands.add_parser("processes", help="List industry process templates")
    process_parser = commands.add_parser(
        "process", help="Assess an industry process template"
    )
    process_parser.add_argument("template")
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
        choices=("auto", "workflow", "process", "profile"),
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

    validate_parser = commands.add_parser(
        "validate", help="Run bundled reference validation or a local XAI4Heat check"
    )
    validate_parser.add_argument("--xai4heat", type=Path)
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
        if args.command == "schema":
            print(_json(load_schema(args.name) if args.name else list_schemas()))
            return 0
        if args.command == "describe":
            print(_json(describe_target(args.name, kind=args.kind)))
            return 0
        if args.command == "assess":
            result = assess(**_assessment_kwargs(args))
            print(_json(result.to_dict()) if args.as_json else result.summary())
            return 0
        if args.command == "profiles":
            profiles = DEFAULT_REGISTRY.list(args.category)
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
        if args.command == "processes":
            print(_json([item.to_dict() for item in list_process_templates()]))
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
            result = assess_process(
                args.template,
                args.energy,
                unit=args.unit,
                country=args.country,
                year=args.year,
                improvement_fraction=args.improvement_fraction,
                economics_options=economics_options,
                annualization_factor=args.annualization_factor,
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
        if args.command == "validate":
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
