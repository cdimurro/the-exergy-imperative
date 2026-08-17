"""Explicit greenhouse-gas boundaries and methane-management projects."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

from .economics import EconomicResult, evaluate_economics, normalize_currency
from .factors import DEFAULT_IMPACT_FACTORS, FactorNotFoundError, ImpactFactorLibrary

METHANE_TO_CO2_MASS_RATIO = 44.0095 / 16.0425
DEFAULT_METHANE_DENSITY_KG_PER_M3 = 0.7168
DEFAULT_METHANE_LHV_MWH_PER_KG = 0.0139
EPA_FLARE_DESTRUCTION_EFFICIENCY = 0.98
EPA_FLARE_SOURCE = "https://www3.epa.gov/ttnchie1/ap42/ch13/final/dc13s05_6-5-17.pdf"


def _nonnegative(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return number


def _fraction(value: float, name: str) -> float:
    number = _nonnegative(value, name)
    if number > 1.0:
        raise ValueError(f"{name} must be between zero and one")
    return number


@dataclass(frozen=True)
class GHGGasContribution:
    gas: str
    mass_kg: float
    gwp20: float | None
    gwp100: float | None
    co2e20_kg: float | None
    co2e100_kg: float | None
    source_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "gas": self.gas,
                "mass_kg": self.mass_kg,
                "gwp20": self.gwp20,
                "gwp100": self.gwp100,
                "co2e20_kg": self.co2e20_kg,
                "co2e100_kg": self.co2e100_kg,
                "source_id": self.source_id,
            }.items()
            if value is not None
        }


@dataclass(frozen=True)
class GHGBoundaryContribution:
    boundary: str
    accounting_group: str
    included_in_total: bool
    gases_kg: Mapping[str, float]
    aggregate_co2e20_kg: float
    aggregate_co2e100_kg: float
    gas_contributions: tuple[GHGGasContribution, ...]
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "boundary": self.boundary,
            "accounting_group": self.accounting_group,
            "included_in_total": self.included_in_total,
            "gases_kg": dict(self.gases_kg),
            "co2e20_kg": self.aggregate_co2e20_kg,
            "co2e100_kg": self.aggregate_co2e100_kg,
            "gas_contributions": [item.to_dict() for item in self.gas_contributions],
        }
        if self.note:
            result["note"] = self.note
        return result


@dataclass(frozen=True)
class GHGBoundaryResult:
    boundaries: tuple[GHGBoundaryContribution, ...]
    direct_co2e20_kg: float
    direct_co2e100_kg: float
    indirect_co2e20_kg: float
    indirect_co2e100_kg: float
    total_co2e20_kg: float
    total_co2e100_kg: float
    sources: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    source_catalog: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    @property
    def warming_horizon_gap_kg_co2e(self) -> float:
        return self.total_co2e20_kg - self.total_co2e100_kg

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "boundaries": [item.to_dict() for item in self.boundaries],
            "totals": {
                "direct_co2e20_kg": self.direct_co2e20_kg,
                "direct_co2e100_kg": self.direct_co2e100_kg,
                "indirect_co2e20_kg": self.indirect_co2e20_kg,
                "indirect_co2e100_kg": self.indirect_co2e100_kg,
                "co2e20_kg": self.total_co2e20_kg,
                "co2e100_kg": self.total_co2e100_kg,
                "warming_horizon_gap_kg_co2e": self.warming_horizon_gap_kg_co2e,
            },
            "sources": list(self.sources),
            "source_catalog": {
                name: dict(value) for name, value in self.source_catalog.items()
            },
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


def _boundary(
    name: str,
    group: str,
    gases: Mapping[str, float] | None,
    aggregate20: float = 0.0,
    aggregate100: float = 0.0,
    *,
    included: bool = True,
    note: str | None = None,
    library: ImpactFactorLibrary,
    warnings: list[str],
    sources: set[str],
) -> GHGBoundaryContribution:
    canonical: dict[str, float] = {}
    contributions: list[GHGGasContribution] = []
    total20 = _nonnegative(aggregate20, f"{name} aggregate CO2e20")
    total100 = _nonnegative(aggregate100, f"{name} aggregate CO2e100")
    for gas, raw_mass in (gases or {}).items():
        mass = _nonnegative(raw_mass, f"{name} gas {gas}")
        try:
            gwp = library.warming_potential(str(gas))
        except FactorNotFoundError:
            canonical[str(gas)] = canonical.get(str(gas), 0.0) + mass
            contributions.append(
                GHGGasContribution(str(gas), mass, None, None, None, None)
            )
            warnings.append(
                f"No warming potential matched {gas!r} in boundary {name!r}; its mass is excluded from CO2e."
            )
            continue
        canonical[gwp.gas] = canonical.get(gwp.gas, 0.0) + mass
        item20 = mass * gwp.gwp20
        item100 = mass * gwp.gwp100
        total20 += item20
        total100 += item100
        sources.add(gwp.source_id)
        contributions.append(
            GHGGasContribution(
                gwp.gas,
                mass,
                gwp.gwp20,
                gwp.gwp100,
                item20,
                item100,
                gwp.source_id,
            )
        )
    return GHGBoundaryContribution(
        boundary=name,
        accounting_group=group,
        included_in_total=included,
        gases_kg=canonical,
        aggregate_co2e20_kg=total20,
        aggregate_co2e100_kg=total100,
        gas_contributions=tuple(contributions),
        note=note,
    )


def assess_ghg_boundaries(
    *,
    combustion_gases_kg: Mapping[str, float] | None = None,
    process_gases_kg: Mapping[str, float] | None = None,
    fugitive_gases_kg: Mapping[str, float] | None = None,
    purchased_energy_co2e_kg: float = 0.0,
    purchased_energy_co2e20_kg: float | None = None,
    allocated_electricity_heat_co2e_kg: float | None = None,
    other_boundaries: Mapping[str, Mapping[str, float]] | None = None,
    factor_library: ImpactFactorLibrary | None = None,
) -> GHGBoundaryResult:
    """Calculate direct and indirect totals while keeping allocation views separate.

    ``allocated_electricity_heat_co2e_kg`` is contextual and excluded from the
    reporting total because adding it to purchased-energy emissions would often
    double count the same generation emissions.
    """

    library = factor_library or DEFAULT_IMPACT_FACTORS
    warnings: list[str] = []
    sources: set[str] = set()
    boundaries: list[GHGBoundaryContribution] = []
    for name, gases in (
        ("combustion", combustion_gases_kg),
        ("process", process_gases_kg),
        ("fugitive", fugitive_gases_kg),
    ):
        if gases:
            boundaries.append(
                _boundary(
                    name,
                    "direct",
                    gases,
                    library=library,
                    warnings=warnings,
                    sources=sources,
                )
            )
    purchased100 = _nonnegative(purchased_energy_co2e_kg, "purchased_energy_co2e_kg")
    purchased20 = (
        purchased100
        if purchased_energy_co2e20_kg is None
        else _nonnegative(purchased_energy_co2e20_kg, "purchased_energy_co2e20_kg")
    )
    if purchased20 or purchased100:
        boundaries.append(
            _boundary(
                "purchased-energy",
                "indirect",
                None,
                purchased20,
                purchased100,
                note="Aggregate CO2e supplied by the user; gas composition was not inferred.",
                library=library,
                warnings=warnings,
                sources=sources,
            )
        )
        if purchased_energy_co2e20_kg is None and purchased100:
            warnings.append(
                "Purchased-energy CO2e was supplied without gas composition or a 20-year value; the 100-year aggregate was carried unchanged into both horizons."
            )
    if allocated_electricity_heat_co2e_kg is not None:
        allocated = _nonnegative(
            allocated_electricity_heat_co2e_kg,
            "allocated_electricity_heat_co2e_kg",
        )
        boundaries.append(
            _boundary(
                "electricity-and-heat-allocated",
                "context",
                None,
                allocated,
                allocated,
                included=False,
                note="Allocation view excluded from totals to prevent double counting.",
                library=library,
                warnings=warnings,
                sources=sources,
            )
        )
        warnings.append(
            "Allocated electricity-and-heat emissions are shown as a separate view and excluded from the combined total to prevent double counting."
        )
    for name, gases in (other_boundaries or {}).items():
        boundaries.append(
            _boundary(
                str(name),
                "other",
                gases,
                library=library,
                warnings=warnings,
                sources=sources,
            )
        )
    direct = [
        item
        for item in boundaries
        if item.included_in_total and item.accounting_group == "direct"
    ]
    indirect = [
        item
        for item in boundaries
        if item.included_in_total and item.accounting_group == "indirect"
    ]
    other = [
        item
        for item in boundaries
        if item.included_in_total and item.accounting_group == "other"
    ]
    direct20 = sum(item.aggregate_co2e20_kg for item in direct)
    direct100 = sum(item.aggregate_co2e100_kg for item in direct)
    indirect20 = sum(item.aggregate_co2e20_kg for item in indirect)
    indirect100 = sum(item.aggregate_co2e100_kg for item in indirect)
    return GHGBoundaryResult(
        boundaries=tuple(boundaries),
        direct_co2e20_kg=direct20,
        direct_co2e100_kg=direct100,
        indirect_co2e20_kg=indirect20,
        indirect_co2e100_kg=indirect100,
        total_co2e20_kg=direct20
        + indirect20
        + sum(item.aggregate_co2e20_kg for item in other),
        total_co2e100_kg=direct100
        + indirect100
        + sum(item.aggregate_co2e100_kg for item in other),
        sources=tuple(sorted(sources)),
        warnings=tuple(dict.fromkeys(warnings)),
        source_catalog={
            source_id: dict(library.sources[source_id])
            for source_id in sorted(sources)
            if source_id in library.sources
        },
    )


@dataclass(frozen=True)
class MethaneDispositionResult:
    mode: str
    methane_origin: str
    effective_efficiency: float
    methane_released_kg: float
    methane_recovered_kg: float
    methane_oxidized_kg: float
    combustion_co2_kg: float
    recovered_energy_mwh: float
    ghg: GHGBoundaryResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "methane_origin": self.methane_origin,
            "effective_efficiency": self.effective_efficiency,
            "methane_released_kg": self.methane_released_kg,
            "methane_recovered_kg": self.methane_recovered_kg,
            "methane_oxidized_kg": self.methane_oxidized_kg,
            "combustion_co2_kg": self.combustion_co2_kg,
            "recovered_energy_mwh": self.recovered_energy_mwh,
            "ghg": self.ghg.to_dict(),
        }


@dataclass(frozen=True)
class MethaneProjectResult:
    annual_methane_available_kg: float
    baseline: MethaneDispositionResult
    project: MethaneDispositionResult
    avoided_co2e20_kg: float
    avoided_co2e100_kg: float
    recovered_gas_revenue: float
    currency: str
    economics: EconomicResult | None
    assumptions: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def warming_horizon_gap_kg_co2e(self) -> float:
        return self.avoided_co2e20_kg - self.avoided_co2e100_kg

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "annual_methane_available_kg": self.annual_methane_available_kg,
            "baseline": self.baseline.to_dict(),
            "project": self.project.to_dict(),
            "avoided": {
                "co2e20_kg": self.avoided_co2e20_kg,
                "co2e100_kg": self.avoided_co2e100_kg,
                "warming_horizon_gap_kg_co2e": self.warming_horizon_gap_kg_co2e,
            },
            "recovered_gas_revenue": {
                "value": self.recovered_gas_revenue,
                "currency": self.currency,
            },
            "economics": self.economics.to_dict() if self.economics else None,
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


_DEFAULT_METHANE_EFFICIENCIES = {
    "vented": 0.0,
    "flared": EPA_FLARE_DESTRUCTION_EFFICIENCY,
    "oxidized": 1.0,
    "recovered": 1.0,
}


def _methane_mode_key(mode: str) -> str:
    key = str(mode).strip().lower().replace("_", "-")
    if key not in _DEFAULT_METHANE_EFFICIENCIES:
        raise ValueError("methane mode must be vented, flared, oxidized, or recovered")
    return key


def _disposition(
    mode: str,
    methane_available_kg: float,
    efficiency: float,
    energy_content_mwh_per_kg: float,
    include_recovered_gas_combustion: bool,
    methane_origin: str,
    factor_library: ImpactFactorLibrary,
) -> MethaneDispositionResult:
    key = _methane_mode_key(mode)
    effective = 0.0 if key == "vented" else _fraction(efficiency, f"{key} efficiency")
    released = (
        methane_available_kg
        if key == "vented"
        else methane_available_kg * (1.0 - effective)
    )
    recovered = methane_available_kg * effective if key == "recovered" else 0.0
    oxidized = (
        methane_available_kg * effective if key in {"flared", "oxidized"} else 0.0
    )
    combustion_mass = oxidized + (
        recovered if key == "recovered" and include_recovered_gas_combustion else 0.0
    )
    combustion_co2 = combustion_mass * METHANE_TO_CO2_MASS_RATIO
    methane_gas = "CH4-fossil" if methane_origin == "fossil" else "CH4-biogenic"
    ghg = assess_ghg_boundaries(
        fugitive_gases_kg={methane_gas: released} if released else None,
        combustion_gases_kg=(
            {"CO2": combustion_co2}
            if combustion_co2 and methane_origin == "fossil"
            else None
        ),
        factor_library=factor_library,
    )
    return MethaneDispositionResult(
        mode=key,
        methane_origin=methane_origin,
        effective_efficiency=effective,
        methane_released_kg=released,
        methane_recovered_kg=recovered,
        methane_oxidized_kg=oxidized,
        combustion_co2_kg=combustion_co2,
        recovered_energy_mwh=recovered * energy_content_mwh_per_kg,
        ghg=ghg,
    )


def assess_methane_project(
    *,
    annual_methane_mass_kg: float | None = None,
    annual_methane_volume_m3: float | None = None,
    methane_density_kg_per_m3: float = DEFAULT_METHANE_DENSITY_KG_PER_M3,
    baseline_mode: str = "vented",
    project_mode: str = "recovered",
    baseline_efficiency: float | None = None,
    project_efficiency: float | None = None,
    methane_energy_mwh_per_kg: float = DEFAULT_METHANE_LHV_MWH_PER_KG,
    methane_origin: str = "fossil",
    include_recovered_gas_combustion: bool = False,
    recovered_gas_price_per_mwh: float = 0.0,
    capital_cost: float | None = None,
    annual_opex_increase: float = 0.0,
    carbon_price_per_tonne: float = 0.0,
    project_life_years: int = 20,
    discount_rate: float = 0.07,
    currency: str = "USD",
    factor_library: ImpactFactorLibrary | None = None,
) -> MethaneProjectResult:
    """Compare venting, flaring, oxidation, or recovery with transparent assumptions."""

    if (annual_methane_mass_kg is None) == (annual_methane_volume_m3 is None):
        raise ValueError(
            "supply exactly one of annual_methane_mass_kg or annual_methane_volume_m3"
        )
    currency = normalize_currency(currency)
    density = _nonnegative(methane_density_kg_per_m3, "methane_density_kg_per_m3")
    if density == 0.0:
        raise ValueError("methane_density_kg_per_m3 must be greater than zero")
    if annual_methane_mass_kg is not None:
        available = _nonnegative(annual_methane_mass_kg, "annual_methane_mass_kg")
        mass_source = "provided mass"
    else:
        available = (
            _nonnegative(annual_methane_volume_m3 or 0.0, "annual_methane_volume_m3")
            * density
        )
        mass_source = "volume multiplied by declared methane density"
    energy_content = _nonnegative(
        methane_energy_mwh_per_kg, "methane_energy_mwh_per_kg"
    )
    origin = str(methane_origin).strip().lower().replace("_", "-")
    if origin not in {"fossil", "biogenic"}:
        raise ValueError("methane_origin must be fossil or biogenic")
    baseline_mode_key = _methane_mode_key(baseline_mode)
    project_mode_key = _methane_mode_key(project_mode)
    baseline_efficiency_defaulted = baseline_efficiency is None
    project_efficiency_defaulted = project_efficiency is None
    baseline_input_efficiency = _fraction(
        _DEFAULT_METHANE_EFFICIENCIES[baseline_mode_key]
        if baseline_efficiency_defaulted
        else baseline_efficiency,
        "baseline_efficiency",
    )
    project_input_efficiency = _fraction(
        _DEFAULT_METHANE_EFFICIENCIES[project_mode_key]
        if project_efficiency_defaulted
        else project_efficiency,
        "project_efficiency",
    )
    library = factor_library or DEFAULT_IMPACT_FACTORS
    baseline = _disposition(
        baseline_mode_key,
        available,
        baseline_input_efficiency,
        energy_content,
        include_recovered_gas_combustion,
        origin,
        library,
    )
    project = _disposition(
        project_mode_key,
        available,
        project_input_efficiency,
        energy_content,
        include_recovered_gas_combustion,
        origin,
        library,
    )
    avoided20 = baseline.ghg.total_co2e20_kg - project.ghg.total_co2e20_kg
    avoided100 = baseline.ghg.total_co2e100_kg - project.ghg.total_co2e100_kg
    gas_price = _nonnegative(recovered_gas_price_per_mwh, "recovered_gas_price_per_mwh")
    incremental_recovered_energy = (
        project.recovered_energy_mwh - baseline.recovered_energy_mwh
    )
    revenue = incremental_recovered_energy * gas_price
    economics: EconomicResult | None = None
    if capital_cost is not None:
        economics = evaluate_economics(
            capital_cost=capital_cost,
            annual_product_revenue=revenue,
            annual_opex_increase=annual_opex_increase,
            annual_co2e_reduction_kg=avoided100,
            carbon_price_per_tonne=carbon_price_per_tonne,
            project_life_years=project_life_years,
            discount_rate=discount_rate,
            currency=currency,
        )
    warnings: list[str] = []
    if annual_methane_volume_m3 is not None:
        warnings.append(
            "Methane mass depends on the declared gas density and standard conditions; replace the default with site-specific data when available."
        )
    warnings.append(
        f"Methane is accounted as {origin}; select biogenic for landfill, wastewater, manure, or other non-fossil carbon sources."
    )
    if (
        baseline.mode == "vented"
        and not baseline_efficiency_defaulted
        and baseline_input_efficiency != 0.0
    ):
        warnings.append(
            "baseline_efficiency is ignored for venting; the effective efficiency is zero."
        )
    if (
        project.mode == "vented"
        and not project_efficiency_defaulted
        and project_input_efficiency != 0.0
    ):
        warnings.append(
            "project_efficiency is ignored for venting; the effective efficiency is zero."
        )
    if baseline.mode == "flared" and baseline_efficiency_defaulted:
        warnings.append(
            "The 98% baseline flare destruction efficiency is an EPA screening assumption for properly operated flares; actual performance can vary."
        )
    if project.mode == "flared" and project_efficiency_defaulted:
        warnings.append(
            "The 98% project flare destruction efficiency is an EPA screening assumption for properly operated flares; actual performance can vary."
        )
    if baseline.mode == "oxidized" and baseline_efficiency_defaulted:
        warnings.append(
            "The default baseline oxidation efficiency is an upper-bound screen; supply a site-specific oxidation factor for decisions."
        )
    if project.mode == "oxidized" and project_efficiency_defaulted:
        warnings.append(
            "The default project oxidation efficiency is an upper-bound screen; supply a site-specific oxidation factor for decisions."
        )
    if baseline.mode == "recovered" and baseline_efficiency_defaulted:
        warnings.append(
            "The default baseline recovery efficiency is an upper-bound screen; supply measured or engineering recovery efficiency for project decisions."
        )
    if project.mode == "recovered" and project_efficiency_defaulted:
        warnings.append(
            "The default recovery efficiency is an upper-bound screen; supply measured or engineering recovery efficiency for project decisions."
        )
    if project.mode == "recovered" and not include_recovered_gas_combustion:
        warnings.append(
            "Downstream combustion of recovered gas is outside the project boundary; enable it when a lifecycle comparison requires it."
        )
    return MethaneProjectResult(
        annual_methane_available_kg=available,
        baseline=baseline,
        project=project,
        avoided_co2e20_kg=avoided20,
        avoided_co2e100_kg=avoided100,
        recovered_gas_revenue=revenue,
        currency=currency,
        economics=economics,
        assumptions={
            "methane_mass_source": mass_source,
            "methane_density_kg_per_m3": density,
            "methane_energy_mwh_per_kg": energy_content,
            "methane_origin": origin,
            "baseline_efficiency": baseline.effective_efficiency,
            "project_efficiency": project.effective_efficiency,
            "baseline_efficiency_input": baseline_input_efficiency,
            "project_efficiency_input": project_input_efficiency,
            "baseline_efficiency_defaulted": baseline_efficiency_defaulted,
            "project_efficiency_defaulted": project_efficiency_defaulted,
            "baseline_efficiency_input_used": baseline.mode != "vented",
            "project_efficiency_input_used": project.mode != "vented",
            "include_recovered_gas_combustion": include_recovered_gas_combustion,
            "flare_screening_source": EPA_FLARE_SOURCE,
        },
        warnings=tuple(warnings),
    )
