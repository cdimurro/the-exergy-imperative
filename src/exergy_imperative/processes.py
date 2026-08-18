"""Ready-to-use industry templates built on the general assessment engine."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from difflib import get_close_matches
from importlib.resources import files
from typing import Any, Mapping

from .assessment import assess
from .economics import EconomicResult, evaluate_economics, normalize_currency
from .factors import ImpactFactorLibrary
from .impacts import EnvironmentalResult, assess_impacts
from .models import AssessmentResult, Estimate
from .registry import DEFAULT_REGISTRY, Registry


class ProcessTemplateNotFoundError(KeyError):
    """Raised when a process template or alias is unknown."""


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


@dataclass(frozen=True)
class ProcessTemplate:
    id: str
    label: str
    aliases: tuple[str, ...]
    sector: str
    technology: str
    description: str
    savings_fraction: Estimate
    major_pollutants: tuple[str, ...]
    priority_inputs: tuple[str, ...]
    source_id: str
    data_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "aliases": list(self.aliases),
            "sector": self.sector,
            "technology": self.technology,
            "description": self.description,
            "screening_savings_fraction": self.savings_fraction.to_dict(),
            "major_pollutants": list(self.major_pollutants),
            "priority_inputs": list(self.priority_inputs),
            "source_id": self.source_id,
            "data_version": self.data_version,
        }


@dataclass(frozen=True)
class ProcessOpportunity:
    improvement_fraction: Estimate
    energy_savings: Estimate
    exergy_destruction_reduction: Estimate | None
    co2e100_reduction: Estimate
    pollutant_reductions_kg: Mapping[str, Estimate]

    def to_dict(self) -> dict[str, Any]:
        return {
            "improvement_fraction": self.improvement_fraction.to_dict(),
            "energy_savings": self.energy_savings.to_dict(),
            "exergy_destruction_reduction": (
                self.exergy_destruction_reduction.to_dict()
                if self.exergy_destruction_reduction
                else None
            ),
            "co2e100_reduction": self.co2e100_reduction.to_dict(),
            "pollutant_reductions_kg": {
                name: value.to_dict()
                for name, value in self.pollutant_reductions_kg.items()
            },
        }


@dataclass(frozen=True)
class ProcessAssessment:
    template: ProcessTemplate
    assessment: AssessmentResult
    environmental: EnvironmentalResult
    opportunity: ProcessOpportunity
    economics: EconomicResult | None = None
    warnings: tuple[str, ...] = ()
    annualization_factor: float | None = None

    @property
    def normalized(self) -> bool:
        """Whether quantities are intensities normalized to one MWh of input."""

        return self.assessment.normalized

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "normalized": self.normalized,
            "template": self.template.to_dict(),
            "assessment": self.assessment.to_dict(),
            "environmental": self.environmental.to_dict(),
            "opportunity": self.opportunity.to_dict(),
            "economics": self.economics.to_dict() if self.economics else None,
            "annualization_factor": self.annualization_factor,
            "warnings": list(self.warnings),
        }

    def summary(self) -> str:
        climate_unit = "kg CO2e per 1 MWh input" if self.normalized else "kg CO2e"
        lines = [
            self.template.label,
            f"Sector: {self.template.sector}",
            f"Fidelity: {self.assessment.tier.value}",
            (
                "Basis: normalized per 1 MWh of input; quantities are "
                "intensities, not reporting-period totals"
                if self.normalized
                else "Basis: absolute reporting-period quantities"
            ),
            f"Exergetic efficiency: {self.assessment.exergetic_efficiency.formatted() if self.assessment.exergetic_efficiency else 'unavailable'}",
            f"Climate impact: {self.environmental.co2e100_kg:.3g} {climate_unit} (100-year)",
            f"Screening energy opportunity: {self.opportunity.energy_savings.formatted()}",
            f"Screening CO2e opportunity: {self.opportunity.co2e100_reduction.formatted()}",
        ]
        if self.economics:
            if self.annualization_factor is not None:
                lines.append(
                    f"Annualization: {self.annualization_factor:.6g} reporting periods per year"
                )
            lines.extend(
                (
                    f"NPV: {self.economics.npv:.3g} {self.economics.currency}",
                    f"Simple payback: {self.economics.simple_payback_years if self.economics.simple_payback_years is not None else 'not reached'} years",
                )
            )
        if self.warnings:
            lines.append("Warnings and limitations:")
            lines.extend(f"  - {warning}" for warning in self.warnings)
        lines.append("Highest-value additional inputs:")
        lines.extend(f"  - {item}" for item in self.template.priority_inputs[:5])
        return "\n".join(lines)

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


def _template_from_dict(
    raw: Mapping[str, Any], *, source_id: str, data_version: str
) -> ProcessTemplate:
    required = {
        "id",
        "label",
        "sector",
        "technology",
        "description",
        "screening_savings_fraction",
        "major_pollutants",
        "priority_inputs",
    }
    missing = sorted(required - set(raw))
    if missing:
        raise ValueError("process template is missing: " + ", ".join(missing))
    factor = raw["screening_savings_fraction"]
    if not isinstance(factor, Mapping):
        raise ValueError("screening_savings_fraction must be an object")
    value = float(factor["value"])
    low = float(factor.get("low", value))
    high = float(factor.get("high", value))
    if not all(math.isfinite(item) for item in (value, low, high)):
        raise ValueError("process-template savings fractions must be finite")
    if not 0.0 <= low <= value <= high <= 1.0:
        raise ValueError(
            "process-template savings fractions must satisfy "
            "0 <= low <= value <= high <= 1"
        )
    return ProcessTemplate(
        id=str(raw["id"]),
        label=str(raw["label"]),
        aliases=tuple(str(item) for item in raw.get("aliases", [])),
        sector=str(raw["sector"]),
        technology=str(raw["technology"]),
        description=str(raw["description"]),
        savings_fraction=Estimate(
            value,
            "fraction of input energy",
            low,
            high,
            "screening prior",
        ),
        major_pollutants=tuple(str(item) for item in raw["major_pollutants"]),
        priority_inputs=tuple(str(item) for item in raw["priority_inputs"]),
        source_id=str(raw.get("source_id", source_id)),
        data_version=str(raw.get("data_version", data_version)),
    )


class ProcessCatalog:
    """Process-template lookup with deterministic in-memory pack overlays."""

    def __init__(self, templates: tuple[ProcessTemplate, ...]):
        self._templates: dict[str, ProcessTemplate] = {}
        self._aliases: dict[str, str] = {}
        for template in templates:
            if not template.id.strip():
                raise ValueError("process-template id must not be empty")
            if template.id in self._templates:
                raise ValueError(f"duplicate process-template id {template.id!r}")
            self._templates[template.id] = template
            for alias in (template.id, template.label, *template.aliases):
                normalized = _key(alias)
                existing = self._aliases.get(normalized)
                if existing and existing != template.id:
                    raise ValueError(f"ambiguous process-template alias {alias!r}")
                self._aliases[normalized] = template.id

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ProcessCatalog":
        source_id = str(payload.get("source_id", "unspecified"))
        data_version = str(payload.get("data_version", "unknown"))
        raw_templates = payload.get("templates", payload.get("process_templates", ()))
        if not isinstance(raw_templates, (list, tuple)):
            raise ValueError("process templates must be an array")
        return cls(
            tuple(
                _template_from_dict(raw, source_id=source_id, data_version=data_version)
                for raw in raw_templates
            )
        )

    def list(self) -> tuple[ProcessTemplate, ...]:
        return tuple(self._templates.values())

    def get(self, value: str) -> ProcessTemplate:
        normalized = _key(value)
        template_id = self._aliases.get(normalized)
        if template_id is not None:
            return self._templates[template_id]
        choices = sorted(self._templates)
        suggestions = get_close_matches(
            str(value).strip().lower().replace(" ", "-"), choices, n=3, cutoff=0.45
        )
        suffix = f"; closest matches: {', '.join(suggestions)}" if suggestions else ""
        raise ProcessTemplateNotFoundError(
            f"unknown process template {value!r}; available templates: "
            + ", ".join(choices)
            + suffix
        )

    def with_payload(self, payload: Mapping[str, Any]) -> "ProcessCatalog":
        custom = ProcessCatalog.from_payload(payload)
        merged = {item.id: item for item in self.list()}
        merged.update({item.id: item for item in custom.list()})
        return ProcessCatalog(tuple(merged.values()))


def _load_templates() -> ProcessCatalog:
    resource = files("exergy_imperative").joinpath("data", "process_templates.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    return ProcessCatalog.from_payload(payload)


DEFAULT_PROCESS_CATALOG = _load_templates()


def list_process_templates(
    catalog: ProcessCatalog | None = None,
) -> tuple[ProcessTemplate, ...]:
    return (catalog or DEFAULT_PROCESS_CATALOG).list()


def get_process_template(
    value: str, *, catalog: ProcessCatalog | None = None
) -> ProcessTemplate:
    return (catalog or DEFAULT_PROCESS_CATALOG).get(value)


def _scale_range(base: float | Estimate, fraction: Estimate, unit: str) -> Estimate:
    base_value = base.value if isinstance(base, Estimate) else float(base)
    base_low = (
        base.low if isinstance(base, Estimate) and base.low is not None else base_value
    )
    base_high = (
        base.high
        if isinstance(base, Estimate) and base.high is not None
        else base_value
    )
    fraction_low = fraction.low if fraction.low is not None else fraction.value
    fraction_high = fraction.high if fraction.high is not None else fraction.value
    return Estimate(
        base_value * fraction.value,
        unit,
        max(base_low, 0.0) * max(fraction_low, 0.0),
        max(base_high, 0.0) * max(fraction_high, 0.0),
        "screening opportunity",
    )


def assess_process(
    template: str,
    energy: float | None = None,
    *,
    unit: str = "MWh",
    country: str | None = None,
    year: int | None = None,
    improvement_fraction: float | None = None,
    assessment_options: Mapping[str, Any] | None = None,
    impact_options: Mapping[str, Any] | None = None,
    economics_options: Mapping[str, Any] | None = None,
    factor_library: ImpactFactorLibrary | None = None,
    annualization_factor: float | None = None,
    registry: Registry | None = None,
    catalog: ProcessCatalog | None = None,
) -> ProcessAssessment:
    """Run a process screen with progressive overrides and integrated impacts."""

    profile = get_process_template(template, catalog=catalog)
    assessment_kwargs = dict(assessment_options or {})
    if "technology" in assessment_kwargs:
        raise ValueError(
            "assessment_options cannot override the process-template technology; "
            "select a different template instead"
        )
    assessment_conflicts: list[str] = []
    if (
        energy is not None
        and "energy" in assessment_kwargs
        and float(assessment_kwargs["energy"]) != float(energy)
    ):
        assessment_conflicts.append("energy")
    if (
        "unit" in assessment_kwargs
        and str(assessment_kwargs["unit"]).casefold() != str(unit).casefold()
    ):
        assessment_conflicts.append("unit")
    if (
        country is not None
        and "location" in assessment_kwargs
        and str(assessment_kwargs["location"]).casefold() != country.casefold()
    ):
        assessment_conflicts.append("country/location")
    if assessment_conflicts:
        raise ValueError(
            "assessment_options conflict with top-level process inputs: "
            + ", ".join(assessment_conflicts)
        )
    assessment_registry = assessment_kwargs.pop("registry", registry)
    assessment_kwargs.setdefault("technology", profile.technology)
    assessment_kwargs.setdefault("energy", energy)
    assessment_kwargs.setdefault("unit", unit)
    if country is not None:
        assessment_kwargs.setdefault("location", country)
    thermodynamic = assess(
        **assessment_kwargs, registry=assessment_registry or DEFAULT_REGISTRY
    )

    impact_kwargs = dict(impact_options or {})
    boundary_overrides = sorted(
        {"assessment", "energy", "unit", "carrier", "country"} & impact_kwargs.keys()
    )
    if boundary_overrides:
        raise ValueError(
            "impact_options cannot override the integrated process boundary: "
            + ", ".join(boundary_overrides)
            + "; use top-level or assessment_options inputs"
        )
    impact_conflicts: list[str] = []
    if year is not None and "year" in impact_kwargs and impact_kwargs["year"] != year:
        impact_conflicts.append("year")
    if (
        factor_library is not None
        and "factor_library" in impact_kwargs
        and impact_kwargs["factor_library"] is not factor_library
    ):
        impact_conflicts.append("factor_library")
    if impact_conflicts:
        raise ValueError(
            "impact_options conflict with top-level process inputs: "
            + ", ".join(impact_conflicts)
        )
    impact_kwargs.setdefault("assessment", thermodynamic)
    impact_kwargs.setdefault("country", country)
    impact_kwargs.setdefault("year", year)
    if factor_library is not None:
        impact_kwargs.setdefault("factor_library", factor_library)
    environmental = assess_impacts(**impact_kwargs)
    fixed_inventory_fields = {
        "gases_kg",
        "refrigerant_leakage_kg",
        "pollutant_masses_kg",
    }
    energy_impact_kwargs = {
        name: value
        for name, value in impact_kwargs.items()
        if name not in fixed_inventory_fields
    }
    energy_environmental = assess_impacts(**energy_impact_kwargs)

    if improvement_fraction is None:
        fraction = profile.savings_fraction
        opportunity_warning = (
            "The improvement opportunity uses a broad template screening prior; "
            "it is not a guaranteed project saving.",
        )
    else:
        value = float(improvement_fraction)
        if not 0.0 <= value <= 1.0:
            raise ValueError("improvement_fraction must be between zero and one")
        fraction = Estimate(value, "fraction of input energy", value, value, "provided")
        opportunity_warning = ()

    normalized = thermodynamic.normalized
    energy_unit = "MWh per 1 MWh input" if normalized else "MWh"
    exergy_unit = "MWh_ex per 1 MWh input" if normalized else "MWh_ex"
    climate_unit = "kg CO2e per 1 MWh input" if normalized else "kg CO2e"
    pollutant_unit = "kg per 1 MWh input" if normalized else "kg"
    energy_savings = _scale_range(environmental.energy_mwh, fraction, energy_unit)
    destroyed = thermodynamic.exergy_destroyed_or_lost
    exergy_reduction = (
        _scale_range(destroyed, fraction, exergy_unit) if destroyed else None
    )
    climate_reduction = _scale_range(
        energy_environmental.co2e100_kg, fraction, climate_unit
    )
    pollutant_reductions = {
        item.pollutant: _scale_range(item.mass, fraction, pollutant_unit)
        for item in energy_environmental.pollutants
    }
    opportunity = ProcessOpportunity(
        improvement_fraction=fraction,
        energy_savings=energy_savings,
        exergy_destruction_reduction=exergy_reduction,
        co2e100_reduction=climate_reduction,
        pollutant_reductions_kg=pollutant_reductions,
    )

    economics: EconomicResult | None = None
    applied_annualization_factor: float | None = None
    if economics_options is not None:
        economic_kwargs = dict(economics_options)
        if "capital_cost" not in economic_kwargs:
            raise ValueError("economics_options requires capital_cost")
        derived_annual_fields = {
            "annual_energy_savings_mwh",
            "annual_co2e_reduction_kg",
            "annual_health_externality_reduction",
        }
        if exergy_reduction is not None:
            derived_annual_fields.add("annual_exergy_savings_mwh")
        needs_annualization = any(
            name not in economic_kwargs for name in derived_annual_fields
        )
        if needs_annualization:
            if thermodynamic.normalized:
                raise ValueError(
                    "cannot annualize a process normalized per 1 MWh; supply an "
                    "energy quantity or every annual economic metric explicitly"
                )
            if annualization_factor is None:
                raise ValueError(
                    "process economics requires annualization_factor (use 1.0 when the input period is one year) or explicit annual energy, exergy, CO2e, and health values"
                )
            annual_factor = float(annualization_factor)
            if not math.isfinite(annual_factor) or annual_factor <= 0.0:
                raise ValueError(
                    "annualization_factor must be finite and greater than zero"
                )
            applied_annualization_factor = annual_factor
        else:
            annual_factor = 1.0
        economic_kwargs.setdefault(
            "annual_energy_savings_mwh", energy_savings.value * annual_factor
        )
        if exergy_reduction is not None:
            economic_kwargs.setdefault(
                "annual_exergy_savings_mwh", exergy_reduction.value * annual_factor
            )
        economic_kwargs.setdefault(
            "annual_co2e_reduction_kg", climate_reduction.value * annual_factor
        )
        health_currency = energy_environmental.health_externality_currency
        economic_currency = normalize_currency(economic_kwargs.get("currency", "USD"))
        if (
            "annual_health_externality_reduction" not in economic_kwargs
            and health_currency is not None
            and economic_currency.casefold() != health_currency.casefold()
        ):
            raise ValueError(
                "pollutant damage-cost currency must match the economics currency, "
                "or annual_health_externality_reduction must be supplied explicitly"
            )
        economic_kwargs.setdefault(
            "annual_health_externality_reduction",
            energy_environmental.health_externality_cost
            * fraction.value
            * annual_factor,
        )
        economics = evaluate_economics(**economic_kwargs)

    warnings = tuple(
        dict.fromkeys(
            (
                *opportunity_warning,
                *(
                    (
                        "Fixed gas, refrigerant, and pollutant masses are held constant in the energy-savings opportunity; model separate controls as a distinct project case.",
                    )
                    if any(impact_kwargs.get(name) for name in fixed_inventory_fields)
                    else ()
                ),
                *thermodynamic.warnings,
                *environmental.warnings,
                *(economics.warnings if economics else ()),
            )
        )
    )
    return ProcessAssessment(
        template=profile,
        assessment=thermodynamic,
        environmental=environmental,
        opportunity=opportunity,
        economics=economics,
        warnings=warnings,
        annualization_factor=applied_annualization_factor,
    )
