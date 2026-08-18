"""Automatic, progressive-fidelity assessment from incomplete user inputs."""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

from .formulas import (
    cooling_exergy_factor_c,
    sensible_heat_exergy_factor_c,
    thermal_exergy_factor_c,
)
from .models import (
    AssessmentResult,
    Estimate,
    FidelityTier,
    Parameter,
    RefinementOpportunity,
    ValueStatus,
)
from .registry import DEFAULT_REGISTRY, Profile, Registry
from .units import convert_energy, energy_basis, parse_temperature


class MissingInputError(ValueError):
    """Raised when strict mode refuses to use a required default."""


def _provided(
    value: Any, unit: str | None = None, *, note: str | None = None
) -> Parameter:
    return Parameter(value=value, unit=unit, status=ValueStatus.PROVIDED, note=note)


def _parameter_range(parameter: Parameter) -> tuple[float, float]:
    value = float(parameter.value)
    return (
        float(parameter.low) if parameter.low is not None else value,
        float(parameter.high) if parameter.high is not None else value,
    )


def _validated_parameter_range(
    parameter: Parameter, name: str
) -> tuple[float, float, float]:
    low, high = _parameter_range(parameter)
    value = float(parameter.value)
    if not all(math.isfinite(item) for item in (low, value, high)):
        raise ValueError(f"{name} values must be finite")
    if low > value or value > high:
        raise ValueError(f"{name} range must satisfy low <= value <= high")
    return low, value, high


def _clipped_boundary_values(
    primary: tuple[float, float, float],
    constraint: tuple[float, float, float],
) -> tuple[float, ...]:
    low, _, high = primary
    values = [low, high]
    for boundary in (constraint[0], constraint[2]):
        values.append(min(max(boundary, low), high))
    return tuple(dict.fromkeys(values))


def _sensible_heat_screening_candidates(
    source_range: tuple[float, float, float],
    return_range: tuple[float, float, float],
    ambient_range: tuple[float, float, float],
) -> list[float]:
    """Evaluate rectangle corners plus active physical-constraint boundaries."""

    candidates: list[float] = []
    log_means_c: list[float] = []
    supply_values = _clipped_boundary_values(source_range, return_range)
    return_values = _clipped_boundary_values(return_range, source_range)
    for supply_c in supply_values:
        for return_c in return_values:
            if supply_c < return_c:
                continue
            supply_k = supply_c + 273.15
            return_k = return_c + 273.15
            if supply_k <= 0.0 or return_k <= 0.0:
                continue
            if supply_c == return_c:
                log_mean_c = supply_c
            else:
                log_mean_c = (supply_c - return_c) / math.log1p(
                    (supply_c - return_c) / return_k
                ) - 273.15
            log_means_c.append(log_mean_c)
            for ambient_c in (ambient_range[0], ambient_range[2]):
                try:
                    factor = (
                        thermal_exergy_factor_c(supply_c, ambient_c)
                        if supply_c == return_c
                        else sensible_heat_exergy_factor_c(
                            supply_c, return_c, ambient_c
                        )
                    )
                except ValueError:
                    continue
                candidates.append(factor)
    if log_means_c and max(min(log_means_c), ambient_range[0]) <= min(
        max(log_means_c), ambient_range[2]
    ):
        candidates.append(0.0)
    return candidates


def _estimate_from_parameter(parameter: Parameter, unit: str | None = None) -> Estimate:
    low, high = _parameter_range(parameter)
    value = float(parameter.value)
    resolved_unit = unit or parameter.unit or "dimensionless"
    if not all(math.isfinite(item) for item in (low, value, high)):
        raise ValueError(f"{resolved_unit} parameter values must be finite")
    if low > value or value > high:
        raise ValueError(
            f"{resolved_unit} parameter range must satisfy low <= value <= high"
        )
    if min(low, value, high) < 0.0:
        if resolved_unit.startswith("MWh_ex/MWh"):
            raise ValueError("exergy factors must be nonnegative")
        raise ValueError(f"{resolved_unit} parameter values must be nonnegative")
    return Estimate(
        value,
        resolved_unit,
        low,
        high,
        parameter.confidence,
    )


def _multiply(*estimates: Estimate, unit: str) -> Estimate:
    value = math.prod(item.value for item in estimates)
    lows = [item.low if item.low is not None else item.value for item in estimates]
    highs = [item.high if item.high is not None else item.value for item in estimates]
    return Estimate(
        value, unit, math.prod(lows), math.prod(highs), "propagated screening range"
    )


def _ratio(
    numerator: Estimate, denominator: Estimate, unit: str = "dimensionless"
) -> Estimate:
    if denominator.value <= 0.0:
        raise ValueError("ratio denominator must be positive")
    n_low = numerator.low if numerator.low is not None else numerator.value
    n_high = numerator.high if numerator.high is not None else numerator.value
    d_low = denominator.low if denominator.low is not None else denominator.value
    d_high = denominator.high if denominator.high is not None else denominator.value
    if d_low <= 0.0:
        raise ValueError("ratio denominator lower bound must be positive")
    return Estimate(
        numerator.value / denominator.value,
        unit,
        n_low / d_high,
        n_high / d_low,
        "propagated screening range",
    )


def _difference(input_: Estimate, output: Estimate, unit: str) -> Estimate:
    i_low = input_.low if input_.low is not None else input_.value
    i_high = input_.high if input_.high is not None else input_.value
    o_low = output.low if output.low is not None else output.value
    o_high = output.high if output.high is not None else output.value
    return Estimate(
        input_.value - output.value,
        unit,
        i_low - o_high,
        i_high - o_low,
        "combined destruction and unallocated losses",
    )


def _resolve_named_profile(
    registry: Registry, category: str, value: str | None
) -> Profile | None:
    if value is None:
        return None
    return registry.get(category, value)


def _select_basis_carrier(
    registry: Registry, carrier: str, basis: str | None
) -> Profile:
    profile = registry.get("carrier", carrier)
    if basis is None:
        return profile
    basis_key = basis.strip().upper()
    if basis_key not in {"HHV", "LHV"}:
        raise ValueError("basis must be HHV or LHV")
    family_name = profile.id
    if family_name in {"hydrogen-hhv", "hydrogen-lhv"}:
        return registry.get("carrier", f"hydrogen-{basis_key.lower()}")
    if family_name in {"natural-gas-hhv", "methane-lhv"}:
        target = "natural-gas-hhv" if basis_key == "HHV" else "methane-lhv"
        return registry.get("carrier", target)
    if profile.metadata.get("basis", "").upper() != basis_key:
        raise ValueError(f"no {basis_key} profile is bundled for {profile.label}")
    return profile


def _temperature_parameter(
    value: float | str | None,
    unit: str,
    name: str,
    profile: Profile | None,
    source_version: str,
) -> Parameter | None:
    if value is not None:
        return _provided(parse_temperature(value, unit), "C")
    if profile is None:
        return None
    return profile.parameter(name, source_version=source_version)


def _factor_from_service(
    service: Profile,
    parameters: dict[str, Parameter],
) -> tuple[Estimate | None, str, list[str]]:
    warnings: list[str] = []
    family = str(service.metadata.get("family", ""))
    if family == "thermal":
        source = parameters.get("source_temperature_c")
        ambient = parameters.get("ambient_temperature_c")
        if source is None or ambient is None:
            return (
                None,
                "thermal.insufficient-data.v1",
                ["Thermal exergy requires source and reference temperatures."],
            )
        source_range = _validated_parameter_range(source, "source_temperature_c")
        ambient_range = _validated_parameter_range(ambient, "ambient_temperature_c")
        return_ = parameters.get("return_temperature_c")
        use_integrated = return_ is not None and return_.status in {
            ValueStatus.PROVIDED,
            ValueStatus.MEASURED,
            ValueStatus.DATASET,
            ValueStatus.SITE_PROFILE,
        }
        if use_integrated:
            return_range = _validated_parameter_range(return_, "return_temperature_c")
            function = sensible_heat_exergy_factor_c
            central = function(
                float(source.value), float(return_.value), float(ambient.value)
            )
            candidates: list[float] = [central]
            candidates.extend(
                _sensible_heat_screening_candidates(
                    source_range, return_range, ambient_range
                )
            )
            if not candidates:
                raise ValueError(
                    "no valid supply-return-reference combination was available"
                )
            return (
                Estimate(
                    central,
                    "MWh_ex/MWh",
                    min(candidates),
                    max(candidates),
                    "screening range",
                ),
                "thermal.sensible-stream.v1",
                warnings,
            )
        function = thermal_exergy_factor_c
        central = function(float(source.value), float(ambient.value))
        candidates = [central]
        for source_c in (source_range[0], source_range[2]):
            for ambient_c in (ambient_range[0], ambient_range[2]):
                try:
                    candidates.append(function(source_c, ambient_c))
                except ValueError:
                    continue
        if max(source_range[0], ambient_range[0]) <= min(
            source_range[2], ambient_range[2]
        ):
            candidates.append(0.0)
        return (
            Estimate(
                central,
                "MWh_ex/MWh",
                min(candidates),
                max(candidates),
                "screening range",
            ),
            "thermal.carnot.constant-temperature.v1",
            warnings,
        )
    if family == "cooling":
        cold = parameters.get("cold_temperature_c")
        ambient = parameters.get("ambient_temperature_c")
        if cold is None or ambient is None:
            return (
                None,
                "cooling.insufficient-data.v1",
                ["Cooling exergy requires service and ambient temperatures."],
            )
        cold_range = _validated_parameter_range(cold, "cold_temperature_c")
        ambient_range = _validated_parameter_range(ambient, "ambient_temperature_c")
        central = cooling_exergy_factor_c(float(cold.value), float(ambient.value))
        candidates = [central]
        for cold_c in (cold_range[0], cold_range[2]):
            for ambient_c in (ambient_range[0], ambient_range[2]):
                try:
                    candidates.append(cooling_exergy_factor_c(cold_c, ambient_c))
                except ValueError:
                    continue
        if max(cold_range[0], ambient_range[0]) <= min(cold_range[2], ambient_range[2]):
            candidates.append(0.0)
        return (
            Estimate(
                central,
                "MWh_ex/MWh",
                min(candidates),
                max(candidates),
                "screening range",
            ),
            "cooling.minimum-work.v1",
            warnings,
        )
    return None, "service.unknown.v1", [f"Unsupported service family {family!r}."]


def _refinements(
    parameters: dict[str, Parameter],
    service: Profile | None,
    carrier: Profile | None,
    technology: Profile | None,
) -> list[RefinementOpportunity]:
    items: list[RefinementOpportunity] = []

    def assumed(name: str) -> bool:
        return name in parameters and parameters[name].is_assumed

    family = service.metadata.get("family") if service else None
    if family == "thermal":
        if assumed("source_temperature_c"):
            items.append(
                RefinementOpportunity(
                    "source_temperature",
                    "high",
                    "The heat-source temperature directly controls its work potential.",
                    "Asset-specific F2 thermal factor",
                )
            )
        if "return_temperature_c" not in parameters:
            items.append(
                RefinementOpportunity(
                    "return_temperature",
                    "high",
                    "A return temperature describes the full sensible-heat delivery interval.",
                    "Integrated water-stream method",
                )
            )
        if assumed("ambient_temperature_c"):
            items.append(
                RefinementOpportunity(
                    "ambient_temperature",
                    "medium",
                    "A local or measured reference temperature replaces the reporting default.",
                    "Location- or interval-specific comparison",
                )
            )
    elif family == "cooling":
        if assumed("cold_temperature_c"):
            items.append(
                RefinementOpportunity(
                    "cold_temperature",
                    "high",
                    "Cooling work depends strongly on the service temperature.",
                    "Asset-specific F2 cooling factor",
                )
            )
        if assumed("ambient_temperature_c"):
            items.append(
                RefinementOpportunity(
                    "ambient_temperature",
                    "medium",
                    "Heat-rejection conditions change minimum cooling work.",
                    "Climate-specific cooling factor",
                )
            )
    if technology:
        performance_name = technology.metadata.get("performance_parameter")
        if performance_name and assumed(str(performance_name)):
            items.append(
                RefinementOpportunity(
                    str(performance_name),
                    "high",
                    "Measured equipment performance narrows useful-output and destruction estimates.",
                    "Asset-specific process performance",
                )
            )
    if carrier and carrier.metadata.get("family") == "chemical":
        factor = parameters.get("input_exergy_factor") or parameters.get(
            "exergy_factor"
        )
        if factor and factor.is_assumed:
            items.append(
                RefinementOpportunity(
                    "fuel composition or chemical exergy factor",
                    "medium",
                    "Fuel composition and HHV/LHV basis affect chemical exergy.",
                    "Composition-specific carrier factor",
                )
            )
    priority_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(items, key=lambda item: (priority_order[item.priority], item.field))


def _strict_check(parameters: Iterable[tuple[str, Parameter]]) -> None:
    assumptions = [name for name, value in parameters if value.is_assumed]
    if assumptions:
        raise MissingInputError(
            "strict mode will not use assumed inputs; provide: "
            + ", ".join(sorted(assumptions))
        )


def _warn_published_estimates(
    warnings: list[str], parameters: Mapping[str, Parameter]
) -> None:
    for name, parameter in parameters.items():
        if parameter.status != ValueStatus.PUBLISHED_ESTIMATE:
            continue
        override_name = name if name in {"efficiency", "cop"} else "performance"
        warnings.append(
            f"{name} uses a published F1 screening estimate, not measured site "
            f"performance. Override it with {override_name}=... or "
            f"result.refine({override_name}=...)."
        )
        if parameter.selection_basis == "family_fallback":
            supplied = ", ".join(parameter.selection_context or {}) or "none"
            available = ", ".join(parameter.available_context or ())
            warnings.append(
                f"No conditional {name} prior matched the supplied estimate_context "
                f"({supplied}); the family fallback was used. For a narrower estimate, "
                f"provide applicable context fields: {available}."
            )
        elif parameter.estimate_variant:
            warnings.append(
                f"Selected published prior variant {parameter.estimate_variant!r} "
                "from estimate_context."
            )


def _used_source_catalog(
    registry: Registry, parameters: Mapping[str, Parameter]
) -> dict[str, Mapping[str, Any]]:
    source_ids = {
        item.source_id for item in parameters.values() if item.source_id is not None
    }
    return {
        source_id: dict(registry.sources[source_id])
        for source_id in sorted(source_ids)
        if source_id in registry.sources
    }


def assess(
    technology: str | None = None,
    service: str | None = None,
    carrier: str | None = None,
    energy: float | None = None,
    unit: str = "MWh",
    *,
    basis: str | None = None,
    source_temperature: float | str | None = None,
    return_temperature: float | str | None = None,
    ambient_temperature: float | str | None = None,
    cold_temperature: float | str | None = None,
    temperature_unit: str = "C",
    efficiency: float | None = None,
    cop: float | None = None,
    performance: float | None = None,
    exergy_factor: float | None = None,
    input_exergy_factor: float | None = None,
    output_exergy_factor: float | None = None,
    location: str | None = None,
    estimate_context: Mapping[str, Any] | None = None,
    strict: bool = False,
    registry: Registry | None = None,
) -> AssessmentResult:
    """Assess a stream or technology using the strongest available evidence.

    Missing energy produces a normalized result per 1 MWh of input. Defaults are
    never hidden: every assumed parameter is returned with provenance and ranges.
    """

    registry = registry or DEFAULT_REGISTRY
    if estimate_context is not None:
        if not isinstance(estimate_context, Mapping):
            raise ValueError("estimate_context must be an object")
        for context_name, context_value in estimate_context.items():
            if not str(context_name).strip():
                raise ValueError("estimate_context field names must not be empty")
            if isinstance(context_value, (int, float)) and not isinstance(
                context_value, bool
            ):
                if not math.isfinite(float(context_value)):
                    raise ValueError(
                        f"estimate_context {context_name!r} must be finite"
                    )
    if energy is not None and float(energy) < 0.0:
        raise ValueError("energy must be nonnegative")
    for label, value in (
        ("exergy_factor", exergy_factor),
        ("input_exergy_factor", input_exergy_factor),
        ("output_exergy_factor", output_exergy_factor),
    ):
        if value is not None and (
            not math.isfinite(float(value)) or float(value) < 0.0
        ):
            raise ValueError(f"{label} must be finite and nonnegative")
    if technology is not None and exergy_factor is not None:
        raise ValueError(
            "for a technology, use input_exergy_factor or output_exergy_factor "
            "to make the boundary explicit"
        )
    if technology is None:
        if efficiency is not None or cop is not None or performance is not None:
            raise ValueError(
                "efficiency, COP, and performance require a technology boundary; for a stream, "
                "provide an exergy factor instead"
            )
        factor_count = sum(
            value is not None
            for value in (exergy_factor, input_exergy_factor, output_exergy_factor)
        )
        if factor_count > 1:
            raise ValueError(
                "exergy_factor, input_exergy_factor, and output_exergy_factor are "
                "mutually exclusive for a stream assessment"
            )
    if sum(value is not None for value in (efficiency, cop, performance)) > 1:
        raise ValueError("efficiency, cop, and performance are mutually exclusive")
    explicit_basis: str | None = None
    if basis is not None:
        if not isinstance(basis, str) or basis.strip().upper() not in {"HHV", "LHV"}:
            raise ValueError("basis must be HHV or LHV")
        explicit_basis = basis.strip().upper()
    unit_basis = energy_basis(unit)
    if (
        explicit_basis is not None
        and unit_basis is not None
        and explicit_basis != unit_basis
    ):
        raise ValueError(
            f"explicit {explicit_basis} basis conflicts with typed unit {unit!r}"
        )
    resolved_basis = explicit_basis if explicit_basis is not None else unit_basis
    if (
        technology is None
        and (service is not None or output_exergy_factor is not None)
        and (carrier is not None or input_exergy_factor is not None)
    ):
        raise ValueError(
            "service/output and carrier/input factors describe different boundaries; "
            "assess one stream boundary or provide a technology"
        )
    request = {
        "technology": technology,
        "service": service,
        "carrier": carrier,
        "energy": energy,
        "unit": unit,
        "basis": basis,
        "source_temperature": source_temperature,
        "return_temperature": return_temperature,
        "ambient_temperature": ambient_temperature,
        "cold_temperature": cold_temperature,
        "temperature_unit": temperature_unit,
        "efficiency": efficiency,
        "cop": cop,
        "performance": performance,
        "exergy_factor": exergy_factor,
        "input_exergy_factor": input_exergy_factor,
        "output_exergy_factor": output_exergy_factor,
        "location": location,
        "estimate_context": dict(estimate_context) if estimate_context else None,
        "strict": strict,
        "registry": registry,
    }
    technology_profile = _resolve_named_profile(registry, "technology", technology)
    if (
        technology_profile
        and service is not None
        and technology_profile.metadata.get("output_carrier")
    ):
        raise ValueError(
            f"{technology_profile.label} has a fixed output carrier and cannot be "
            "combined with a service override; model the downstream conversion separately"
        )
    if technology_profile and service is None:
        service = technology_profile.metadata.get("default_service")
    service_profile = _resolve_named_profile(registry, "service", service)
    custom_stream_factor = technology_profile is None and exergy_factor is not None
    explicit_service_factor = output_exergy_factor is not None
    factor_controls_service_boundary = custom_stream_factor or explicit_service_factor

    if technology_profile and carrier is None:
        carrier = technology_profile.metadata.get("input_carrier")
    carrier_profile = (
        _select_basis_carrier(registry, carrier, resolved_basis) if carrier else None
    )
    if technology_profile and carrier_profile:
        default_carrier_id = technology_profile.metadata.get("input_carrier")
        default_carrier = (
            registry.get("carrier", str(default_carrier_id))
            if default_carrier_id
            else None
        )
        performance_field = technology_profile.metadata.get("performance_parameter")
        explicit_basis_performance = (
            performance
            if performance is not None
            else efficiency
            if performance_field == "efficiency"
            else cop
        )
        if (
            default_carrier is not None
            and carrier_profile.id != default_carrier.id
            and explicit_basis_performance is None
        ):
            raise ValueError(
                f"switching {technology_profile.label} input carrier from "
                f"{default_carrier.label} to {carrier_profile.label} requires an "
                f"explicit {performance_field} for the selected carrier and basis"
            )

    output_carrier_profile: Profile | None = None
    if technology_profile and technology_profile.metadata.get("output_carrier"):
        output_carrier_profile = registry.get(
            "carrier", str(technology_profile.metadata["output_carrier"])
        )

    parameters: dict[str, Parameter] = {}
    if location:
        parameters["location"] = _provided(location)
    if resolved_basis:
        parameters["basis"] = _provided(
            resolved_basis,
            note="explicit basis" if basis is not None else f"derived from {unit}",
        )

    if factor_controls_service_boundary:
        source_parameter = None
        ambient_parameter = None
        cold_parameter = None
        return_parameter = None
    else:
        source_parameter = _temperature_parameter(
            source_temperature,
            temperature_unit,
            "source_temperature_c",
            service_profile,
            registry.data_version,
        )
        ambient_parameter = _temperature_parameter(
            ambient_temperature,
            temperature_unit,
            "ambient_temperature_c",
            service_profile,
            registry.data_version,
        )
        cold_parameter = _temperature_parameter(
            cold_temperature,
            temperature_unit,
            "cold_temperature_c",
            service_profile,
            registry.data_version,
        )
        return_parameter = (
            _temperature_parameter(
                return_temperature,
                temperature_unit,
                "return_temperature_c",
                service_profile,
                registry.data_version,
            )
            if return_temperature is not None
            else None
        )
    for name, value in (
        ("source_temperature_c", source_parameter),
        ("return_temperature_c", return_parameter),
        ("ambient_temperature_c", ambient_parameter),
        ("cold_temperature_c", cold_parameter),
    ):
        if value is not None:
            parameters[name] = value

    performance_name = (
        str(technology_profile.metadata.get("performance_parameter"))
        if technology_profile
        and technology_profile.metadata.get("performance_parameter")
        else None
    )
    performance_parameter: Parameter | None = None
    explicit_performance = (
        performance
        if performance is not None
        else efficiency
        if performance_name == "efficiency"
        else cop
    )
    if performance_name:
        if performance_name == "efficiency" and cop is not None:
            raise ValueError(f"{technology_profile.label} uses efficiency, not COP")
        if performance_name == "cop" and efficiency is not None:
            raise ValueError(f"{technology_profile.label} uses COP, not efficiency")
        if performance_name not in {"efficiency", "cop"} and (
            efficiency is not None or cop is not None
        ):
            raise ValueError(
                f"{technology_profile.label} uses {performance_name}; provide it "
                "through the generic performance input"
            )
        if explicit_performance is not None:
            performance_parameter = _provided(
                float(explicit_performance), "dimensionless"
            )
        else:
            performance_parameter = technology_profile.parameter(
                performance_name,
                source_version=registry.data_version,
                context=estimate_context,
            )
        if performance_parameter:
            performance_value = float(performance_parameter.value)
            performance_low, performance_high = _parameter_range(performance_parameter)
            if not math.isfinite(performance_value) or performance_value < 0.0:
                raise ValueError(f"{performance_name} must be finite and nonnegative")
            if (
                performance_name == "efficiency"
                and max(performance_value, performance_high) > 1.0
            ):
                raise ValueError("efficiency and its upper bound must not exceed one")
            if performance_low < 0.0:
                raise ValueError(f"{performance_name} lower bound must be nonnegative")
            parameters[performance_name] = performance_parameter

    input_factor_parameter: Parameter | None = None
    if input_exergy_factor is not None:
        input_factor_parameter = _provided(float(input_exergy_factor), "MWh_ex/MWh")
    elif carrier_profile:
        input_factor_parameter = carrier_profile.parameter(
            "exergy_factor",
            status=ValueStatus.LOOKUP,
            source_version=registry.data_version,
        )
    if input_factor_parameter and technology_profile is not None:
        parameters["input_exergy_factor"] = input_factor_parameter

    service_factor: Estimate | None = None
    service_factor_uses_temperatures = False
    method_id = "assessment.insufficient-data.v1"
    warnings: list[str] = []
    if factor_controls_service_boundary and any(
        value is not None
        for value in (
            source_temperature,
            return_temperature,
            ambient_temperature,
            cold_temperature,
        )
    ):
        warnings.append(
            "Service-temperature inputs were ignored because an explicit exergy factor controls this boundary."
        )
    if output_exergy_factor is not None:
        service_factor = Estimate(
            float(output_exergy_factor),
            "MWh_ex/MWh",
            float(output_exergy_factor),
            float(output_exergy_factor),
        )
        parameters["output_exergy_factor"] = _provided(
            float(output_exergy_factor), "MWh_ex/MWh"
        )
        method_id = "output.custom-factor.v1"
    elif service_profile and not custom_stream_factor:
        service_factor, method_id, factor_warnings = _factor_from_service(
            service_profile, parameters
        )
        service_factor_uses_temperatures = service_factor is not None
        warnings.extend(factor_warnings)
    elif output_carrier_profile:
        output_parameter = output_carrier_profile.parameter(
            "exergy_factor",
            status=ValueStatus.LOOKUP,
            source_version=registry.data_version,
        )
        if output_parameter:
            parameters["output_exergy_factor"] = output_parameter
            service_factor = _estimate_from_parameter(output_parameter, "MWh_ex/MWh")
            method_id = "carrier.lookup.v1"

    direct_factor: Estimate | None = None
    service_family = service_profile.metadata.get("family") if service_profile else None
    temperature_model_inputs: set[str] = set()
    if service_factor_uses_temperatures and service_family == "thermal":
        temperature_model_inputs.update(
            {
                "source_temperature_c",
                "return_temperature_c",
                "ambient_temperature_c",
            }
        )
    elif service_factor_uses_temperatures and service_family == "cooling":
        temperature_model_inputs.update({"cold_temperature_c", "ambient_temperature_c"})

    if technology_profile is None:
        if exergy_factor is not None:
            parameter = _provided(float(exergy_factor), "MWh_ex/MWh")
            parameters["exergy_factor"] = parameter
            direct_factor = _estimate_from_parameter(parameter)
            method_id = "stream.custom-factor.v1"
        elif service_factor is not None:
            direct_factor = service_factor
        elif input_factor_parameter is not None:
            parameters["exergy_factor"] = input_factor_parameter
            direct_factor = _estimate_from_parameter(
                input_factor_parameter, "MWh_ex/MWh"
            )
            method_id = (
                "stream.custom-input-factor.v1"
                if input_exergy_factor is not None
                else "carrier.lookup.v1"
            )

    normalized = energy is None
    energy_mwh = 1.0 if energy is None else convert_energy(energy, unit, "MWh")
    energy_estimate = Estimate(
        energy_mwh,
        "MWh",
        energy_mwh,
        energy_mwh,
        "provided" if energy is not None else "normalized",
    )
    if energy is not None:
        parameters["energy"] = _provided(float(energy), unit)

    if technology_profile is None and direct_factor is None:
        missing = []
        if (
            technology is None
            and service is None
            and carrier is None
            and exergy_factor is None
        ):
            missing.append("technology, service, carrier, or exergy_factor")
        elif service_profile and service_factor is None:
            service_requirements = {
                "thermal": (
                    ("source_temperature_c", "source_temperature"),
                    ("ambient_temperature_c", "ambient_temperature"),
                ),
                "cooling": (
                    ("cold_temperature_c", "cold_temperature"),
                    ("ambient_temperature_c", "ambient_temperature"),
                ),
            }
            for parameter_name, input_name in service_requirements.get(
                str(service_profile.metadata.get("family")), ()
            ):
                if parameter_name not in parameters:
                    missing.append(input_name)
        subject = (
            service_profile.label
            if service_profile
            else carrier_profile.label
            if carrier_profile
            else "Unresolved exergy assessment"
        )
        return AssessmentResult(
            subject=subject,
            tier=FidelityTier.F0,
            method_id=method_id,
            registry_version=registry.data_version,
            parameters=parameters,
            carrier_id=carrier_profile.id if carrier_profile else None,
            input_energy=energy_estimate,
            normalized=normalized,
            warnings=warnings,
            missing=missing,
            source_catalog=_used_source_catalog(registry, parameters),
            request=request,
        )

    if technology_profile is None:
        stream_model_inputs = {"exergy_factor"}
        if method_id != "stream.custom-factor.v1":
            stream_model_inputs.update(temperature_model_inputs)
        if strict:
            _strict_check(
                (name, value)
                for name, value in parameters.items()
                if name in stream_model_inputs
            )
        accessible = _multiply(energy_estimate, direct_factor, unit="MWh_ex")
        stream_model_inputs.add("output_exergy_factor")
        tier = (
            FidelityTier.F2
            if any(
                parameter.status in {ValueStatus.PROVIDED, ValueStatus.MEASURED}
                for name, parameter in parameters.items()
                if name in stream_model_inputs
            )
            else FidelityTier.F1
        )
        result = AssessmentResult(
            subject=service_profile.label
            if service_profile
            else carrier_profile.label
            if carrier_profile
            else "Custom energy stream",
            tier=tier,
            method_id=method_id,
            registry_version=registry.data_version,
            parameters=parameters,
            carrier_id=carrier_profile.id if carrier_profile else None,
            exergy_factor=direct_factor,
            input_energy=energy_estimate,
            useful_energy=energy_estimate,
            useful_exergy=accessible,
            normalized=normalized,
            warnings=warnings,
            source_catalog=_used_source_catalog(registry, parameters),
            request=request,
        )
        result.refinements = _refinements(
            parameters,
            None if factor_controls_service_boundary else service_profile,
            carrier_profile,
            None,
        )
        return result

    if performance_parameter is None:
        raise MissingInputError(
            f"technology profile {technology_profile.id!r} has no performance parameter"
        )
    if input_factor_parameter is None:
        raise MissingInputError(
            "technology assessment requires an input carrier exergy factor"
        )
    if service_factor is None:
        raise MissingInputError(
            "technology assessment requires an output service or carrier factor"
        )

    performance = _estimate_from_parameter(performance_parameter, "dimensionless")
    input_factor = _estimate_from_parameter(input_factor_parameter, "MWh_ex/MWh")
    input_exergy = _multiply(energy_estimate, input_factor, unit="MWh_ex")
    useful_energy = _multiply(energy_estimate, performance, unit="MWh")
    useful_exergy = _multiply(useful_energy, service_factor, unit="MWh_ex")
    useful_exergy_per_input = _multiply(performance, service_factor, unit="MWh_ex/MWh")
    exergy_efficiency = _ratio(useful_exergy_per_input, input_factor)
    destroyed_or_lost = _difference(input_exergy, useful_exergy, "MWh_ex")
    if exergy_efficiency.value > 1.0 + 1e-12:
        raise ValueError(
            "the central assumptions imply product exergy greater than input exergy; "
            "check performance, carrier basis, and service temperatures"
        )
    if exergy_efficiency.high is not None and exergy_efficiency.high > 1.0:
        warnings.append(
            "The independent screening ranges permit an unphysical upper-bound combination; "
            "use site-specific performance and state data for a coupled bound."
        )
    if destroyed_or_lost.low is not None and destroyed_or_lost.low < 0.0:
        warnings.append(
            "The independent uncertainty bounds overlap an unphysical negative destruction value."
        )
    if strict:
        used_names = {
            "input_exergy_factor",
            "output_exergy_factor",
            performance_name,
        }
        used_names.update(temperature_model_inputs)
        _strict_check(
            (name, value) for name, value in parameters.items() if name in used_names
        )
    _warn_published_estimates(warnings, parameters)
    technology_model_inputs = {
        "input_exergy_factor",
        "output_exergy_factor",
        performance_name,
    }
    technology_model_inputs.update(temperature_model_inputs)
    explicit_model_inputs = [
        item
        for name, item in parameters.items()
        if name in technology_model_inputs
        and item.status in {ValueStatus.PROVIDED, ValueStatus.MEASURED}
    ]
    tier = FidelityTier.F2 if explicit_model_inputs else FidelityTier.F1
    result = AssessmentResult(
        subject=technology_profile.label,
        tier=tier,
        method_id=f"technology.{technology_profile.metadata.get('model', 'converter')}.v1+{method_id}",
        registry_version=registry.data_version,
        parameters=parameters,
        carrier_id=carrier_profile.id if carrier_profile else None,
        exergy_factor=service_factor,
        input_energy=energy_estimate,
        input_exergy=input_exergy,
        useful_energy=useful_energy,
        useful_exergy=useful_exergy,
        exergy_destroyed_or_lost=destroyed_or_lost,
        exergetic_efficiency=exergy_efficiency,
        normalized=normalized,
        warnings=warnings,
        source_catalog=_used_source_catalog(registry, parameters),
        request=request,
    )
    result.refinements = _refinements(
        parameters,
        None if explicit_service_factor else service_profile,
        carrier_profile,
        technology_profile,
    )
    return result
