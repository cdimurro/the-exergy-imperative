"""Dependency-free project economics for energy and exergy improvements."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Sequence


def _rate(value: float, name: str = "rate") -> float:
    number = float(value)
    if not math.isfinite(number) or number <= -1.0:
        raise ValueError(f"{name} must be finite and greater than -1")
    return number


def _number(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _finite_integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite integer")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite integer") from exc
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError(f"{name} must be a finite integer")
    return int(number)


def normalize_currency(value: str) -> str:
    """Validate and normalize a user-declared currency label."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("currency must be a non-empty string")
    label = value.strip()
    return label.upper() if len(label) == 3 and label.isalpha() else label


def net_present_value(discount_rate: float, cash_flows: Iterable[float]) -> float:
    """Return NPV with the first cash flow occurring at time zero."""

    rate = _rate(discount_rate, "discount_rate")
    return sum(
        _number(value, f"cash flow {period}") / (1.0 + rate) ** period
        for period, value in enumerate(cash_flows)
    )


def capital_recovery_factor(discount_rate: float, periods: int) -> float:
    rate = _rate(discount_rate, "discount_rate")
    period_count = _finite_integer(periods, "periods")
    if period_count <= 0:
        raise ValueError("periods must be a positive integer")
    if rate == 0.0:
        return 1.0 / period_count
    exponent = -period_count * math.log1p(rate)
    try:
        denominator = -math.expm1(exponent)
    except OverflowError:
        return 0.0
    return rate / denominator


def simple_payback_period(cash_flows: Sequence[float]) -> float | None:
    """Return interpolated undiscounted payback in periods, or ``None``."""

    if not cash_flows:
        raise ValueError("cash_flows must not be empty")
    cumulative = _number(cash_flows[0], "cash flow 0")
    if cumulative >= 0.0:
        return 0.0
    for period, value in enumerate(cash_flows[1:], start=1):
        flow = _number(value, f"cash flow {period}")
        previous = cumulative
        cumulative += flow
        if cumulative >= 0.0 and flow > 0.0:
            return (period - 1) + (-previous / flow)
    return None


def discounted_payback_period(
    discount_rate: float, cash_flows: Sequence[float]
) -> float | None:
    if not cash_flows:
        raise ValueError("cash_flows must not be empty")
    rate = _rate(discount_rate, "discount_rate")
    discounted = [
        _number(value, f"cash flow {period}") / (1.0 + rate) ** period
        for period, value in enumerate(cash_flows)
    ]
    return simple_payback_period(discounted)


def internal_rate_of_return(cash_flows: Sequence[float]) -> float | None:
    """Return a unique periodic IRR, avoiding misleading multiple-root cases."""

    values = tuple(
        _number(value, f"cash flow {index}") for index, value in enumerate(cash_flows)
    )
    first_nonzero = next(
        (index for index, value in enumerate(values) if value != 0.0), len(values)
    )
    values = values[first_nonzero:]
    if (
        len(values) < 2
        or not any(value < 0.0 for value in values)
        or not any(value > 0.0 for value in values)
    ):
        return None

    # Normalize before evaluating the polynomial so the root and convergence
    # criterion are invariant to the currency/unit scale of the cash flows.
    scale = max(abs(value) for value in values)
    values = tuple(value / scale for value in values)

    signs = [value > 0.0 for value in values if value != 0.0]
    if sum(left != right for left, right in zip(signs, signs[1:])) != 1:
        return None

    def polynomial(discount_factor: float) -> float:
        result = 0.0
        for value in reversed(values):
            result = result * discount_factor + value
        return result

    low = 0.0
    low_value = polynomial(low)
    high = 1.0
    high_value = polynomial(high)
    while (high_value > 0.0) == (low_value > 0.0):
        high *= 2.0
        high_value = polynomial(high)
    if high_value == 0.0:
        return 1.0 / high - 1.0
    for _ in range(1100):
        midpoint = (low + high) / 2.0
        if midpoint == low or midpoint == high:
            break
        value = polynomial(midpoint)
        if value == 0.0:
            return 1.0 / midpoint - 1.0
        if (value > 0.0) == (low_value > 0.0):
            low, low_value = midpoint, value
        else:
            high = midpoint
    discount_factor = (low + high) / 2.0 or high
    return 1.0 / discount_factor - 1.0


def levelized_cost(
    costs: Sequence[float],
    output: Sequence[float],
    discount_rate: float,
) -> float | None:
    if len(costs) != len(output) or not costs:
        raise ValueError("costs and output must have the same nonzero length")
    denominator = net_present_value(discount_rate, output)
    if denominator <= 0.0:
        return None
    return net_present_value(discount_rate, costs) / denominator


def price_trajectory(
    initial_value: float,
    periods: int,
    *,
    escalation: float = 0.0,
) -> tuple[float, ...]:
    """Return period-one through period-N prices for a declared escalation rate."""

    period_count = _finite_integer(periods, "periods")
    if period_count <= 0:
        raise ValueError("periods must be a positive integer")
    initial = _number(initial_value, "initial_value")
    rate = _rate(escalation, "escalation")
    return tuple(initial * (1.0 + rate) ** period for period in range(period_count))


def _annual_schedule(
    explicit: Sequence[float] | None,
    *,
    initial: float,
    escalation: float,
    periods: int,
    name: str,
) -> tuple[float, ...]:
    initial_value = _number(initial, f"{name} initial value")
    escalation_rate = _rate(escalation, f"{name} escalation")
    if explicit is None:
        return price_trajectory(initial_value, periods, escalation=escalation_rate)
    values = tuple(
        _number(value, f"{name} year {year}") for year, value in enumerate(explicit, 1)
    )
    if len(values) != periods:
        raise ValueError(f"{name} must contain exactly {periods} annual values")
    return values


@dataclass(frozen=True)
class EconomicResult:
    currency: str
    project_life_years: int
    discount_rate: float
    cash_flows: tuple[float, ...]
    npv: float
    irr: float | None
    simple_payback_years: float | None
    discounted_payback_years: float | None
    benefit_cost_ratio: float | None
    annualized_capital_cost: float
    levelized_cost_per_mwh_saved: float | None
    levelized_cost_per_mwh_ex_saved: float | None
    levelized_cost_per_mwh_output: float | None
    marginal_abatement_cost_per_tonne_co2e: float | None
    annual_benefits: Mapping[str, float]
    annual_energy_prices_per_mwh: tuple[float, ...]
    annual_carbon_prices_per_tonne: tuple[float, ...]
    assumptions: Mapping[str, Any]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "currency": self.currency,
            "project_life_years": self.project_life_years,
            "discount_rate": self.discount_rate,
            "cash_flows": list(self.cash_flows),
            "npv": self.npv,
            "irr": self.irr,
            "simple_payback_years": self.simple_payback_years,
            "discounted_payback_years": self.discounted_payback_years,
            "benefit_cost_ratio": self.benefit_cost_ratio,
            "annualized_capital_cost": self.annualized_capital_cost,
            "levelized_cost_per_mwh_saved": self.levelized_cost_per_mwh_saved,
            "levelized_cost_per_mwh_ex_saved": self.levelized_cost_per_mwh_ex_saved,
            "levelized_cost_per_mwh_output": self.levelized_cost_per_mwh_output,
            "marginal_abatement_cost_per_tonne_co2e": self.marginal_abatement_cost_per_tonne_co2e,
            "annual_benefits": dict(self.annual_benefits),
            "annual_energy_prices_per_mwh": list(self.annual_energy_prices_per_mwh),
            "annual_carbon_prices_per_tonne": list(self.annual_carbon_prices_per_tonne),
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


def evaluate_economics(
    *,
    capital_cost: float,
    annual_energy_savings_mwh: float = 0.0,
    energy_price_per_mwh: float = 0.0,
    annual_energy_prices_per_mwh: Sequence[float] | None = None,
    annual_exergy_savings_mwh: float | None = None,
    annual_output_mwh: float | None = None,
    annual_maintenance_savings: float = 0.0,
    annual_other_benefits: float = 0.0,
    annual_product_revenue: float = 0.0,
    annual_opex_increase: float = 0.0,
    annual_co2e_reduction_kg: float = 0.0,
    carbon_price_per_tonne: float = 0.0,
    annual_carbon_prices_per_tonne: Sequence[float] | None = None,
    carbon_price_escalation: float = 0.0,
    annual_health_externality_reduction: float = 0.0,
    project_life_years: int = 20,
    discount_rate: float = 0.07,
    energy_price_escalation: float = 0.0,
    residual_value: float = 0.0,
    currency: str = "USD",
) -> EconomicResult:
    """Evaluate a project with transparent cash flows and optional externalities."""

    life = _finite_integer(project_life_years, "project_life_years")
    if life <= 0:
        raise ValueError("project_life_years must be a positive integer")
    rate = _rate(discount_rate, "discount_rate")
    escalation = _rate(energy_price_escalation, "energy_price_escalation")
    carbon_escalation = _rate(carbon_price_escalation, "carbon_price_escalation")
    capex = _number(capital_cost, "capital_cost")
    if capex < 0.0:
        raise ValueError("capital_cost must be nonnegative")
    energy_savings = _number(annual_energy_savings_mwh, "annual_energy_savings_mwh")
    exergy_savings = (
        _number(annual_exergy_savings_mwh, "annual_exergy_savings_mwh")
        if annual_exergy_savings_mwh is not None
        else None
    )
    carbon_reduction = _number(annual_co2e_reduction_kg, "annual_co2e_reduction_kg")
    energy_price = _number(energy_price_per_mwh, "energy_price_per_mwh")
    carbon_price = _number(carbon_price_per_tonne, "carbon_price_per_tonne")
    maintenance = _number(annual_maintenance_savings, "annual_maintenance_savings")
    other = _number(annual_other_benefits, "annual_other_benefits")
    product_revenue = _number(annual_product_revenue, "annual_product_revenue")
    opex = _number(annual_opex_increase, "annual_opex_increase")
    health = _number(
        annual_health_externality_reduction,
        "annual_health_externality_reduction",
    )
    residual = _number(residual_value, "residual_value")
    currency = normalize_currency(currency)

    energy_prices = _annual_schedule(
        annual_energy_prices_per_mwh,
        initial=energy_price,
        escalation=escalation,
        periods=life,
        name="annual_energy_prices_per_mwh",
    )
    carbon_prices = _annual_schedule(
        annual_carbon_prices_per_tonne,
        initial=carbon_price,
        escalation=carbon_escalation,
        periods=life,
        name="annual_carbon_prices_per_tonne",
    )
    cash_flows = [-capex]
    energy_benefits: list[float] = []
    carbon_benefits: list[float] = []
    for year in range(1, life + 1):
        energy_benefit = energy_savings * energy_prices[year - 1]
        carbon_benefit = carbon_reduction / 1000.0 * carbon_prices[year - 1]
        energy_benefits.append(energy_benefit)
        carbon_benefits.append(carbon_benefit)
        benefit = (
            energy_benefit
            + maintenance
            + other
            + product_revenue
            + carbon_benefit
            + health
            - opex
        )
        if year == life:
            benefit += residual
        cash_flows.append(benefit)

    benefit_flows = [0.0]
    cost_flows = [capex]
    for year in range(life):
        gross_benefit = (
            energy_benefits[year]
            + maintenance
            + other
            + product_revenue
            + carbon_benefits[year]
            + health
            + (residual if year == life - 1 else 0.0)
        )
        benefit_flows.append(max(gross_benefit, 0.0) + max(-opex, 0.0))
        cost_flows.append(max(opex, 0.0) + max(-gross_benefit, 0.0))
    pv_benefits = net_present_value(rate, benefit_flows)
    pv_costs = net_present_value(rate, cost_flows)
    benefit_cost = pv_benefits / pv_costs if pv_costs > 0.0 else None
    annualized_capital = capex * capital_recovery_factor(rate, life)

    project_costs = [capex] + [opex] * life
    project_costs[-1] -= residual
    energy_output = [0.0] + [max(energy_savings, 0.0)] * life
    exergy_output = [0.0] + [max(exergy_savings or 0.0, 0.0)] * life
    levelized_energy = levelized_cost(project_costs, energy_output, rate)
    levelized_exergy = (
        levelized_cost(project_costs, exergy_output, rate)
        if exergy_savings is not None
        else None
    )
    output_quantity = (
        _number(annual_output_mwh, "annual_output_mwh")
        if annual_output_mwh is not None
        else None
    )
    if output_quantity is not None and output_quantity < 0.0:
        raise ValueError("annual_output_mwh must be nonnegative")
    output_series = (
        [0.0] + [max(output_quantity or 0.0, 0.0)] * life
        if output_quantity is not None
        else None
    )
    levelized_output = (
        levelized_cost(project_costs, output_series, rate)
        if output_series is not None
        else None
    )
    discounted_reduction_tonnes = net_present_value(
        rate, [0.0] + [max(carbon_reduction, 0.0) / 1000.0] * life
    )
    discounted_private_net_cost = net_present_value(
        rate,
        [capex]
        + [
            opex
            - energy_benefits[index]
            - maintenance
            - other
            - product_revenue
            - (residual if index == life - 1 else 0.0)
            for index in range(life)
        ],
    )
    marginal_abatement = (
        discounted_private_net_cost / discounted_reduction_tonnes
        if discounted_reduction_tonnes > 0.0
        else None
    )

    warnings: list[str] = []
    result_irr = internal_rate_of_return(cash_flows)
    if result_irr is None and any(value > 0.0 for value in cash_flows[1:]):
        warnings.append(
            "IRR is unavailable because the cash-flow pattern has no unique root in the screened range."
        )
    if any(carbon_prices) or health:
        warnings.append(
            "Climate and health values are scenario assumptions, not universal market prices."
        )
    return EconomicResult(
        currency=currency,
        project_life_years=life,
        discount_rate=rate,
        cash_flows=tuple(cash_flows),
        npv=net_present_value(rate, cash_flows),
        irr=result_irr,
        simple_payback_years=simple_payback_period(cash_flows),
        discounted_payback_years=discounted_payback_period(rate, cash_flows),
        benefit_cost_ratio=benefit_cost,
        annualized_capital_cost=annualized_capital,
        levelized_cost_per_mwh_saved=levelized_energy,
        levelized_cost_per_mwh_ex_saved=levelized_exergy,
        levelized_cost_per_mwh_output=levelized_output,
        marginal_abatement_cost_per_tonne_co2e=marginal_abatement,
        annual_benefits={
            "energy_first_year": energy_benefits[0] if energy_benefits else 0.0,
            "maintenance": maintenance,
            "other": other,
            "carbon": carbon_benefits[0] if carbon_benefits else 0.0,
            "health_externality": health,
            "product_revenue": product_revenue,
            "opex_increase": opex,
        },
        annual_energy_prices_per_mwh=energy_prices,
        annual_carbon_prices_per_tonne=carbon_prices,
        assumptions={
            "capital_cost": capex,
            "energy_price_per_mwh": energy_price,
            "energy_price_escalation": escalation,
            "carbon_price_per_tonne": carbon_price,
            "carbon_price_escalation": carbon_escalation,
            "residual_value": residual,
        },
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class TechnologyCostScenario:
    """User-supplied technology costs with no proprietary built-in values."""

    name: str
    capital_cost: float
    annual_output_mwh: float
    output_name: str = "useful energy"
    currency: str = "USD"
    price_year: int | None = None
    project_life_years: int = 20
    discount_rate: float = 0.07
    annual_fixed_opex: float = 0.0
    variable_opex_per_mwh: float = 0.0
    annual_fuel_use_mwh: float = 0.0
    fuel_price_per_mwh: float = 0.0
    fuel_price_escalation: float = 0.0
    annual_fuel_prices_per_mwh: tuple[float, ...] = ()
    annual_emissions_kg_co2e: float = 0.0
    carbon_price_per_tonne: float = 0.0
    carbon_price_escalation: float = 0.0
    annual_carbon_prices_per_tonne: tuple[float, ...] = ()
    output_value_per_mwh: float = 0.0
    output_value_escalation: float = 0.0
    annual_output_values_per_mwh: tuple[float, ...] = ()
    output_degradation: float = 0.0
    residual_value: float = 0.0
    source: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TechnologyCostScenario":
        fields = cls.__dataclass_fields__
        unknown = sorted(set(value) - set(fields))
        if unknown:
            raise ValueError("unknown technology cost fields: " + ", ".join(unknown))
        payload = {name: item for name, item in value.items() if name in fields}
        for name in (
            "annual_fuel_prices_per_mwh",
            "annual_carbon_prices_per_tonne",
            "annual_output_values_per_mwh",
        ):
            if name in payload:
                payload[name] = tuple(payload[name])
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        result = dict(self.__dict__)
        result["annual_fuel_prices_per_mwh"] = list(self.annual_fuel_prices_per_mwh)
        result["annual_carbon_prices_per_tonne"] = list(
            self.annual_carbon_prices_per_tonne
        )
        result["annual_output_values_per_mwh"] = list(self.annual_output_values_per_mwh)
        result["metadata"] = dict(self.metadata)
        return result


@dataclass(frozen=True)
class TechnologyEconomicResult:
    scenario: TechnologyCostScenario
    annual_outputs_mwh: tuple[float, ...]
    annual_fuel_prices_per_mwh: tuple[float, ...]
    annual_carbon_prices_per_tonne: tuple[float, ...]
    annual_costs: tuple[float, ...]
    annual_revenues: tuple[float, ...]
    cash_flows: tuple[float, ...]
    npv: float
    irr: float | None
    simple_payback_years: float | None
    discounted_payback_years: float | None
    annualized_capital_cost: float
    levelized_cost_per_mwh: float | None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "scenario": self.scenario.to_dict(),
            "annual_outputs_mwh": list(self.annual_outputs_mwh),
            "annual_fuel_prices_per_mwh": list(self.annual_fuel_prices_per_mwh),
            "annual_carbon_prices_per_tonne": list(self.annual_carbon_prices_per_tonne),
            "annual_costs": list(self.annual_costs),
            "annual_revenues": list(self.annual_revenues),
            "cash_flows": list(self.cash_flows),
            "npv": self.npv,
            "irr": self.irr,
            "simple_payback_years": self.simple_payback_years,
            "discounted_payback_years": self.discounted_payback_years,
            "annualized_capital_cost": self.annualized_capital_cost,
            "levelized_cost_per_mwh": self.levelized_cost_per_mwh,
            "levelized_cost_unit": (
                f"{self.scenario.currency}/MWh {self.scenario.output_name}"
            ),
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


def evaluate_technology_cost_scenario(
    scenario: TechnologyCostScenario | Mapping[str, Any],
) -> TechnologyEconomicResult:
    """Calculate levelized cost and cash flow from a user-declared scenario."""

    item = (
        scenario
        if isinstance(scenario, TechnologyCostScenario)
        else TechnologyCostScenario.from_mapping(scenario)
    )
    life = _finite_integer(item.project_life_years, "project_life_years")
    if life <= 0:
        raise ValueError("project_life_years must be a positive integer")
    price_year = (
        _finite_integer(item.price_year, "price_year")
        if item.price_year is not None
        else None
    )
    item = replace(
        item,
        project_life_years=life,
        price_year=price_year,
        currency=normalize_currency(item.currency),
    )
    rate = _rate(item.discount_rate, "discount_rate")
    capex = _number(item.capital_cost, "capital_cost")
    output = _number(item.annual_output_mwh, "annual_output_mwh")
    if capex < 0.0 or output < 0.0:
        raise ValueError("capital_cost and annual_output_mwh must be nonnegative")
    output_degradation = _number(item.output_degradation, "output_degradation")
    if output_degradation < 0.0 or output_degradation >= 1.0:
        raise ValueError("output_degradation must be between zero and one")
    outputs = tuple(output * (1.0 - output_degradation) ** year for year in range(life))
    fuel_prices = _annual_schedule(
        item.annual_fuel_prices_per_mwh or None,
        initial=item.fuel_price_per_mwh,
        escalation=item.fuel_price_escalation,
        periods=life,
        name="annual_fuel_prices_per_mwh",
    )
    carbon_prices = _annual_schedule(
        item.annual_carbon_prices_per_tonne or None,
        initial=item.carbon_price_per_tonne,
        escalation=item.carbon_price_escalation,
        periods=life,
        name="annual_carbon_prices_per_tonne",
    )
    output_values = _annual_schedule(
        item.annual_output_values_per_mwh or None,
        initial=item.output_value_per_mwh,
        escalation=item.output_value_escalation,
        periods=life,
        name="annual_output_values_per_mwh",
    )
    if min((*fuel_prices, *carbon_prices, *output_values), default=0.0) < 0.0:
        raise ValueError(
            "fuel prices, carbon prices, and output values must be nonnegative"
        )
    fixed_opex = _number(item.annual_fixed_opex, "annual_fixed_opex")
    variable_opex = _number(item.variable_opex_per_mwh, "variable_opex_per_mwh")
    fuel_use = _number(item.annual_fuel_use_mwh, "annual_fuel_use_mwh")
    emissions = _number(item.annual_emissions_kg_co2e, "annual_emissions_kg_co2e")
    if min(fixed_opex, variable_opex, fuel_use, emissions) < 0.0:
        raise ValueError("operating costs, fuel use, and emissions must be nonnegative")
    annual_costs = tuple(
        fixed_opex
        + variable_opex * annual_output
        + fuel_use * fuel_price
        + emissions / 1000.0 * carbon_price
        for annual_output, fuel_price, carbon_price in zip(
            outputs, fuel_prices, carbon_prices
        )
    )
    annual_revenues = tuple(
        annual_output * value for annual_output, value in zip(outputs, output_values)
    )
    cash_flows = [-capex]
    for year, (cost, revenue) in enumerate(zip(annual_costs, annual_revenues), 1):
        cash = revenue - cost
        if year == life:
            cash += _number(item.residual_value, "residual_value")
        cash_flows.append(cash)
    residual = _number(item.residual_value, "residual_value")
    if residual < 0.0:
        raise ValueError("residual_value must be nonnegative")
    cost_series = [capex] + list(annual_costs)
    cost_series[-1] -= residual
    output_series = [0.0] + list(outputs)
    warnings: list[str] = []
    if item.source is None:
        warnings.append(
            "Technology costs are user supplied; record their source, price year, and currency basis for reproducibility."
        )
    if any(carbon_prices):
        warnings.append(
            "Carbon prices are scenario assumptions and are shown separately from fuel and operating costs."
        )
    return TechnologyEconomicResult(
        scenario=item,
        annual_outputs_mwh=outputs,
        annual_fuel_prices_per_mwh=fuel_prices,
        annual_carbon_prices_per_tonne=carbon_prices,
        annual_costs=annual_costs,
        annual_revenues=annual_revenues,
        cash_flows=tuple(cash_flows),
        npv=net_present_value(rate, cash_flows),
        irr=internal_rate_of_return(cash_flows),
        simple_payback_years=simple_payback_period(cash_flows),
        discounted_payback_years=discounted_payback_period(rate, cash_flows),
        annualized_capital_cost=capex * capital_recovery_factor(rate, life),
        levelized_cost_per_mwh=levelized_cost(cost_series, output_series, rate),
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class TechnologyScenarioComparison:
    results: Mapping[str, TechnologyEconomicResult]
    lowest_levelized_cost: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "lowest_levelized_cost": self.lowest_levelized_cost,
            "results": {
                name: result.to_dict() for name, result in self.results.items()
            },
        }


def compare_technology_cost_scenarios(
    scenarios: Mapping[str, TechnologyCostScenario | Mapping[str, Any]],
) -> TechnologyScenarioComparison:
    if not scenarios:
        raise ValueError("at least one technology cost scenario is required")
    results = {
        name: evaluate_technology_cost_scenario(value)
        for name, value in scenarios.items()
    }
    comparable = {
        name: result.levelized_cost_per_mwh
        for name, result in results.items()
        if result.levelized_cost_per_mwh is not None
    }
    comparable_currencies = {
        results[name].scenario.currency.strip().upper() for name in comparable
    }
    if len(comparable_currencies) > 1:
        raise ValueError(
            "technology cost scenarios must use one currency before levelized costs can be ranked"
        )
    comparable_outputs = {
        results[name].scenario.output_name.strip().casefold() for name in comparable
    }
    if len(comparable_outputs) > 1:
        raise ValueError(
            "technology cost scenarios must use one output basis before levelized costs can be ranked"
        )
    comparable_price_years = {
        results[name].scenario.price_year
        for name in comparable
        if results[name].scenario.price_year is not None
    }
    if len(comparable_price_years) > 1 or (
        comparable_price_years
        and any(results[name].scenario.price_year is None for name in comparable)
    ):
        raise ValueError(
            "technology cost scenarios must use one declared price year before levelized costs can be ranked"
        )
    lowest = min(comparable, key=comparable.get) if comparable else None
    return TechnologyScenarioComparison(results=results, lowest_levelized_cost=lowest)


@dataclass(frozen=True)
class StrandedCostCase:
    retirement_year: int
    years_operated: int
    remaining_life_years: int
    undepreciated_value: float
    net_stranded_cost: float
    currency: str

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def stranded_asset_value(
    *,
    capital_cost: float,
    commissioning_year: int,
    retirement_year: int,
    planned_life_years: int,
    residual_value: float = 0.0,
    recoverable_value: float = 0.0,
    decommissioning_cost: float = 0.0,
    currency: str = "USD",
) -> StrandedCostCase:
    """Return straight-line undepreciated and net stranded cost at retirement."""

    life = _finite_integer(planned_life_years, "planned_life_years")
    if life <= 0:
        raise ValueError("planned_life_years must be a positive integer")
    commissioned = _finite_integer(commissioning_year, "commissioning_year")
    retired = _finite_integer(retirement_year, "retirement_year")
    if retired < commissioned:
        raise ValueError("retirement_year must not precede commissioning_year")
    capex = _number(capital_cost, "capital_cost")
    residual = _number(residual_value, "residual_value")
    recoverable = _number(recoverable_value, "recoverable_value")
    decommissioning = _number(decommissioning_cost, "decommissioning_cost")
    currency = normalize_currency(currency)
    if min(capex, residual, recoverable, decommissioning) < 0.0:
        raise ValueError("costs and recoverable values must be nonnegative")
    if residual > capex:
        raise ValueError("residual_value must not exceed capital_cost")
    years_operated = min(retired - commissioned, life)
    remaining = max(life - years_operated, 0)
    depreciable = max(capex - residual, 0.0)
    undepreciated = residual + depreciable * remaining / life
    net = max(undepreciated + decommissioning - recoverable, 0.0)
    return StrandedCostCase(
        retirement_year=retired,
        years_operated=years_operated,
        remaining_life_years=remaining,
        undepreciated_value=undepreciated,
        net_stranded_cost=net,
        currency=currency,
    )


def stranded_cost_sensitivity(
    retirement_years: Iterable[int],
    **options: Any,
) -> tuple[StrandedCostCase, ...]:
    raw_years = tuple(retirement_years)
    years = tuple(
        _finite_integer(year, f"retirement_years[{index}]")
        for index, year in enumerate(raw_years)
    )
    if not years:
        raise ValueError("retirement_years must not be empty")
    return tuple(
        stranded_asset_value(retirement_year=year, **options) for year in years
    )
