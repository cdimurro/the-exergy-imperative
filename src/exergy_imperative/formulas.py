"""Validated thermodynamic kernels with no profile or data assumptions."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import SupportsFloat

SOLAR_TEMPERATURE_K = 5_778.0
STEFAN_BOLTZMANN = 5.670374419e-8
UNIVERSAL_GAS_CONSTANT = 8.31446261815324


def _number(value: SupportsFloat, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _positive(value: SupportsFloat, name: str) -> float:
    number = _number(value, name)
    if number <= 0.0:
        raise ValueError(f"{name} must be greater than zero")
    return number


def _nonnegative(value: SupportsFloat, name: str) -> float:
    number = _number(value, name)
    if number < 0.0:
        raise ValueError(f"{name} must be nonnegative")
    return number


def thermal_exergy_factor(source_k: SupportsFloat, reference_k: SupportsFloat) -> float:
    """Carnot factor for heat supplied isothermally above the reference state."""

    source = _positive(source_k, "source_k")
    reference = _positive(reference_k, "reference_k")
    if source < reference:
        raise ValueError("source_k must be at least reference_k for a heat service")
    return 1.0 - reference / source


def thermal_exergy_factor_c(
    source_c: SupportsFloat, reference_c: SupportsFloat
) -> float:
    return thermal_exergy_factor(
        _number(source_c, "source_c") + 273.15,
        _number(reference_c, "reference_c") + 273.15,
    )


def cooling_exergy_factor(cold_k: SupportsFloat, ambient_k: SupportsFloat) -> float:
    """Minimum work per unit cooling delivered below ambient temperature."""

    cold = _positive(cold_k, "cold_k")
    ambient = _positive(ambient_k, "ambient_k")
    if cold > ambient:
        raise ValueError("cold_k must not exceed ambient_k for a cooling service")
    return ambient / cold - 1.0


def cooling_exergy_factor_c(cold_c: SupportsFloat, ambient_c: SupportsFloat) -> float:
    return cooling_exergy_factor(
        _number(cold_c, "cold_c") + 273.15,
        _number(ambient_c, "ambient_c") + 273.15,
    )


def sensible_heat_exergy_factor(
    supply_k: SupportsFloat,
    return_k: SupportsFloat,
    reference_k: SupportsFloat,
) -> float:
    """Exergy fraction of sensible heat for a constant-heat-capacity stream.

    This evaluates ``1 - T0 ln(T_supply/T_return)/(T_supply-T_return)``.
    """

    supply = _positive(supply_k, "supply_k")
    return_ = _positive(return_k, "return_k")
    reference = _positive(reference_k, "reference_k")
    if supply <= return_:
        raise ValueError("supply_k must be greater than return_k")
    relative_lift = (supply - return_) / return_
    if relative_lift < 1e-4:
        # 1 - log1p(x) / x, evaluated without cancellation for close states.
        log_mean_correction = relative_lift * (
            0.5
            + relative_lift
            * (-1.0 / 3.0 + relative_lift * (0.25 - relative_lift / 5.0))
        )
    else:
        log_mean_correction = 1.0 - math.log1p(relative_lift) / relative_lift
    reference_ratio = reference / return_
    factor = (return_ - reference) / return_ + (reference_ratio * log_mean_correction)
    if factor < -1e-12:
        raise ValueError(
            "reference state is incompatible with a positive sensible-heat exergy factor"
        )
    return max(0.0, factor)


def sensible_heat_exergy_factor_c(
    supply_c: SupportsFloat,
    return_c: SupportsFloat,
    reference_c: SupportsFloat,
) -> float:
    return sensible_heat_exergy_factor(
        _number(supply_c, "supply_c") + 273.15,
        _number(return_c, "return_c") + 273.15,
        _number(reference_c, "reference_c") + 273.15,
    )


def physical_flow_exergy(
    enthalpy: SupportsFloat,
    reference_enthalpy: SupportsFloat,
    entropy: SupportsFloat,
    reference_entropy: SupportsFloat,
    reference_k: SupportsFloat,
) -> float:
    """Specific physical flow exergy in the units used for enthalpy.

    Entropy must use the matching energy-per-temperature basis.
    """

    h = _number(enthalpy, "enthalpy")
    h0 = _number(reference_enthalpy, "reference_enthalpy")
    s = _number(entropy, "entropy")
    s0 = _number(reference_entropy, "reference_entropy")
    t0 = _positive(reference_k, "reference_k")
    return (h - h0) - t0 * (s - s0)


def exergy_destruction(
    reference_k: SupportsFloat, entropy_generation: SupportsFloat
) -> float:
    return _positive(reference_k, "reference_k") * _nonnegative(
        entropy_generation, "entropy_generation"
    )


def kinetic_exergy(mass: SupportsFloat, velocity: SupportsFloat) -> float:
    return 0.5 * _nonnegative(mass, "mass") * _number(velocity, "velocity") ** 2


def potential_exergy(
    mass: SupportsFloat,
    elevation_difference: SupportsFloat,
    gravity: SupportsFloat = 9.80665,
) -> float:
    return (
        _nonnegative(mass, "mass")
        * _number(gravity, "gravity")
        * _number(elevation_difference, "elevation_difference")
    )


def ideal_gas_pressure_exergy(
    amount_mol: SupportsFloat,
    pressure: SupportsFloat,
    reference_pressure: SupportsFloat,
    reference_k: SupportsFloat,
) -> float:
    amount = _nonnegative(amount_mol, "amount_mol")
    p = _positive(pressure, "pressure")
    p0 = _positive(reference_pressure, "reference_pressure")
    t0 = _positive(reference_k, "reference_k")
    return amount * UNIVERSAL_GAS_CONSTANT * t0 * math.log(p / p0)


def ideal_mixture_separation_exergy(
    amount_mol: SupportsFloat,
    mole_fractions: Sequence[SupportsFloat],
    reference_k: SupportsFloat,
) -> float:
    """Minimum reversible separation work for an ideal mixture in joules."""

    amount = _nonnegative(amount_mol, "amount_mol")
    t0 = _positive(reference_k, "reference_k")
    fractions = [_number(value, "mole_fraction") for value in mole_fractions]
    if not fractions or any(value < 0.0 or value > 1.0 for value in fractions):
        raise ValueError(
            "mole fractions must be a non-empty sequence between zero and one"
        )
    if not math.isclose(sum(fractions), 1.0, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError("mole fractions must sum to one")
    mixing_sum = sum(value * math.log(value) for value in fractions if value > 0.0)
    return -amount * UNIVERSAL_GAS_CONSTANT * t0 * mixing_sum


def petela_exergy_factor(
    reference_k: SupportsFloat = 298.15,
    radiation_temperature_k: SupportsFloat = SOLAR_TEMPERATURE_K,
) -> float:
    reference = _positive(reference_k, "reference_k")
    radiation = _positive(radiation_temperature_k, "radiation_temperature_k")
    if reference > radiation:
        raise ValueError("reference_k must not exceed radiation_temperature_k")
    ratio = reference / radiation
    return 1.0 - (4.0 / 3.0) * ratio + (1.0 / 3.0) * ratio**4


def accessible_exergy(energy: SupportsFloat, exergy_factor: SupportsFloat) -> float:
    quantity = _nonnegative(energy, "energy")
    factor = _nonnegative(exergy_factor, "exergy_factor")
    return quantity * factor


def exergetic_efficiency(
    product_exergy: SupportsFloat, input_exergy: SupportsFloat
) -> float:
    product = _nonnegative(product_exergy, "product_exergy")
    input_ = _positive(input_exergy, "input_exergy")
    efficiency = product / input_
    if efficiency > 1.0 + 1e-12:
        raise ValueError("product_exergy cannot exceed input_exergy")
    return min(1.0, efficiency)


def weighted_exergy_factor(
    records: Iterable[tuple[SupportsFloat, SupportsFloat]],
) -> float:
    weighted = 0.0
    total = 0.0
    for weight_value, factor_value in records:
        weight = _nonnegative(weight_value, "weight")
        factor = _nonnegative(factor_value, "exergy_factor")
        weighted += weight * factor
        total += weight
    if total <= 0.0:
        raise ValueError("at least one positive weight is required")
    return weighted / total
