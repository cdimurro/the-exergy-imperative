"""Composable energy/exergy accounting for arbitrary connected systems.

This module deliberately does not solve equipment performance.  It accounts for
user-supplied or profile-resolved flows around explicit component and system
boundaries.  Detailed simulators can therefore export their results into the
same small contract without making this package a competing process solver.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .balance import analyze_balance
from .models import BalanceResult, ExergyStream, FidelityTier
from .registry import DEFAULT_REGISTRY, Registry
from .units import convert_energy, exergy_unit_for

SYSTEM_COMPONENT_KINDS: tuple[str, ...] = (
    "source",
    "sink",
    "converter",
    "heater-cooler",
    "heat-exchanger",
    "mixer-splitter",
    "compressor-pump",
    "turbine-expander",
    "reactor-separator",
    "storage",
    "transport",
)
SYSTEM_FLOW_ROLES: tuple[str, ...] = ("resource", "internal", "product", "loss")


def _finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _identifier(value: Any, name: str) -> str:
    identifier = str(value).strip()
    if not identifier:
        raise ValueError(f"{name} must not be empty")
    return identifier


def _tier(value: Any, name: str = "tier") -> FidelityTier:
    try:
        return value if isinstance(value, FidelityTier) else FidelityTier(str(value))
    except ValueError as exc:
        raise ValueError(f"{name} must be F0, F1, F2, F3, or F4") from exc


def _minimum_tier(values: Iterable[FidelityTier]) -> FidelityTier:
    tiers = tuple(values)
    if not tiers:
        return FidelityTier.F0
    return min(tiers, key=lambda item: int(item.value[1:]))


@dataclass(frozen=True)
class SystemComponent:
    """One declared accounting boundary in a connected system."""

    id: str
    kind: str
    label: str | None = None
    technology: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SystemComponent":
        allowed = {"id", "kind", "label", "technology", "metadata"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError("unknown component fields: " + ", ".join(unknown))
        component_id = _identifier(payload.get("id"), "component id")
        kind = str(payload.get("kind", "converter")).strip().lower().replace("_", "-")
        if kind not in SYSTEM_COMPONENT_KINDS:
            raise ValueError(
                f"component {component_id!r} kind must be one of "
                + ", ".join(SYSTEM_COMPONENT_KINDS)
            )
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise ValueError(f"component {component_id!r} metadata must be an object")
        return cls(
            id=component_id,
            kind=kind,
            label=(str(payload["label"]) if payload.get("label") is not None else None),
            technology=(
                str(payload["technology"])
                if payload.get("technology") is not None
                else None
            ),
            metadata=dict(metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": self.id, "kind": self.kind}
        if self.label is not None:
            payload["label"] = self.label
        if self.technology is not None:
            payload["technology"] = self.technology
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True)
class SystemFlow:
    """An interval energy quantity and its exergy quality between boundaries."""

    id: str
    energy: float
    unit: str = "MWh"
    source: str | None = None
    target: str | None = None
    role: str | None = None
    carrier: str | None = None
    exergy: float | None = None
    exergy_factor: float | None = None
    tier: FidelityTier = FidelityTier.F2
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SystemFlow":
        allowed = {
            "id",
            "name",
            "energy",
            "unit",
            "source",
            "target",
            "role",
            "carrier",
            "exergy",
            "exergy_factor",
            "tier",
            "metadata",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError("unknown flow fields: " + ", ".join(unknown))
        flow_id = _identifier(payload.get("id", payload.get("name")), "flow id")
        if "energy" not in payload:
            raise ValueError(f"flow {flow_id!r} requires energy")
        energy = _finite(payload["energy"], f"flow {flow_id!r} energy")
        if energy < 0.0:
            raise ValueError(f"flow {flow_id!r} energy must be nonnegative")
        source = (
            _identifier(payload["source"], f"flow {flow_id!r} source")
            if payload.get("source") is not None
            else None
        )
        target = (
            _identifier(payload["target"], f"flow {flow_id!r} target")
            if payload.get("target") is not None
            else None
        )
        if source is None and target is None:
            raise ValueError(
                f"flow {flow_id!r} must cross at least one component boundary"
            )
        role = payload.get("role")
        if role is not None:
            role = str(role).strip().lower().replace("_", "-")
            if role not in SYSTEM_FLOW_ROLES:
                raise ValueError(
                    f"flow {flow_id!r} role must be one of "
                    + ", ".join(SYSTEM_FLOW_ROLES)
                )
        exergy = (
            _finite(payload["exergy"], f"flow {flow_id!r} exergy")
            if payload.get("exergy") is not None
            else None
        )
        if exergy is not None and exergy < 0.0:
            raise ValueError(f"flow {flow_id!r} exergy must be nonnegative")
        factor = (
            _finite(payload["exergy_factor"], f"flow {flow_id!r} exergy_factor")
            if payload.get("exergy_factor") is not None
            else None
        )
        if factor is not None and factor < 0.0:
            raise ValueError(f"flow {flow_id!r} exergy_factor must be nonnegative")
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise ValueError(f"flow {flow_id!r} metadata must be an object")
        return cls(
            id=flow_id,
            energy=energy,
            unit=str(payload.get("unit", "MWh")),
            source=source,
            target=target,
            role=role,
            carrier=(str(payload["carrier"]) if payload.get("carrier") else None),
            exergy=exergy,
            exergy_factor=factor,
            tier=_tier(payload.get("tier", "F2"), f"flow {flow_id!r} tier"),
            metadata=dict(metadata),
        )


@dataclass(frozen=True)
class SystemAccumulation:
    """A signed change retained inside a storage component during an interval."""

    component: str
    energy_change: float
    unit: str = "MWh"
    exergy_change: float | None = None
    exergy_factor: float | None = None
    carrier: str | None = None
    tier: FidelityTier = FidelityTier.F2
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SystemAccumulation":
        allowed = {
            "component",
            "energy_change",
            "unit",
            "exergy_change",
            "exergy_factor",
            "carrier",
            "tier",
            "metadata",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError("unknown accumulation fields: " + ", ".join(unknown))
        component = _identifier(payload.get("component"), "accumulation component")
        if "energy_change" not in payload:
            raise ValueError(f"accumulation for {component!r} requires energy_change")
        energy = _finite(
            payload["energy_change"], f"accumulation for {component!r} energy_change"
        )
        exergy = (
            _finite(
                payload["exergy_change"],
                f"accumulation for {component!r} exergy_change",
            )
            if payload.get("exergy_change") is not None
            else None
        )
        if exergy is not None and energy * exergy < 0.0:
            raise ValueError(
                f"accumulation for {component!r} energy and exergy changes "
                "must have the same sign"
            )
        factor = (
            _finite(
                payload["exergy_factor"],
                f"accumulation for {component!r} exergy_factor",
            )
            if payload.get("exergy_factor") is not None
            else None
        )
        if factor is not None and factor < 0.0:
            raise ValueError(
                f"accumulation for {component!r} exergy_factor must be nonnegative"
            )
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise ValueError(
                f"accumulation for {component!r} metadata must be an object"
            )
        return cls(
            component=component,
            energy_change=energy,
            unit=str(payload.get("unit", "MWh")),
            exergy_change=exergy,
            exergy_factor=factor,
            carrier=(str(payload["carrier"]) if payload.get("carrier") else None),
            tier=_tier(
                payload.get("tier", "F2"), f"accumulation for {component!r} tier"
            ),
            metadata=dict(metadata),
        )


@dataclass(frozen=True)
class ResolvedSystemFlow:
    id: str
    energy: float
    exergy: float
    unit: str
    source: str | None
    target: str | None
    role: str
    carrier: str | None
    exergy_factor: float
    factor_status: str
    tier: FidelityTier
    source_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "energy": self.energy,
            "exergy": self.exergy,
            "unit": self.unit,
            "exergy_unit": exergy_unit_for(self.unit),
            "source": self.source,
            "target": self.target,
            "role": self.role,
            "exergy_factor": self.exergy_factor,
            "factor_status": self.factor_status,
            "tier": self.tier.value,
        }
        if self.carrier is not None:
            payload["carrier"] = self.carrier
        if self.source_id is not None:
            payload["source_id"] = self.source_id
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True)
class ResolvedAccumulation:
    component: str
    energy_change: float
    exergy_change: float
    unit: str
    exergy_factor: float
    factor_status: str
    tier: FidelityTier
    carrier: str | None = None
    source_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "component": self.component,
            "energy_change": self.energy_change,
            "exergy_change": self.exergy_change,
            "unit": self.unit,
            "exergy_unit": exergy_unit_for(self.unit),
            "exergy_factor": self.exergy_factor,
            "factor_status": self.factor_status,
            "tier": self.tier.value,
        }
        if self.carrier is not None:
            payload["carrier"] = self.carrier
        if self.source_id is not None:
            payload["source_id"] = self.source_id
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True)
class EnergyBalanceResult:
    """First-law accounting without calling an untracked residual destruction."""

    name: str
    input_energy: float
    product_energy: float
    loss_energy: float
    accumulation_energy: float
    residual: float
    efficiency: float | None
    unit: str
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit,
            "input_energy": self.input_energy,
            "product_energy": self.product_energy,
            "loss_energy": self.loss_energy,
            "accumulation_energy": self.accumulation_energy,
            "residual": self.residual,
            "efficiency": self.efficiency,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ComponentAnalysisResult:
    component: SystemComponent
    energy: EnergyBalanceResult
    exergy: BalanceResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component.to_dict(),
            "energy": self.energy.to_dict(),
            "exergy": self.exergy.to_dict(),
        }


@dataclass(frozen=True)
class SystemAnalysisResult:
    name: str
    tier: FidelityTier
    unit: str
    components: tuple[ComponentAnalysisResult, ...]
    flows: tuple[ResolvedSystemFlow, ...]
    accumulations: tuple[ResolvedAccumulation, ...]
    energy: EnergyBalanceResult
    exergy: BalanceResult
    warnings: tuple[str, ...] = ()
    source_catalog: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "name": self.name,
            "tier": self.tier.value,
            "unit": self.unit,
            "components": [item.to_dict() for item in self.components],
            "flows": [item.to_dict() for item in self.flows],
            "accumulations": [item.to_dict() for item in self.accumulations],
            "energy": self.energy.to_dict(),
            "exergy": self.exergy.to_dict(),
            "warnings": list(self.warnings),
            "source_catalog": {
                key: dict(value) for key, value in self.source_catalog.items()
            },
        }


@dataclass(frozen=True)
class SystemTimeSeriesResult:
    name: str
    tier: FidelityTier
    unit: str
    record_count: int
    total_weight: float
    aggregate_energy: Mapping[str, Any]
    aggregate_exergy: Mapping[str, Any]
    component_totals: tuple[Mapping[str, Any], ...]
    snapshots: tuple[Mapping[str, Any], ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "name": self.name,
            "tier": self.tier.value,
            "unit": self.unit,
            "record_count": self.record_count,
            "total_weight": self.total_weight,
            "value_basis": "interval energy quantities",
            "aggregate_energy": dict(self.aggregate_energy),
            "aggregate_exergy": dict(self.aggregate_exergy),
            "component_totals": [dict(item) for item in self.component_totals],
            "snapshots": [dict(item) for item in self.snapshots],
            "warnings": list(self.warnings),
        }


def _role(flow: SystemFlow) -> str:
    if flow.role is not None:
        role = flow.role
    elif flow.source is None:
        role = "resource"
    elif flow.target is None:
        role = "product"
    else:
        role = "internal"
    if flow.source is None and role != "resource":
        raise ValueError(f"boundary input flow {flow.id!r} must have role 'resource'")
    if flow.target is None and role not in {"product", "loss"}:
        raise ValueError(
            f"boundary output flow {flow.id!r} must have role 'product' or 'loss'"
        )
    if flow.source is not None and flow.target is not None and role != "internal":
        raise ValueError(f"connected flow {flow.id!r} must have role 'internal'")
    return role


def _resolve_quality(
    *,
    name: str,
    energy: float,
    original_unit: str,
    unit: str,
    exergy: float | None,
    exergy_factor: float | None,
    carrier: str | None,
    declared_tier: FidelityTier,
    registry: Registry,
) -> tuple[float, float, str, FidelityTier, str | None, tuple[str, ...]]:
    converted_energy = convert_energy(energy, original_unit, unit)
    explicit_exergy = (
        convert_energy(exergy, original_unit, unit) if exergy is not None else None
    )
    warnings: list[str] = []
    source_id: str | None = None
    if explicit_exergy is not None:
        if converted_energy == 0.0:
            if explicit_exergy != 0.0:
                raise ValueError(f"{name} cannot have exergy when energy is zero")
            derived_factor = 0.0 if exergy_factor is None else exergy_factor
        else:
            derived_factor = explicit_exergy / converted_energy
        if exergy_factor is not None and not math.isclose(
            explicit_exergy,
            converted_energy * exergy_factor,
            rel_tol=1e-9,
            abs_tol=1e-12,
        ):
            raise ValueError(
                f"{name} exergy conflicts with energy multiplied by exergy_factor"
            )
        return (
            explicit_exergy,
            derived_factor,
            "provided-exergy",
            declared_tier,
            None,
            (),
        )
    if exergy_factor is not None:
        if carrier is not None and registry.find("carrier", carrier) is not None:
            warnings.append(
                f"{name} uses the provided exergy factor instead of the carrier profile."
            )
        return (
            converted_energy * exergy_factor,
            exergy_factor,
            "provided-factor",
            declared_tier,
            None,
            tuple(warnings),
        )
    if carrier is None:
        raise ValueError(
            f"{name} requires exergy, exergy_factor, or a carrier with a factor"
        )
    profile = registry.get("carrier", carrier)
    parameter = profile.parameter("exergy_factor", source_version=registry.data_version)
    if parameter is None:
        raise ValueError(
            f"carrier {profile.id!r} has no exergy_factor; provide one explicitly"
        )
    factor = _finite(parameter.value, f"carrier {profile.id!r} exergy_factor")
    if factor < 0.0:
        raise ValueError(f"carrier {profile.id!r} exergy_factor must be nonnegative")
    source_id = profile.source_id
    warnings.append(
        f"{name} uses the {profile.label} profile factor; it is not a measurement."
    )
    return (
        converted_energy * factor,
        factor,
        "profile",
        FidelityTier.F1,
        source_id,
        tuple(warnings),
    )


def _resolve_flow(
    flow: SystemFlow, unit: str, registry: Registry
) -> tuple[ResolvedSystemFlow, tuple[str, ...]]:
    exergy, factor, status, tier, source_id, warnings = _resolve_quality(
        name=f"flow {flow.id!r}",
        energy=flow.energy,
        original_unit=flow.unit,
        unit=unit,
        exergy=flow.exergy,
        exergy_factor=flow.exergy_factor,
        carrier=flow.carrier,
        declared_tier=flow.tier,
        registry=registry,
    )
    return (
        ResolvedSystemFlow(
            id=flow.id,
            energy=convert_energy(flow.energy, flow.unit, unit),
            exergy=exergy,
            unit=unit,
            source=flow.source,
            target=flow.target,
            role=_role(flow),
            carrier=flow.carrier,
            exergy_factor=factor,
            factor_status=status,
            tier=tier,
            source_id=source_id,
            metadata=flow.metadata,
        ),
        warnings,
    )


def _resolve_accumulation(
    accumulation: SystemAccumulation, unit: str, registry: Registry
) -> tuple[ResolvedAccumulation, tuple[str, ...]]:
    sign = -1.0 if accumulation.energy_change < 0.0 else 1.0
    magnitude = abs(accumulation.energy_change)
    explicit_exergy = (
        abs(accumulation.exergy_change)
        if accumulation.exergy_change is not None
        else None
    )
    exergy, factor, status, tier, source_id, warnings = _resolve_quality(
        name=f"accumulation for {accumulation.component!r}",
        energy=magnitude,
        original_unit=accumulation.unit,
        unit=unit,
        exergy=explicit_exergy,
        exergy_factor=accumulation.exergy_factor,
        carrier=accumulation.carrier,
        declared_tier=accumulation.tier,
        registry=registry,
    )
    return (
        ResolvedAccumulation(
            component=accumulation.component,
            energy_change=convert_energy(
                accumulation.energy_change, accumulation.unit, unit
            ),
            exergy_change=sign * exergy,
            unit=unit,
            exergy_factor=factor,
            factor_status=status,
            tier=tier,
            carrier=accumulation.carrier,
            source_id=source_id,
            metadata=accumulation.metadata,
        ),
        warnings,
    )


def _energy_balance(
    name: str,
    *,
    inputs: Sequence[float],
    products: Sequence[float],
    losses: Sequence[float],
    accumulation: float,
    unit: str,
    tolerance: float,
) -> EnergyBalanceResult:
    input_total = sum(inputs) + max(-accumulation, 0.0)
    product_total = sum(products) + max(accumulation, 0.0)
    loss_total = sum(losses)
    residual = input_total - product_total - loss_total
    warnings: list[str] = []
    if abs(residual) > tolerance:
        warnings.append(
            f"The declared energy balance does not close; untracked residual is "
            f"{residual:.6g} {unit}. Energy residual is not energy destruction."
        )
    efficiency = product_total / input_total if input_total > 0.0 else None
    return EnergyBalanceResult(
        name=name,
        input_energy=input_total,
        product_energy=product_total,
        loss_energy=loss_total,
        accumulation_energy=accumulation,
        residual=residual,
        efficiency=efficiency,
        unit=unit,
        warnings=tuple(warnings),
    )


def _exergy_balance(
    name: str,
    *,
    inputs: Sequence[ResolvedSystemFlow],
    products: Sequence[ResolvedSystemFlow],
    losses: Sequence[ResolvedSystemFlow],
    accumulation: float,
    unit: str,
    tolerance: float,
) -> BalanceResult:
    exergy_unit = exergy_unit_for(unit)
    input_streams = [
        ExergyStream(item.id, item.exergy, unit=exergy_unit) for item in inputs
    ]
    product_streams = [
        ExergyStream(item.id, item.exergy, unit=exergy_unit) for item in products
    ]
    loss_streams = [
        ExergyStream(item.id, item.exergy, unit=exergy_unit) for item in losses
    ]
    if accumulation < 0.0:
        input_streams.append(
            ExergyStream("released stored exergy", -accumulation, unit=exergy_unit)
        )
    elif accumulation > 0.0:
        product_streams.append(
            ExergyStream("stored exergy increase", accumulation, unit=exergy_unit)
        )
    return analyze_balance(
        name,
        inputs=input_streams,
        products=product_streams,
        losses=loss_streams,
        unit=exergy_unit,
        tolerance=tolerance,
    )


def analyze_system(
    name: str,
    *,
    components: Iterable[SystemComponent | Mapping[str, Any]],
    flows: Iterable[SystemFlow | Mapping[str, Any]],
    accumulations: Iterable[SystemAccumulation | Mapping[str, Any]] = (),
    unit: str = "MWh",
    tolerance: float = 1e-9,
    registry: Registry | None = None,
) -> SystemAnalysisResult:
    """Account for a connected system from explicit interval energy flows.

    ``flows`` are interval energy quantities, not power measurements.  Exergy is
    either supplied directly, calculated from an explicit factor, or resolved
    from a carrier profile.  Positive accumulation retains energy/exergy inside
    storage; negative accumulation releases it.
    """

    system_name = _identifier(name, "system name")
    tolerance = _finite(tolerance, "tolerance")
    if tolerance < 0.0:
        raise ValueError("tolerance must be nonnegative")
    registry = registry or DEFAULT_REGISTRY
    component_items = tuple(
        item if isinstance(item, SystemComponent) else SystemComponent.from_dict(item)
        for item in components
    )
    if not component_items:
        raise ValueError("at least one system component is required")
    component_index = {item.id: item for item in component_items}
    if len(component_index) != len(component_items):
        raise ValueError("system component ids must be unique")
    flow_items = tuple(
        item if isinstance(item, SystemFlow) else SystemFlow.from_dict(item)
        for item in flows
    )
    if not flow_items:
        raise ValueError("at least one system flow is required")
    if len({item.id for item in flow_items}) != len(flow_items):
        raise ValueError("system flow ids must be unique")
    for item in flow_items:
        if item.source is not None and item.source not in component_index:
            raise ValueError(
                f"flow {item.id!r} references unknown source {item.source!r}"
            )
        if item.target is not None and item.target not in component_index:
            raise ValueError(
                f"flow {item.id!r} references unknown target {item.target!r}"
            )
        if item.source is not None and item.source == item.target:
            raise ValueError(f"flow {item.id!r} cannot connect a component to itself")
    accumulation_items = tuple(
        item
        if isinstance(item, SystemAccumulation)
        else SystemAccumulation.from_dict(item)
        for item in accumulations
    )
    if len({item.component for item in accumulation_items}) != len(accumulation_items):
        raise ValueError("only one accumulation may be declared per component")
    for item in accumulation_items:
        component = component_index.get(item.component)
        if component is None:
            raise ValueError(
                f"accumulation references unknown component {item.component!r}"
            )
        if component.kind != "storage":
            raise ValueError(
                f"accumulation component {item.component!r} must have kind 'storage'"
            )

    warning_items: list[str] = []
    resolved_flows_list: list[ResolvedSystemFlow] = []
    for item in flow_items:
        resolved, item_warnings = _resolve_flow(item, unit, registry)
        resolved_flows_list.append(resolved)
        warning_items.extend(item_warnings)
    resolved_flows = tuple(resolved_flows_list)
    resolved_accumulations_list: list[ResolvedAccumulation] = []
    for item in accumulation_items:
        resolved, item_warnings = _resolve_accumulation(item, unit, registry)
        resolved_accumulations_list.append(resolved)
        warning_items.extend(item_warnings)
    resolved_accumulations = tuple(resolved_accumulations_list)
    accumulation_index = {item.component: item for item in resolved_accumulations}

    component_results: list[ComponentAnalysisResult] = []
    for component in component_items:
        incoming = tuple(item for item in resolved_flows if item.target == component.id)
        outgoing = tuple(item for item in resolved_flows if item.source == component.id)
        accumulation = accumulation_index.get(component.id)
        if not incoming and not outgoing and accumulation is None:
            inactive_energy = EnergyBalanceResult(
                name=component.label or component.id,
                input_energy=0.0,
                product_energy=0.0,
                loss_energy=0.0,
                accumulation_energy=0.0,
                residual=0.0,
                efficiency=None,
                unit=unit,
            )
            inactive_exergy = BalanceResult(
                name=component.label or component.id,
                input_exergy=0.0,
                product_exergy=0.0,
                loss_exergy=0.0,
                destruction_exergy=0.0,
                residual=0.0,
                exergetic_efficiency=None,
                unit=exergy_unit_for(unit),
                inferred_destruction=True,
            )
            component_results.append(
                ComponentAnalysisResult(component, inactive_energy, inactive_exergy)
            )
            warning_items.append(
                f"{component.id}: component is inactive in this accounting interval."
            )
            continue
        if not incoming and not (
            component.kind == "storage"
            and accumulation is not None
            and accumulation.energy_change < 0.0
        ):
            raise ValueError(f"component {component.id!r} has no input flow")
        if not outgoing and component.kind != "storage":
            raise ValueError(f"component {component.id!r} has no output flow")
        products = tuple(item for item in outgoing if item.role != "loss")
        losses = tuple(item for item in outgoing if item.role == "loss")
        energy_change = accumulation.energy_change if accumulation else 0.0
        exergy_change = accumulation.exergy_change if accumulation else 0.0
        energy_balance = _energy_balance(
            component.label or component.id,
            inputs=[item.energy for item in incoming],
            products=[item.energy for item in products],
            losses=[item.energy for item in losses],
            accumulation=energy_change,
            unit=unit,
            tolerance=tolerance,
        )
        exergy_balance = _exergy_balance(
            component.label or component.id,
            inputs=incoming,
            products=products,
            losses=losses,
            accumulation=exergy_change,
            unit=unit,
            tolerance=tolerance,
        )
        component_results.append(
            ComponentAnalysisResult(component, energy_balance, exergy_balance)
        )
        warning_items.extend(
            f"{component.id}: {message}" for message in energy_balance.warnings
        )
        warning_items.extend(
            f"{component.id}: {message}" for message in exergy_balance.warnings
        )

    boundary_inputs = tuple(item for item in resolved_flows if item.source is None)
    boundary_products = tuple(
        item
        for item in resolved_flows
        if item.target is None and item.role == "product"
    )
    boundary_losses = tuple(
        item for item in resolved_flows if item.target is None and item.role == "loss"
    )
    total_energy_change = sum(item.energy_change for item in resolved_accumulations)
    total_exergy_change = sum(item.exergy_change for item in resolved_accumulations)
    system_energy = _energy_balance(
        system_name,
        inputs=[item.energy for item in boundary_inputs],
        products=[item.energy for item in boundary_products],
        losses=[item.energy for item in boundary_losses],
        accumulation=total_energy_change,
        unit=unit,
        tolerance=tolerance,
    )
    system_exergy = _exergy_balance(
        system_name,
        inputs=boundary_inputs,
        products=boundary_products,
        losses=boundary_losses,
        accumulation=total_exergy_change,
        unit=unit,
        tolerance=tolerance,
    )
    warning_items.extend(system_energy.warnings)
    warning_items.extend(system_exergy.warnings)
    component_destruction = sum(
        item.exergy.destruction_exergy for item in component_results
    )
    if not math.isclose(
        component_destruction,
        system_exergy.destruction_exergy,
        rel_tol=1e-9,
        abs_tol=tolerance,
    ):
        warning_items.append(
            "Component exergy destruction does not reconcile with the whole-system "
            "boundary; inspect component residuals, storage changes, and internal flows."
        )
    if (
        boundary_inputs
        and boundary_products
        and all(item.carrier == "electricity" for item in boundary_inputs)
        and all(item.carrier == "electricity" for item in boundary_products)
    ):
        warning_items.append(
            "At an electricity-to-electricity boundary, exergy equals energy; "
            "the additional value is loss, impact, and economic accounting."
        )
    used_source_ids = {
        item.source_id
        for item in (*resolved_flows, *resolved_accumulations)
        if item.source_id is not None
    }
    source_catalog = {
        source_id: dict(registry.sources[source_id])
        for source_id in sorted(used_source_ids)
        if source_id in registry.sources
    }
    tiers = [item.tier for item in (*resolved_flows, *resolved_accumulations)]
    return SystemAnalysisResult(
        name=system_name,
        tier=_minimum_tier(tiers),
        unit=unit,
        components=tuple(component_results),
        flows=resolved_flows,
        accumulations=resolved_accumulations,
        energy=system_energy,
        exergy=system_exergy,
        warnings=tuple(dict.fromkeys(warning_items)),
        source_catalog=source_catalog,
    )


def analyze_system_definition(
    payload: Mapping[str, Any], *, registry: Registry | None = None
) -> SystemAnalysisResult:
    """Analyze the JSON-shaped system-definition contract."""

    allowed = {
        "name",
        "components",
        "flows",
        "accumulations",
        "unit",
        "tolerance",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError("unknown system-definition fields: " + ", ".join(unknown))
    return analyze_system(
        str(payload.get("name", "system")),
        components=payload.get("components", ()),
        flows=payload.get("flows", ()),
        accumulations=payload.get("accumulations", ()),
        unit=str(payload.get("unit", "MWh")),
        tolerance=payload.get("tolerance", 1e-9),
        registry=registry,
    )


def _weighted_balance(
    results: Sequence[tuple[float, EnergyBalanceResult | BalanceResult]],
    *,
    exergy: bool,
    unit: str,
    accumulations: Sequence[tuple[float, float]] = (),
) -> dict[str, Any]:
    if exergy:
        changes = [value for _, value in accumulations]
        if changes and len(changes) != len(results):
            raise ValueError("weighted exergy accumulations must match results")
        if not changes:
            changes = [0.0] * len(results)
        external_input = sum(
            weight * (item.input_exergy - max(-change, 0.0))
            for (weight, item), change in zip(results, changes, strict=True)
        )
        external_product = sum(
            weight * (item.product_exergy - max(change, 0.0))
            for (weight, item), change in zip(results, changes, strict=True)
        )
        net_accumulation = sum(
            weight * change
            for (weight, _), change in zip(results, changes, strict=True)
        )
        input_total = external_input + max(-net_accumulation, 0.0)
        product_total = external_product + max(net_accumulation, 0.0)
        loss_total = sum(weight * item.loss_exergy for weight, item in results)
        destruction_total = sum(
            weight * item.destruction_exergy for weight, item in results
        )
        residual = sum(weight * item.residual for weight, item in results)
        return {
            "unit": exergy_unit_for(unit),
            "input_exergy": input_total,
            "product_exergy": product_total,
            "loss_exergy": loss_total,
            "destruction_exergy": destruction_total,
            "accumulation_exergy": net_accumulation,
            "residual": residual,
            "exergetic_efficiency": (
                product_total / input_total if input_total > 0.0 else None
            ),
        }
    external_input = sum(
        weight * (item.input_energy - max(-item.accumulation_energy, 0.0))
        for weight, item in results
    )
    external_product = sum(
        weight * (item.product_energy - max(item.accumulation_energy, 0.0))
        for weight, item in results
    )
    loss_total = sum(weight * item.loss_energy for weight, item in results)
    accumulation = sum(weight * item.accumulation_energy for weight, item in results)
    input_total = external_input + max(-accumulation, 0.0)
    product_total = external_product + max(accumulation, 0.0)
    residual = sum(weight * item.residual for weight, item in results)
    return {
        "unit": unit,
        "input_energy": input_total,
        "product_energy": product_total,
        "loss_energy": loss_total,
        "accumulation_energy": accumulation,
        "residual": residual,
        "efficiency": product_total / input_total if input_total > 0.0 else None,
    }


def analyze_system_timeseries(
    name: str,
    *,
    components: Iterable[SystemComponent | Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
    unit: str = "MWh",
    tolerance: float = 1e-9,
    registry: Registry | None = None,
    include_snapshots: bool = True,
) -> SystemTimeSeriesResult:
    """Aggregate chronological system records containing interval quantities.

    Each record requires ``timestamp`` and ``flows``.  ``weight`` can make a
    representative interval count multiple times.  ``duration_hours`` is
    retained as metadata only; values are never silently interpreted as power.
    """

    component_items = tuple(
        item if isinstance(item, SystemComponent) else SystemComponent.from_dict(item)
        for item in components
    )
    if not records:
        raise ValueError("system time series requires at least one record")
    seen_timestamps: set[str] = set()
    analyses: list[tuple[float, str, float | None, SystemAnalysisResult]] = []
    warning_items: list[str] = [
        "Time-series flow values are interval energy quantities, not power; "
        "duration_hours is metadata and does not rescale them."
    ]
    for index, record in enumerate(records):
        allowed = {
            "timestamp",
            "weight",
            "duration_hours",
            "flows",
            "accumulations",
        }
        unknown = sorted(set(record) - allowed)
        if unknown:
            raise ValueError(
                f"unknown time-series record fields at index {index}: "
                + ", ".join(unknown)
            )
        timestamp = _identifier(record.get("timestamp"), f"record {index} timestamp")
        if timestamp in seen_timestamps:
            raise ValueError(f"duplicate time-series timestamp {timestamp!r}")
        seen_timestamps.add(timestamp)
        weight = _finite(record.get("weight", 1.0), f"record {index} weight")
        if weight <= 0.0:
            raise ValueError(f"record {index} weight must be positive")
        duration = record.get("duration_hours")
        if duration is not None:
            duration = _finite(duration, f"record {index} duration_hours")
            if duration <= 0.0:
                raise ValueError(f"record {index} duration_hours must be positive")
        result = analyze_system(
            f"{name} @ {timestamp}",
            components=component_items,
            flows=record.get("flows", ()),
            accumulations=record.get("accumulations", ()),
            unit=unit,
            tolerance=tolerance,
            registry=registry,
        )
        analyses.append((weight, timestamp, duration, result))
    energy_results = [(weight, item.energy) for weight, _, _, item in analyses]
    exergy_results = [(weight, item.exergy) for weight, _, _, item in analyses]
    system_exergy_accumulations = [
        (weight, sum(item.exergy_change for item in result.accumulations))
        for weight, _, _, result in analyses
    ]
    component_totals: list[Mapping[str, Any]] = []
    for component in component_items:
        selected = [
            (
                weight,
                next(
                    item
                    for item in result.components
                    if item.component.id == component.id
                ),
            )
            for weight, _, _, result in analyses
        ]
        component_exergy_accumulations = [
            (
                weight,
                next(
                    (
                        accumulation.exergy_change
                        for accumulation in result.accumulations
                        if accumulation.component == component.id
                    ),
                    0.0,
                ),
            )
            for weight, _, _, result in analyses
        ]
        component_totals.append(
            {
                "component": component.to_dict(),
                "energy": _weighted_balance(
                    [(weight, item.energy) for weight, item in selected],
                    exergy=False,
                    unit=unit,
                ),
                "exergy": _weighted_balance(
                    [(weight, item.exergy) for weight, item in selected],
                    exergy=True,
                    unit=unit,
                    accumulations=component_exergy_accumulations,
                ),
            }
        )
    snapshots: list[Mapping[str, Any]] = []
    for weight, timestamp, duration, result in analyses:
        snapshot: dict[str, Any] = {
            "timestamp": timestamp,
            "weight": weight,
            "tier": result.tier.value,
            "energy": result.energy.to_dict(),
            "exergy": result.exergy.to_dict(),
            "warnings": list(result.warnings),
        }
        if duration is not None:
            snapshot["duration_hours"] = duration
        if include_snapshots:
            snapshot["analysis"] = result.to_dict()
        snapshots.append(snapshot)
        warning_items.extend(result.warnings)
    return SystemTimeSeriesResult(
        name=_identifier(name, "system time-series name"),
        tier=_minimum_tier(item.tier for _, _, _, item in analyses),
        unit=unit,
        record_count=len(analyses),
        total_weight=sum(weight for weight, _, _, _ in analyses),
        aggregate_energy=_weighted_balance(energy_results, exergy=False, unit=unit),
        aggregate_exergy=_weighted_balance(
            exergy_results,
            exergy=True,
            unit=unit,
            accumulations=system_exergy_accumulations,
        ),
        component_totals=tuple(component_totals),
        snapshots=tuple(snapshots),
        warnings=tuple(dict.fromkeys(warning_items)),
    )


def analyze_system_timeseries_definition(
    payload: Mapping[str, Any], *, registry: Registry | None = None
) -> SystemTimeSeriesResult:
    """Analyze the JSON-shaped chronological system contract."""

    allowed = {
        "name",
        "components",
        "records",
        "unit",
        "tolerance",
        "include_snapshots",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError("unknown system-time-series fields: " + ", ".join(unknown))
    return analyze_system_timeseries(
        str(payload.get("name", "system time series")),
        components=payload.get("components", ()),
        records=payload.get("records", ()),
        unit=str(payload.get("unit", "MWh")),
        tolerance=payload.get("tolerance", 1e-9),
        registry=registry,
        include_snapshots=bool(payload.get("include_snapshots", True)),
    )
