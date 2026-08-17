"""Optional thermophysical-property integration for F4 physical exergy."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .formulas import physical_flow_exergy
from .models import Environment
from .units import parse_temperature


@dataclass(frozen=True)
class PhysicalExergyResult:
    fluid: str
    temperature_c: float
    pressure_kpa: float
    reference_temperature_c: float
    reference_pressure_kpa: float
    enthalpy_j_per_kg: float
    entropy_j_per_kg_k: float
    reference_enthalpy_j_per_kg: float
    reference_entropy_j_per_kg_k: float
    physical_exergy_j_per_kg: float
    exergy_rate_kw: float | None = None
    method_id: str = "physical.coolprop.state-vector.v1"

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in self.__dict__.items() if value is not None}


def coolprop_available() -> bool:
    try:
        import CoolProp.CoolProp  # noqa: F401
    except ImportError:
        return False
    return True


def coolprop_physical_exergy(
    fluid: str,
    temperature: float | str,
    pressure_kpa: float,
    *,
    temperature_unit: str = "C",
    environment: Environment | None = None,
    mass_flow_kg_s: float | None = None,
) -> PhysicalExergyResult:
    """Calculate physical flow exergy from a full fluid state using CoolProp.

    Chemical, kinetic, and potential exergy are intentionally excluded.
    Install with ``pip install exergy-imperative[properties]``.
    """

    try:
        from CoolProp.CoolProp import PropsSI
    except ImportError as exc:  # pragma: no cover - depends on optional environment
        raise RuntimeError(
            "CoolProp is required; install exergy-imperative[properties]"
        ) from exc
    environment = environment or Environment()
    temperature_c = parse_temperature(temperature, temperature_unit)
    pressure = float(pressure_kpa)
    if not math.isfinite(pressure) or pressure <= 0.0:
        raise ValueError("pressure_kpa must be finite and positive")
    mass_flow = float(mass_flow_kg_s) if mass_flow_kg_s is not None else None
    if mass_flow is not None and (not math.isfinite(mass_flow) or mass_flow < 0.0):
        raise ValueError("mass_flow_kg_s must be finite and nonnegative")
    temperature_k = temperature_c + 273.15
    pressure_pa = pressure * 1_000.0
    reference_k = environment.temperature_k
    reference_pa = environment.pressure_kpa * 1_000.0
    enthalpy = float(PropsSI("Hmass", "T", temperature_k, "P", pressure_pa, fluid))
    entropy = float(PropsSI("Smass", "T", temperature_k, "P", pressure_pa, fluid))
    reference_enthalpy = float(
        PropsSI("Hmass", "T", reference_k, "P", reference_pa, fluid)
    )
    reference_entropy = float(
        PropsSI("Smass", "T", reference_k, "P", reference_pa, fluid)
    )
    specific_exergy = physical_flow_exergy(
        enthalpy,
        reference_enthalpy,
        entropy,
        reference_entropy,
        reference_k,
    )
    rate_kw = specific_exergy * mass_flow / 1_000.0 if mass_flow is not None else None
    return PhysicalExergyResult(
        fluid=fluid,
        temperature_c=temperature_c,
        pressure_kpa=pressure,
        reference_temperature_c=environment.temperature_c,
        reference_pressure_kpa=environment.pressure_kpa,
        enthalpy_j_per_kg=enthalpy,
        entropy_j_per_kg_k=entropy,
        reference_enthalpy_j_per_kg=reference_enthalpy,
        reference_entropy_j_per_kg_k=reference_entropy,
        physical_exergy_j_per_kg=specific_exergy,
        exergy_rate_kw=rate_kw,
    )
