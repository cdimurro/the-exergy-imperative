"""Basic charts plus HTML, PDF, and Excel-compatible report exports."""

from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from .economics import EconomicResult, TechnologyEconomicResult
from .engineering import EngineeringModelResult, WasteHeatMatchResult
from .factors import DEFAULT_IMPACT_FACTORS
from .ghg import GHGBoundaryResult, MethaneProjectResult
from .impacts import EnvironmentalResult
from .ingestion import _spreadsheet_safe_value
from .models import AssessmentResult
from .processes import ProcessAssessment
from .registry import DEFAULT_REGISTRY
from .weather import WeatherNormalizationResult

Reportable = (
    AssessmentResult
    | EnvironmentalResult
    | ProcessAssessment
    | GHGBoundaryResult
    | MethaneProjectResult
    | EconomicResult
    | TechnologyEconomicResult
    | WeatherNormalizationResult
    | EngineeringModelResult
    | WasteHeatMatchResult
)


@dataclass(frozen=True)
class ChartSpec:
    id: str
    title: str
    unit: str
    values: tuple[tuple[str, float], ...]
    color: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "unit": self.unit,
            "values": [
                {"label": label, "value": value} for label, value in self.values
            ],
            "color": self.color,
        }


@dataclass(frozen=True)
class ReportView:
    title: str
    subtitle: str
    key_metrics: tuple[tuple[str, float | str, str], ...]
    tables: Mapping[str, tuple[Mapping[str, Any], ...]]
    charts: tuple[ChartSpec, ...]
    warnings: tuple[str, ...]
    sources: tuple[Mapping[str, str], ...]
    payload: Mapping[str, Any]


def _estimate_value(value: Any) -> float | None:
    return float(value.value) if value is not None else None


def _assessment_chart(result: AssessmentResult) -> ChartSpec | None:
    values = tuple(
        (label, value)
        for label, value in (
            ("Input energy", _estimate_value(result.input_energy)),
            ("Input exergy", _estimate_value(result.input_exergy)),
            ("Useful energy", _estimate_value(result.useful_energy)),
            ("Useful exergy", _estimate_value(result.useful_exergy)),
            (
                "Destroyed or lost",
                _estimate_value(result.exergy_destroyed_or_lost),
            ),
        )
        if value is not None
    )
    if not values:
        return None
    return ChartSpec(
        "energy-exergy",
        (
            "Energy and exergy normalized per 1 MWh input"
            if result.normalized
            else "Energy and exergy at the declared boundary"
        ),
        "MWh per 1 MWh input" if result.normalized else "MWh per reporting period",
        values,
        "#2563EB",
    )


def _source_records(
    source_ids: Iterable[str],
    *originating_catalogs: Mapping[str, Mapping[str, Any]],
) -> tuple[Mapping[str, str], ...]:
    catalog = {
        **DEFAULT_IMPACT_FACTORS.sources,
        **DEFAULT_REGISTRY.sources,
    }
    for originating_catalog in originating_catalogs:
        catalog.update(originating_catalog)
    records: list[Mapping[str, str]] = []
    for source_id in sorted(set(source_ids)):
        raw = catalog.get(source_id, {})
        records.append(
            {
                "source_id": source_id,
                "title": str(raw.get("title", source_id)),
                "url": str(raw.get("url", "")),
            }
        )
    return tuple(records)


def report_view(
    result: Reportable,
    *,
    title: str | None = None,
) -> ReportView:
    """Convert a supported result to one stable reporting representation."""

    if isinstance(result, ProcessAssessment):
        assessment = result.assessment
        environment = result.environmental
        economics = result.economics
        normalized = result.normalized
        exergy_unit = "MWh_ex per 1 MWh input" if normalized else "MWh_ex"
        climate_unit = "kg CO2e per 1 MWh input" if normalized else "kg CO2e"
        pollutant_unit = "kg per 1 MWh input" if normalized else "kg"
        metrics: list[tuple[str, float | str, str]] = [
            ("Fidelity", assessment.tier.value, ""),
            (
                "Exergetic efficiency",
                _estimate_value(assessment.exergetic_efficiency) or 0.0,
                "fraction",
            ),
            (
                "Exergy destroyed or lost",
                _estimate_value(assessment.exergy_destroyed_or_lost) or 0.0,
                exergy_unit,
            ),
            ("Climate impact - 100 year", environment.co2e100_kg, climate_unit),
            ("Climate impact - 20 year", environment.co2e20_kg, climate_unit),
            (
                "Screening energy opportunity",
                result.opportunity.energy_savings.value,
                result.opportunity.energy_savings.unit,
            ),
        ]
        if economics:
            metrics.extend(
                (
                    ("Net present value", economics.npv, economics.currency),
                    (
                        "Simple payback",
                        economics.simple_payback_years
                        if economics.simple_payback_years is not None
                        else "not reached",
                        "years",
                    ),
                )
            )
        parameter_rows = tuple(
            {"parameter": name, **parameter.to_dict()}
            for name, parameter in assessment.parameters.items()
        )
        basis = "per 1 MWh input" if normalized else "reporting-period total"
        climate_rows = tuple(
            {"basis": basis, **item.to_dict()}
            for item in environment.climate_contributions
        )
        pollutant_rows = tuple(
            {
                "pollutant": item.pollutant,
                "basis": basis,
                "mass_kg": item.mass.value,
                "low_kg": item.mass.low,
                "high_kg": item.mass.high,
                "health_category": item.profile.category if item.profile else "",
                "health_screen": (
                    " ".join(item.profile.health_effects) if item.profile else ""
                ),
            }
            for item in environment.pollutants
        )
        opportunity_rows = (
            {
                "metric": "Energy savings",
                **result.opportunity.energy_savings.to_dict(),
            },
            {
                "metric": "CO2e reduction - 100 year",
                **result.opportunity.co2e100_reduction.to_dict(),
            },
        )
        economic_rows = (
            tuple(
                {"year": year, "cash_flow": value, "currency": economics.currency}
                for year, value in enumerate(economics.cash_flows)
            )
            if economics
            else ()
        )
        normalized_suffix = " (per 1 MWh input)" if normalized else ""
        tables = {
            "Assumptions and inputs": parameter_rows,
            f"Climate contributions{normalized_suffix}": climate_rows,
            f"Air pollutant and health screening{normalized_suffix}": pollutant_rows,
            f"Improvement opportunity{normalized_suffix}": opportunity_rows,
            "Project cash flows": economic_rows,
        }
        charts: list[ChartSpec] = []
        assessment_chart = _assessment_chart(assessment)
        if assessment_chart:
            charts.append(assessment_chart)
        charts.append(
            ChartSpec(
                "warming-horizons",
                "Climate impact by warming horizon",
                climate_unit,
                (
                    ("20-year", environment.co2e20_kg),
                    ("100-year", environment.co2e100_kg),
                ),
                "#16A34A",
            )
        )
        if environment.pollutants:
            charts.append(
                ChartSpec(
                    "pollutants",
                    "Air pollutant inventory",
                    pollutant_unit,
                    tuple(
                        (item.pollutant, item.mass.value)
                        for item in environment.pollutants
                    ),
                    "#DC2626",
                )
            )
        if economics:
            cash_flows = economics.cash_flows
            financial_chart_values: list[tuple[str, float]] = [
                ("Initial investment", cash_flows[0])
            ]
            if len(cash_flows) > 1:
                financial_chart_values.append(("Year 1", cash_flows[1]))
            if len(cash_flows) > 2:
                financial_chart_values.append(
                    (f"Year {len(cash_flows) - 1}", cash_flows[-1])
                )
            charts.append(
                ChartSpec(
                    "cash-flow",
                    "Representative project cash flows",
                    economics.currency,
                    tuple(financial_chart_values),
                    "#7C3AED",
                )
            )
        assessment_source_ids = tuple(
            parameter.source_id
            for parameter in assessment.parameters.values()
            if parameter.source_id
        )
        source_ids = (
            *environment.sources,
            *assessment_source_ids,
            result.template.source_id,
        )
        return ReportView(
            title=title or f"{result.template.label} assessment",
            subtitle=(
                result.template.description
                + (
                    " | normalized per 1 MWh input"
                    if normalized
                    else " | absolute reporting-period quantities"
                )
            ),
            key_metrics=tuple(metrics),
            tables={name: rows for name, rows in tables.items() if rows},
            charts=tuple(charts),
            warnings=result.warnings
            + (
                (
                    "Values are normalized per 1 MWh of input; they are not "
                    "absolute reporting-period totals."
                ),
            )
            if normalized
            else result.warnings,
            sources=_source_records(
                source_ids,
                environment.source_catalog,
                assessment.source_catalog,
            ),
            payload=result.to_dict(),
        )

    if isinstance(result, AssessmentResult):

        def assessment_unit(value: Any) -> str:
            if value is None:
                return ""
            return f"{value.unit} per 1 MWh input" if result.normalized else value.unit

        metrics = tuple(
            (label, value, unit)
            for label, value, unit in (
                (
                    "Exergetic efficiency",
                    _estimate_value(result.exergetic_efficiency),
                    "fraction",
                ),
                (
                    "Input exergy",
                    _estimate_value(result.input_exergy),
                    assessment_unit(result.input_exergy),
                ),
                (
                    "Useful exergy",
                    _estimate_value(result.useful_exergy),
                    assessment_unit(result.useful_exergy),
                ),
                (
                    "Destroyed or lost",
                    _estimate_value(result.exergy_destroyed_or_lost),
                    (assessment_unit(result.exergy_destroyed_or_lost)),
                ),
            )
            if value is not None
        )
        chart = _assessment_chart(result)
        return ReportView(
            title=title or result.subject,
            subtitle=(
                f"{result.tier.value} progressive-fidelity exergy assessment"
                + (
                    " | normalized per 1 MWh input"
                    if result.normalized
                    else " | absolute reporting-period quantities"
                )
            ),
            key_metrics=metrics,
            tables={
                "Assumptions and inputs": tuple(
                    {"parameter": name, **parameter.to_dict()}
                    for name, parameter in result.parameters.items()
                ),
                "Refinement opportunities": tuple(
                    item.to_dict() for item in result.refinements
                ),
            },
            charts=(chart,) if chart else (),
            warnings=tuple(result.warnings)
            + (
                (
                    (
                        "Values are normalized per 1 MWh of input; they are not "
                        "absolute reporting-period totals."
                    ),
                )
                if result.normalized
                else ()
            ),
            sources=_source_records(
                (
                    parameter.source_id
                    for parameter in result.parameters.values()
                    if parameter.source_id
                ),
                result.source_catalog,
            ),
            payload=result.to_dict(),
        )

    if isinstance(result, EnvironmentalResult):
        impact_unit = "kg CO2e per MWh input" if result.normalized else "kg CO2e"
        pollutant_unit = "kg per MWh input" if result.normalized else "kg"
        charts = [
            ChartSpec(
                "warming-horizons",
                "Climate impact by warming horizon",
                impact_unit,
                (("20-year", result.co2e20_kg), ("100-year", result.co2e100_kg)),
                "#16A34A",
            )
        ]
        if result.pollutants:
            charts.append(
                ChartSpec(
                    "pollutants",
                    "Air pollutant inventory",
                    pollutant_unit,
                    tuple(
                        (item.pollutant, item.mass.value) for item in result.pollutants
                    ),
                    "#DC2626",
                )
            )
        return ReportView(
            title=title or "Environmental impact screening",
            subtitle=(
                "Climate and air-pollutant inventory linked to energy use"
                + (
                    " | normalized per 1 MWh input"
                    if result.normalized
                    else " | absolute reporting-period quantities"
                )
            ),
            key_metrics=(
                (
                    "Energy basis" if result.normalized else "Energy",
                    result.energy_mwh,
                    "MWh per 1 MWh input" if result.normalized else "MWh",
                ),
                ("Climate impact - 20 year", result.co2e20_kg, impact_unit),
                ("Climate impact - 100 year", result.co2e100_kg, impact_unit),
            ),
            tables={
                "Climate contributions": tuple(
                    item.to_dict() for item in result.climate_contributions
                ),
                "Air pollutant and health screening": tuple(
                    item.to_dict() for item in result.pollutants
                ),
            },
            charts=tuple(charts),
            warnings=result.warnings
            + (
                (
                    (
                        "Values are normalized per 1 MWh of input; they are not "
                        "absolute reporting-period inventories."
                    ),
                )
                if result.normalized
                else ()
            ),
            sources=_source_records(result.sources, result.source_catalog),
            payload=result.to_dict(),
        )

    if isinstance(result, GHGBoundaryResult):
        boundary_rows = tuple(
            {
                "boundary": item.boundary,
                "accounting_group": item.accounting_group,
                "included_in_total": item.included_in_total,
                "co2e20_kg": item.aggregate_co2e20_kg,
                "co2e100_kg": item.aggregate_co2e100_kg,
                "note": item.note or "",
            }
            for item in result.boundaries
        )
        included = tuple(
            (item.boundary, item.aggregate_co2e100_kg)
            for item in result.boundaries
            if item.included_in_total
        )
        charts = [
            ChartSpec(
                "warming-horizons",
                "GHG inventory by warming horizon",
                "kg CO2e",
                (
                    ("20-year", result.total_co2e20_kg),
                    ("100-year", result.total_co2e100_kg),
                ),
                "#16A34A",
            )
        ]
        if included:
            charts.append(
                ChartSpec(
                    "ghg-boundaries",
                    "100-year climate impact by included boundary",
                    "kg CO2e",
                    included,
                    "#0F766E",
                )
            )
        return ReportView(
            title=title or "Greenhouse-gas boundary assessment",
            subtitle="Direct, indirect, and contextual allocation views",
            key_metrics=(
                ("Total climate impact - 20 year", result.total_co2e20_kg, "kg CO2e"),
                ("Total climate impact - 100 year", result.total_co2e100_kg, "kg CO2e"),
                ("Direct impact - 100 year", result.direct_co2e100_kg, "kg CO2e"),
                ("Indirect impact - 100 year", result.indirect_co2e100_kg, "kg CO2e"),
            ),
            tables={"GHG boundaries": boundary_rows},
            charts=tuple(charts),
            warnings=result.warnings,
            sources=_source_records(result.sources, result.source_catalog),
            payload=result.to_dict(),
        )

    if isinstance(result, MethaneProjectResult):
        disposition_rows = tuple(
            {
                "case": label,
                "mode": item.mode,
                "methane_released_kg": item.methane_released_kg,
                "methane_recovered_kg": item.methane_recovered_kg,
                "methane_oxidized_kg": item.methane_oxidized_kg,
                "combustion_co2_kg": item.combustion_co2_kg,
                "recovered_energy_mwh": item.recovered_energy_mwh,
                "co2e20_kg": item.ghg.total_co2e20_kg,
                "co2e100_kg": item.ghg.total_co2e100_kg,
            }
            for label, item in (
                ("baseline", result.baseline),
                ("project", result.project),
            )
        )
        economic_rows = (
            tuple(
                {
                    "year": year,
                    "cash_flow": value,
                    "currency": result.economics.currency,
                }
                for year, value in enumerate(result.economics.cash_flows)
            )
            if result.economics
            else ()
        )
        metrics: list[tuple[str, float | str, str]] = [
            ("Avoided climate impact - 20 year", result.avoided_co2e20_kg, "kg CO2e"),
            ("Avoided climate impact - 100 year", result.avoided_co2e100_kg, "kg CO2e"),
            ("Recovered energy", result.project.recovered_energy_mwh, "MWh"),
            ("Recovered-gas revenue", result.recovered_gas_revenue, result.currency),
        ]
        if result.economics:
            metrics.append(("Net present value", result.economics.npv, result.currency))
        source_ids = (*result.baseline.ghg.sources, *result.project.ghg.sources)
        return ReportView(
            title=title or "Methane management project",
            subtitle=f"{result.baseline.mode.title()} baseline versus {result.project.mode.title()} project",
            key_metrics=tuple(metrics),
            tables={
                "Disposition comparison": disposition_rows,
                **({"Project cash flows": economic_rows} if economic_rows else {}),
            },
            charts=(
                ChartSpec(
                    "methane-baseline-project",
                    "Baseline and project climate impact",
                    "kg CO2e (100-year)",
                    (
                        ("Baseline", result.baseline.ghg.total_co2e100_kg),
                        ("Project", result.project.ghg.total_co2e100_kg),
                    ),
                    "#0F766E",
                ),
                ChartSpec(
                    "methane-horizons",
                    "Avoided climate impact by warming horizon",
                    "kg CO2e",
                    (
                        ("20-year", result.avoided_co2e20_kg),
                        ("100-year", result.avoided_co2e100_kg),
                    ),
                    "#16A34A",
                ),
            ),
            warnings=tuple(
                dict.fromkeys(
                    (
                        *result.warnings,
                        *(result.economics.warnings if result.economics else ()),
                    )
                )
            ),
            sources=_source_records(
                source_ids,
                result.baseline.ghg.source_catalog,
                result.project.ghg.source_catalog,
            ),
            payload=result.to_dict(),
        )

    if isinstance(result, EconomicResult):
        annual_rows = tuple(
            {
                "year": year,
                "cash_flow": cash_flow,
                "energy_price_per_mwh": (
                    result.annual_energy_prices_per_mwh[year - 1] if year > 0 else None
                ),
                "carbon_price_per_tonne": (
                    result.annual_carbon_prices_per_tonne[year - 1]
                    if year > 0
                    else None
                ),
                "currency": result.currency,
            }
            for year, cash_flow in enumerate(result.cash_flows)
        )
        return ReportView(
            title=title or "Project economics",
            subtitle="Discounted cash flow, payback, levelized-cost, and abatement screen",
            key_metrics=(
                ("Net present value", result.npv, result.currency),
                (
                    "Internal rate of return",
                    result.irr if result.irr is not None else "not available",
                    "fraction",
                ),
                (
                    "Simple payback",
                    result.simple_payback_years
                    if result.simple_payback_years is not None
                    else "not reached",
                    "years",
                ),
                (
                    "Benefit-cost ratio",
                    result.benefit_cost_ratio
                    if result.benefit_cost_ratio is not None
                    else "not available",
                    "ratio",
                ),
                (
                    "Annualized capital cost",
                    result.annualized_capital_cost,
                    result.currency,
                ),
            ),
            tables={
                "Annual cash flow": annual_rows,
                "Annual benefits": (dict(result.annual_benefits),),
                "Assumptions": (dict(result.assumptions),),
            },
            charts=(
                ChartSpec(
                    "project-cash-flow",
                    "Project cash flow by year",
                    result.currency,
                    tuple(
                        (f"Year {year}", cash_flow)
                        for year, cash_flow in enumerate(result.cash_flows)
                    ),
                    "#7C3AED",
                ),
            ),
            warnings=result.warnings,
            sources=(),
            payload=result.to_dict(),
        )

    if isinstance(result, TechnologyEconomicResult):
        scenario = result.scenario
        annual_rows = tuple(
            {
                "year": year,
                "output_mwh": output,
                "fuel_price_per_mwh": fuel_price,
                "carbon_price_per_tonne": carbon_price,
                "cost": cost,
                "revenue": revenue,
                "cash_flow": result.cash_flows[year],
                "currency": scenario.currency,
            }
            for year, (output, fuel_price, carbon_price, cost, revenue) in enumerate(
                zip(
                    result.annual_outputs_mwh,
                    result.annual_fuel_prices_per_mwh,
                    result.annual_carbon_prices_per_tonne,
                    result.annual_costs,
                    result.annual_revenues,
                ),
                1,
            )
        )
        representative = [("Year 1", result.annual_costs[0])]
        if len(result.annual_costs) > 1:
            representative.append(
                (f"Year {len(result.annual_costs)}", result.annual_costs[-1])
            )
        sources = (
            (
                {
                    "source_id": "user-supplied-technology-costs",
                    "title": scenario.source,
                    "url": "",
                },
            )
            if scenario.source
            else ()
        )
        return ReportView(
            title=title or f"{scenario.name} economics",
            subtitle=f"User-supplied cost scenario for {scenario.output_name}",
            key_metrics=(
                (
                    "Levelized cost",
                    result.levelized_cost_per_mwh
                    if result.levelized_cost_per_mwh is not None
                    else "unavailable",
                    f"{scenario.currency}/MWh {scenario.output_name}",
                ),
                ("Net present value", result.npv, scenario.currency),
                (
                    "Annualized capital cost",
                    result.annualized_capital_cost,
                    scenario.currency,
                ),
                (
                    "Simple payback",
                    result.simple_payback_years
                    if result.simple_payback_years is not None
                    else "not reached",
                    "years",
                ),
            ),
            tables={
                "Scenario assumptions": (scenario.to_dict(),),
                "Annual economics": annual_rows,
            },
            charts=(
                ChartSpec(
                    "technology-costs",
                    "Representative annual technology costs",
                    scenario.currency,
                    tuple(representative),
                    "#7C3AED",
                ),
            ),
            warnings=result.warnings,
            sources=sources,
            payload=result.to_dict(),
        )

    if isinstance(result, WeatherNormalizationResult):
        return ReportView(
            title=title or f"Weather-normalized {result.metric}",
            subtitle="Degree-day regression against declared normal weather",
            key_metrics=(
                ("Actual total", result.actual_total, result.unit),
                ("Weather-normalized total", result.normalized_total, result.unit),
                ("Weather adjustment", result.weather_adjustment, result.unit),
                (
                    "Model R-squared",
                    result.r_squared if result.r_squared is not None else "unavailable",
                    "fraction",
                ),
            ),
            tables={
                "Weather-normalization model": (
                    {
                        "metric": result.metric,
                        "observations": result.observations,
                        "intercept_per_observation": result.intercept_per_observation,
                        "heating_sensitivity_per_degree_day": result.heating_sensitivity_per_degree_day,
                        "cooling_sensitivity_per_degree_day": result.cooling_sensitivity_per_degree_day,
                        "actual_heating_degree_days": result.actual_heating_degree_days,
                        "normal_heating_degree_days": result.normal_heating_degree_days,
                        "actual_cooling_degree_days": result.actual_cooling_degree_days,
                        "normal_cooling_degree_days": result.normal_cooling_degree_days,
                    },
                )
            },
            charts=(
                ChartSpec(
                    "weather-normalized-total",
                    "Actual and weather-normalized performance",
                    result.unit,
                    (
                        ("Actual", result.actual_total),
                        ("Normalized", result.normalized_total),
                    ),
                    "#2563EB",
                ),
                ChartSpec(
                    "degree-days",
                    "Actual and normal degree days",
                    "degree-days",
                    (
                        ("Actual heating", result.actual_heating_degree_days),
                        ("Normal heating", result.normal_heating_degree_days),
                        ("Actual cooling", result.actual_cooling_degree_days),
                        ("Normal cooling", result.normal_cooling_degree_days),
                    ),
                    "#EA580C",
                ),
            ),
            warnings=result.warnings,
            sources=(),
            payload=result.to_dict(),
        )

    if isinstance(result, EngineeringModelResult):
        source_rows = tuple(
            {"source_id": f"engineering-source-{index}", "title": url, "url": url}
            for index, url in enumerate(result.sources, start=1)
        )
        return ReportView(
            title=title or result.name,
            subtitle=f"Transparent engineering screen: {result.model_id}",
            key_metrics=(
                ("Input energy", result.input_energy_mwh, "MWh"),
                ("Useful energy", result.useful_energy_mwh, "MWh"),
                ("Energy efficiency", result.energy_efficiency, "fraction"),
                ("Useful exergy", result.useful_exergy_mwh, "MWh_ex"),
                ("Exergetic efficiency", result.exergetic_efficiency, "fraction"),
                ("Recoverable energy", result.recoverable_energy_mwh, "MWh"),
            ),
            tables={
                "Model metrics": tuple(
                    {"metric": name, "value": value}
                    for name, value in result.metrics.items()
                ),
                "Assumptions": tuple(
                    {"parameter": name, "value": value}
                    for name, value in result.assumptions.items()
                ),
            },
            charts=(
                ChartSpec(
                    "engineering-energy",
                    "Engineering energy screen",
                    "MWh",
                    (
                        ("Input", result.input_energy_mwh),
                        ("Useful", result.useful_energy_mwh),
                        ("Recoverable", result.recoverable_energy_mwh),
                    ),
                    "#2563EB",
                ),
                ChartSpec(
                    "engineering-exergy",
                    "Engineering exergy screen",
                    "MWh_ex",
                    (
                        ("Input", result.input_exergy_mwh),
                        ("Useful", result.useful_exergy_mwh),
                        ("Destroyed or lost", result.exergy_destroyed_or_lost_mwh),
                    ),
                    "#0F766E",
                ),
            ),
            warnings=result.warnings,
            sources=source_rows,
            payload=result.to_dict(),
        )

    if isinstance(result, WasteHeatMatchResult):
        source_rows = tuple(
            {"source_id": f"engineering-source-{index}", "title": url, "url": url}
            for index, url in enumerate(result.sources, start=1)
        )
        return ReportView(
            title=title or "Waste-heat matching screen",
            subtitle="Temperature-feasible matching with explicit exergy-quality loss",
            key_metrics=(
                ("Heat recovered", result.total_heat_recovered_mwh, "MWh"),
                ("Source exergy", result.total_source_exergy_mwh, "MWh_ex"),
                ("Useful exergy", result.total_useful_exergy_mwh, "MWh_ex"),
                ("Quality loss", result.total_quality_loss_mwh, "MWh_ex"),
            ),
            tables={
                "Heat matches": tuple(item.to_dict() for item in result.matches),
                "Unmatched sources": tuple(
                    {"source": name, "heat_mwh": value}
                    for name, value in result.unmatched_source_heat_mwh.items()
                ),
                "Unmet demands": tuple(
                    {"demand": name, "heat_mwh": value}
                    for name, value in result.unmet_demand_heat_mwh.items()
                ),
            },
            charts=(
                ChartSpec(
                    "waste-heat-recovery",
                    "Recovered heat and exergy",
                    "MWh or MWh_ex",
                    (
                        ("Recovered heat", result.total_heat_recovered_mwh),
                        ("Source exergy", result.total_source_exergy_mwh),
                        ("Useful exergy", result.total_useful_exergy_mwh),
                        ("Quality loss", result.total_quality_loss_mwh),
                    ),
                    "#EA580C",
                ),
            ),
            warnings=result.warnings,
            sources=source_rows,
            payload=result.to_dict(),
        )
    raise TypeError("unsupported result type for report export")


def svg_bar_chart(spec: ChartSpec, *, width: int = 760, height: int = 320) -> str:
    """Return an accessible horizontal SVG bar chart with no dependencies."""

    values = spec.values
    if not values:
        return ""
    label_width = 190
    right_margin = 95
    top = 56
    bottom = 42
    height = max(height, top + bottom + 28 * len(values))
    plot_width = width - label_width - right_margin
    row_height = (height - top - bottom) / len(values)
    maximum = max(abs(value) for _, value in values) or 1.0
    zero_x = label_width
    has_negative = any(value < 0.0 for _, value in values)
    has_positive = any(value > 0.0 for _, value in values)
    if has_negative and has_positive:
        zero_x = label_width + plot_width / 2.0
        scale = plot_width / (2.0 * maximum)
    elif has_negative:
        zero_x = label_width + plot_width
        scale = plot_width / maximum
    else:
        scale = plot_width / maximum
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="{html.escape(spec.id)}-title" viewBox="0 0 {width} {height}">',
        f'<title id="{html.escape(spec.id)}-title">{html.escape(spec.title)}</title>',
        '<rect width="100%" height="100%" fill="#ffffff" rx="8"/>',
        f'<text x="20" y="28" font-family="Arial,sans-serif" font-size="16" font-weight="700" fill="#111827">{html.escape(spec.title)}</text>',
        f'<text x="20" y="47" font-family="Arial,sans-serif" font-size="11" fill="#6B7280">{html.escape(spec.unit)}</text>',
        f'<line x1="{zero_x:.1f}" y1="{top - 5}" x2="{zero_x:.1f}" y2="{height - bottom + 5}" stroke="#9CA3AF" stroke-width="1"/>',
    ]
    for index, (label, value) in enumerate(values):
        center_y = top + index * row_height + row_height / 2.0
        length = abs(value) * scale
        x = zero_x if value >= 0.0 else zero_x - length
        if value >= 0.0:
            value_x = x + length + 6
            value_anchor = "start"
            value_color = "#111827"
        elif length >= 40:
            value_x = x + 6
            value_anchor = "start"
            value_color = "#ffffff"
        else:
            value_x = x - 6
            value_anchor = "end"
            value_color = "#111827"
        lines.extend(
            (
                f'<text x="{label_width - 10}" y="{center_y + 4:.1f}" text-anchor="end" font-family="Arial,sans-serif" font-size="11" fill="#374151">{html.escape(label)}</text>',
                f'<rect x="{x:.1f}" y="{center_y - 8:.1f}" width="{max(length, 0.8):.1f}" height="16" fill="{html.escape(spec.color)}" rx="2"/>',
                f'<text x="{value_x:.1f}" y="{center_y + 4:.1f}" text-anchor="{value_anchor}" font-family="Arial,sans-serif" font-size="10" fill="{value_color}">{value:.4g}</text>',
            )
        )
    lines.append("</svg>")
    return "".join(lines)


def _display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _html_table(title: str, rows: tuple[Mapping[str, Any], ...]) -> str:
    if not rows:
        return ""
    columns = list(dict.fromkeys(key for row in rows for key in row))
    header = "".join(f"<th>{html.escape(str(column))}</th>" for column in columns)
    body = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(_display(row.get(column)))}</td>" for column in columns
        )
        + "</tr>"
        for row in rows
    )
    return (
        f"<section><h2>{html.escape(title)}</h2><div class='table-wrap'><table>"
        f"<thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div></section>"
    )


def export_html(
    result: Reportable,
    path: str | Path,
    *,
    title: str | None = None,
) -> Path:
    view = report_view(result, title=title)
    metrics = "".join(
        "<div class='kpi'><span>"
        + html.escape(label)
        + "</span><strong>"
        + html.escape(_display(value))
        + "</strong><small>"
        + html.escape(unit)
        + "</small></div>"
        for label, value, unit in view.key_metrics
    )
    charts = "".join(
        f"<section class='chart'>{svg_bar_chart(spec)}</section>"
        for spec in view.charts
    )
    tables = "".join(_html_table(name, rows) for name, rows in view.tables.items())
    warnings = "".join(f"<li>{html.escape(item)}</li>" for item in view.warnings)

    def source_html(item: Mapping[str, str]) -> str:
        url = item.get("url", "")
        scheme = urlsplit(url).scheme.casefold()
        rendered_url = ""
        if url:
            escaped_url = html.escape(url)
            rendered_url = (
                f" - <a href='{html.escape(url, quote=True)}' rel='noopener noreferrer'>{escaped_url}</a>"
                if scheme in {"http", "https"}
                else f" - {escaped_url}"
            )
        return (
            "<li><strong>"
            + html.escape(item.get("source_id", ""))
            + ":</strong> "
            + html.escape(item.get("title", ""))
            + rendered_url
            + "</li>"
        )

    sources = "".join(source_html(item) for item in view.sources)
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(view.title)}</title>
<style>
:root{{--ink:#111827;--muted:#6b7280;--line:#d1d5db;--soft:#f3f4f6;--accent:#1d4ed8;}}
*{{box-sizing:border-box}} body{{margin:0;background:#eef2f7;color:var(--ink);font:14px/1.45 Arial,sans-serif}}
main{{max-width:1120px;margin:24px auto;background:white;padding:40px;border-radius:12px;box-shadow:0 10px 30px #11182718}}
h1{{font-size:30px;margin:0 0 5px}} .subtitle{{color:var(--muted);margin:0 0 24px}} h2{{font-size:18px;margin:28px 0 10px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}} .kpi{{background:var(--soft);border-left:4px solid var(--accent);padding:14px}}
.kpi span,.kpi small{{display:block;color:var(--muted)}} .kpi strong{{display:block;font-size:21px;margin:4px 0}}
.chart{{border:1px solid var(--line);border-radius:8px;margin:18px 0;overflow:hidden}} .table-wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:12px}} th{{text-align:left;background:#1f2937;color:white}} th,td{{padding:8px;border-bottom:1px solid var(--line);vertical-align:top}}
.warning{{background:#fff7ed;border-left:4px solid #ea580c;padding:12px 18px}} a{{color:var(--accent)}} footer{{margin-top:30px;color:var(--muted);font-size:11px}}
@media print{{body{{background:white}}main{{box-shadow:none;margin:0;max-width:none}}}}
</style></head><body><main>
<header><h1>{html.escape(view.title)}</h1><p class="subtitle">{html.escape(view.subtitle)}</p></header>
<section class="kpis">{metrics}</section>{charts}{tables}
{f'<section class="warning"><h2>Limitations and warnings</h2><ul>{warnings}</ul></section>' if warnings else ""}
{f"<section><h2>Sources</h2><ul>{sources}</ul></section>" if sources else ""}
<footer>Generated by exergy-imperative. Health information is screening-level and does not estimate individual exposure or clinical risk.</footer>
</main></body></html>"""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")
    return destination


def _pdf_chart(spec: ChartSpec, width: float = 500, height: float = 190) -> Any:
    from reportlab.graphics.shapes import Drawing, Rect, String
    from reportlab.lib import colors

    drawing = Drawing(width, height)
    label_width = 145
    right = 70
    top = 34
    bottom = 18
    plot_width = width - label_width - right
    row_height = (height - top - bottom) / max(len(spec.values), 1)
    maximum = max((abs(value) for _, value in spec.values), default=1.0) or 1.0
    has_negative = any(value < 0 for _, value in spec.values)
    has_positive = any(value > 0 for _, value in spec.values)
    mixed = has_negative and has_positive
    zero_x = label_width + plot_width / 2 if mixed else label_width
    if has_negative and not has_positive:
        zero_x = label_width + plot_width
    scale = plot_width / (2 * maximum if mixed else maximum)
    drawing.add(
        String(0, height - 15, spec.title, fontName="Helvetica-Bold", fontSize=10)
    )
    drawing.add(
        String(
            0, height - 28, spec.unit, fontSize=7, fillColor=colors.HexColor("#6B7280")
        )
    )
    drawing.add(
        Rect(
            zero_x,
            bottom,
            0.5,
            height - top - bottom,
            fillColor=colors.HexColor("#9CA3AF"),
            strokeColor=None,
        )
    )
    for index, (label, value) in enumerate(spec.values):
        center = height - top - index * row_height - row_height / 2
        length = abs(value) * scale
        x = zero_x if value >= 0 else zero_x - length
        if value >= 0:
            value_x = x + length + 4
            value_anchor = "start"
            value_color = colors.black
        elif length >= 30:
            value_x = x + 4
            value_anchor = "start"
            value_color = colors.white
        else:
            value_x = x - 4
            value_anchor = "end"
            value_color = colors.black
        drawing.add(
            String(
                label_width - 5,
                center - 2,
                label[:28],
                textAnchor="end",
                fontSize=7,
                fillColor=colors.HexColor("#374151"),
            )
        )
        drawing.add(
            Rect(
                x,
                center - 5,
                max(length, 0.5),
                10,
                fillColor=colors.HexColor(spec.color),
                strokeColor=None,
            )
        )
        drawing.add(
            String(
                value_x,
                center - 2,
                f"{value:.4g}",
                textAnchor=value_anchor,
                fontSize=7,
                fillColor=value_color,
            )
        )
    return drawing


def export_pdf(
    result: Reportable,
    path: str | Path,
    *,
    title: str | None = None,
) -> Path:
    """Export a compact PDF report using the optional ``reports`` extra."""

    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            KeepTogether,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ImportError(
            "PDF export requires: pip install exergy-imperative[reports]"
        ) from exc

    view = report_view(result, title=title)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(destination),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=view.title,
        author="Exergy Lab",
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            "Small",
            parent=styles["BodyText"],
            fontSize=7.5,
            leading=10,
            alignment=TA_LEFT,
        )
    )
    styles.add(
        ParagraphStyle(
            "SmallHeader",
            parent=styles["Small"],
            textColor=colors.white,
            fontName="Helvetica-Bold",
        )
    )
    styles["Title"].textColor = colors.HexColor("#123B5D")
    styles["Heading2"].textColor = colors.HexColor("#123B5D")
    styles["Heading2"].keepWithNext = True
    story: list[Any] = [
        Paragraph(html.escape(view.title), styles["Title"]),
        Paragraph(html.escape(view.subtitle), styles["BodyText"]),
        Spacer(1, 5 * mm),
    ]
    metric_data = [["Metric", "Value", "Unit"]] + [
        [label, _display(value), unit] for label, value, unit in view.key_metrics
    ]
    metric_table = Table(
        metric_data, colWidths=[86 * mm, 46 * mm, 35 * mm], repeatRows=1
    )
    metric_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#123B5D")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#F3F4F6")],
                ),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(metric_table)
    story.append(Spacer(1, 6 * mm))
    for chart in view.charts:
        story.extend((KeepTogether([_pdf_chart(chart)]), Spacer(1, 3 * mm)))

    for table_name, rows in view.tables.items():
        if not rows:
            continue
        columns = list(dict.fromkeys(key for row in rows for key in row))
        data = [
            [
                Paragraph(html.escape(column), styles["SmallHeader"])
                for column in columns
            ]
        ]
        data.extend(
            [
                Paragraph(html.escape(_display(row.get(column))), styles["Small"])
                for column in columns
            ]
            for row in rows
        )
        available = 174 * mm
        widths = [available / max(len(columns), 1)] * len(columns)
        table = Table(data, colWidths=widths, repeatRows=1, splitByRow=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#374151")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("GRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#D1D5DB")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#F9FAFB")],
                    ),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.extend(
            (
                KeepTogether(
                    [
                        Paragraph(html.escape(table_name), styles["Heading2"]),
                        table,
                    ]
                ),
                Spacer(1, 4 * mm),
            )
        )

    if view.warnings:
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph("Limitations and warnings", styles["Heading2"]))
        story.extend(
            Paragraph(f"- {html.escape(item)}", styles["BodyText"])
            for item in view.warnings
        )
    if view.sources:
        story.append(Paragraph("Sources", styles["Heading2"]))
        story.extend(
            Paragraph(
                html.escape(
                    f"{item.get('source_id', '')}: {item.get('title', '')} {item.get('url', '')}"
                ),
                styles["Small"],
            )
            for item in view.sources
        )

    def footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#6B7280"))
        canvas.drawString(
            18 * mm,
            10 * mm,
            "Generated by exergy-imperative - screening results require professional review",
        )
        canvas.drawRightString(192 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return destination


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialized = [dict(row) for row in rows]
    columns = list(dict.fromkeys(key for row in materialized for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(_spreadsheet_safe_value(column) for column in columns)
        for row in materialized:
            writer.writerow(
                _spreadsheet_safe_value(row.get(column)) for column in columns
            )


def export_excel_compatible_report(
    result: Reportable,
    directory: str | Path,
    *,
    title: str | None = None,
) -> tuple[Path, ...]:
    """Write traceable CSV tables and JSON metadata for Excel or Sheets."""

    view = report_view(result, title=title)
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    summary = root / "summary.csv"
    _write_csv(
        summary,
        (
            {"metric": label, "value": value, "unit": unit}
            for label, value, unit in view.key_metrics
        ),
    )
    outputs.append(summary)
    for index, (name, rows) in enumerate(view.tables.items(), start=1):
        safe_name = "-".join(
            part
            for part in "".join(c if c.isalnum() else " " for c in name.lower()).split()
        )
        path = root / f"{index:02d}-{safe_name}.csv"
        _write_csv(path, rows)
        outputs.append(path)
    sources = root / "sources.csv"
    _write_csv(sources, view.sources)
    outputs.append(sources)
    metadata = root / "report-metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "title": view.title,
                "subtitle": view.subtitle,
                "warnings": list(view.warnings),
                "charts": [item.to_dict() for item in view.charts],
                "source_payload": view.payload,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    outputs.append(metadata)
    return tuple(outputs)
