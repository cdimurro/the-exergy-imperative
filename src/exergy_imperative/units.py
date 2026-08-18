"""Small, dependency-free unit helpers used by the core package."""

from __future__ import annotations

import math
import re
from typing import SupportsFloat


class UnitError(ValueError):
    """Raised when a value cannot be safely converted."""


_ENERGY_TO_MWH = {
    "j": 1.0 / 3_600_000_000.0,
    "kj": 1.0 / 3_600_000.0,
    "mj": 1.0 / 3_600.0,
    "gj": 1.0 / 3.6,
    "tj": 1_000.0 / 3.6,
    "wh": 1.0e-6,
    "kwh": 1.0e-3,
    "mwh": 1.0,
    "gwh": 1_000.0,
    "twh": 1_000_000.0,
    "btu": 1_055.05585262 / 3_600_000_000.0,
    "mmbtu": 1_055.05585262e6 / 3_600_000_000.0,
    "therm": 105_505_585.262 / 3_600_000_000.0,
    "kcal": 4_184.0 / 3_600_000_000.0,
    "toe": 41.868 / 3.6,
}

_DISPLAY_ENERGY_UNITS = {
    "j": "J",
    "kj": "kJ",
    "mj": "MJ",
    "gj": "GJ",
    "tj": "TJ",
    "wh": "Wh",
    "kwh": "kWh",
    "mwh": "MWh",
    "gwh": "GWh",
    "twh": "TWh",
    "btu": "Btu",
    "mmbtu": "MMBtu",
    "therm": "therm",
    "kcal": "kcal",
    "toe": "toe",
}

SUPPORTED_ENERGY_UNITS: tuple[str, ...] = tuple(_DISPLAY_ENERGY_UNITS.values())

_TEMPERATURE_PATTERN = re.compile(
    r"^\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*"
    r"(?:°|deg(?:ree)?s?\s*)?\s*([cCfFkK])?\s*$"
)


def _finite(value: SupportsFloat, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise UnitError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise UnitError(f"{name} must be finite")
    return number


def energy_unit_key(unit: str) -> str:
    """Return the energy scale from a typed unit such as ``MWh_HHV_CH4``."""

    if not isinstance(unit, str) or not unit.strip():
        raise UnitError("energy unit is required")
    normalized = unit.strip().replace(" ", "").replace("-", "_").lower()
    if normalized in _ENERGY_TO_MWH:
        return normalized
    prefix = normalized.split("_", 1)[0]
    if prefix in _ENERGY_TO_MWH:
        return prefix
    raise UnitError(
        f"unsupported energy unit {unit!r}; supported scales are "
        + ", ".join(SUPPORTED_ENERGY_UNITS)
    )


def is_energy_unit(unit: str) -> bool:
    try:
        energy_unit_key(unit)
    except UnitError:
        return False
    return True


def canonical_energy_unit(unit: str) -> str:
    return _DISPLAY_ENERGY_UNITS[energy_unit_key(unit)]


def energy_basis(unit: str) -> str | None:
    """Return an HHV/LHV qualifier embedded in a typed energy unit, if present."""

    energy_unit_key(unit)
    tokens = set(re.sub(r"[^a-z0-9]+", "_", unit.strip().lower()).split("_"))
    bases = {item.upper() for item in tokens if item in {"hhv", "lhv"}}
    if len(bases) > 1:
        raise UnitError(f"energy unit {unit!r} contains conflicting HHV/LHV qualifiers")
    return next(iter(bases), None)


def convert_energy(value: SupportsFloat, from_unit: str, to_unit: str = "MWh") -> float:
    """Convert an energy quantity without silently changing HHV/LHV basis.

    Typed suffixes other than HHV/LHV remain metadata.  A conversion between
    two explicitly different calorific-value bases requires a fuel-specific
    conversion and is therefore rejected here.
    """

    number = _finite(value, "energy")
    from_key = energy_unit_key(from_unit)
    to_key = energy_unit_key(to_unit)
    from_basis = energy_basis(from_unit)
    to_basis = energy_basis(to_unit)
    if from_basis is not None and to_basis is not None and from_basis != to_basis:
        raise UnitError(
            f"cannot convert {from_basis} energy to {to_basis} without a "
            "fuel-specific HHV/LHV conversion factor"
        )
    return number * _ENERGY_TO_MWH[from_key] / _ENERGY_TO_MWH[to_key]


def parse_temperature(
    value: SupportsFloat | str,
    unit: str | None = None,
    *,
    default_unit: str = "C",
) -> float:
    """Return temperature in degrees Celsius.

    Strings may include their unit (``"68 F"`` or ``"293.15 K"``). Numeric
    values use ``unit`` or ``default_unit``.
    """

    detected_unit = unit
    if isinstance(value, str):
        match = _TEMPERATURE_PATTERN.match(value)
        if not match:
            raise UnitError(f"invalid temperature {value!r}")
        number = _finite(match.group(1), "temperature")
        detected_unit = match.group(2) or unit or default_unit
    else:
        number = _finite(value, "temperature")
        detected_unit = unit or default_unit

    key = str(detected_unit).strip().lower().replace("°", "")
    key = key.replace("degrees", "").replace("degree", "").replace("deg", "").strip()
    if key == "c":
        celsius = number
    elif key == "f":
        celsius = (number - 32.0) * 5.0 / 9.0
    elif key == "k":
        celsius = number - 273.15
    else:
        raise UnitError(
            f"unsupported temperature unit {detected_unit!r}; use C, F, or K"
        )
    if not math.isfinite(celsius):
        raise UnitError("temperature conversion must be finite")
    if celsius < -273.15:
        raise UnitError("temperature cannot be below absolute zero")
    return celsius


def temperature_to_k(value: SupportsFloat | str, unit: str | None = None) -> float:
    kelvin = parse_temperature(value, unit) + 273.15
    if kelvin <= 0.0:
        raise UnitError("thermodynamic temperature must be greater than 0 K")
    return kelvin


def exergy_unit_for(unit: str) -> str:
    """Return a typed exergy unit matching the input energy scale."""

    return f"{canonical_energy_unit(unit)}_ex"
