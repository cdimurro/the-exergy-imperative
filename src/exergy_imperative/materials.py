"""Mass, composition, and chemical-exergy accounting for material systems.

Material balances are intentionally separate from energy balances.  Chemical
exergy is reported only when every relevant stream has an explicit factor, and
an unreconciled chemical-exergy residual is never labeled destruction without
the accompanying heat, work, and reaction model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .models import FidelityTier
from .systems import SYSTEM_FLOW_ROLES, SystemComponent

MATERIAL_BALANCE_SCHEMA_VERSION = "1.0"
SUPPORTED_MASS_UNITS: tuple[str, ...] = (
    "kg",
    "g",
    "t",
    "tonne",
    "lb",
    "short-ton",
)
_KG_PER_UNIT = {
    "kg": 1.0,
    "g": 0.001,
    "t": 1000.0,
    "tonne": 1000.0,
    "lb": 0.45359237,
    "short-ton": 907.18474,
}


def _text(value: Any, name: str) -> str:
    result = str(value).strip()
    if not result:
        raise ValueError(f"{name} must not be empty")
    return result


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _mass_kg(value: Any, unit: str, name: str) -> float:
    key = unit.strip().lower().replace("_", "-")
    try:
        factor = _KG_PER_UNIT[key]
    except KeyError as exc:
        raise ValueError(
            f"{name} unit must be one of {', '.join(SUPPORTED_MASS_UNITS)}"
        ) from exc
    return _number(value, name) * factor


def convert_mass(value: Any, from_unit: str, to_unit: str = "kg") -> float:
    """Convert a finite mass without changing material or composition basis."""

    mass_kg = _mass_kg(value, from_unit, "mass")
    key = str(to_unit).strip().lower().replace("_", "-")
    try:
        factor = _KG_PER_UNIT[key]
    except KeyError as exc:
        raise ValueError(
            f"mass unit must be one of {', '.join(SUPPORTED_MASS_UNITS)}"
        ) from exc
    return mass_kg / factor


def _tier(value: Any, name: str) -> FidelityTier:
    try:
        return value if isinstance(value, FidelityTier) else FidelityTier(str(value))
    except ValueError as exc:
        raise ValueError(f"{name} must be F0, F1, F2, F3, or F4") from exc


def _minimum_tier(items: Iterable[FidelityTier]) -> FidelityTier:
    values = tuple(items)
    if not values:
        return FidelityTier.F0
    return min(values, key=lambda item: int(item.value[1:]))


def _composition(raw: Any, material: str | None, *, name: str) -> Mapping[str, float]:
    if raw is None:
        if material is None:
            raise ValueError(f"{name} requires material or composition")
        return {material: 1.0}
    if not isinstance(raw, Mapping) or not raw:
        raise ValueError(f"{name} composition must be a non-empty object")
    result: dict[str, float] = {}
    for constituent, fraction in raw.items():
        key = _text(constituent, f"{name} constituent")
        value = _number(fraction, f"{name} composition[{key!r}]")
        if not 0.0 <= value <= 1.0:
            raise ValueError(
                f"{name} composition fractions must be between zero and one"
            )
        result[key] = value
    if not math.isclose(sum(result.values()), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"{name} composition fractions must sum to one")
    return result


def _role(
    source: str | None, target: str | None, declared: str | None, name: str
) -> str:
    role = (
        declared.strip().lower().replace("_", "-")
        if declared is not None
        else "resource"
        if source is None
        else "product"
        if target is None
        else "internal"
    )
    if role not in SYSTEM_FLOW_ROLES:
        raise ValueError(f"{name} role must be one of {', '.join(SYSTEM_FLOW_ROLES)}")
    if source is None and role != "resource":
        raise ValueError(f"boundary input {name} must have role 'resource'")
    if target is None and role not in {"product", "loss"}:
        raise ValueError(f"boundary output {name} must have role 'product' or 'loss'")
    if source is not None and target is not None and role != "internal":
        raise ValueError(f"connected {name} must have role 'internal'")
    return role


@dataclass(frozen=True)
class MaterialStream:
    """A mass stream with an explicit composition and optional chemical exergy."""

    id: str
    mass: float
    material: str | None = None
    unit: str = "kg"
    source: str | None = None
    target: str | None = None
    role: str | None = None
    composition: Mapping[str, float] = field(default_factory=dict)
    specific_chemical_exergy_mj_per_kg: float | None = None
    tier: FidelityTier = FidelityTier.F2
    source_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MaterialStream":
        allowed = {
            "id",
            "name",
            "mass",
            "material",
            "unit",
            "source",
            "target",
            "role",
            "composition",
            "specific_chemical_exergy_mj_per_kg",
            "tier",
            "source_id",
            "metadata",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError("unknown material-stream fields: " + ", ".join(unknown))
        stream_id = _text(payload.get("id", payload.get("name")), "material-stream id")
        if "mass" not in payload:
            raise ValueError(f"material stream {stream_id!r} requires mass")
        mass = _number(payload["mass"], f"material stream {stream_id!r} mass")
        if mass < 0.0:
            raise ValueError(f"material stream {stream_id!r} mass must be nonnegative")
        material = (
            _text(payload["material"], f"material stream {stream_id!r} material")
            if payload.get("material") is not None
            else None
        )
        source = (
            _text(payload["source"], f"material stream {stream_id!r} source")
            if payload.get("source") is not None
            else None
        )
        target = (
            _text(payload["target"], f"material stream {stream_id!r} target")
            if payload.get("target") is not None
            else None
        )
        if source is None and target is None:
            raise ValueError(
                f"material stream {stream_id!r} must cross a component boundary"
            )
        factor = payload.get("specific_chemical_exergy_mj_per_kg")
        if factor is not None:
            factor = _number(factor, f"material stream {stream_id!r} chemical exergy")
            if factor < 0.0:
                raise ValueError("specific chemical exergy must be nonnegative")
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise ValueError(
                f"material stream {stream_id!r} metadata must be an object"
            )
        return cls(
            id=stream_id,
            mass=mass,
            material=material,
            unit=str(payload.get("unit", "kg")),
            source=source,
            target=target,
            role=(str(payload["role"]) if payload.get("role") is not None else None),
            composition=_composition(
                payload.get("composition"),
                material,
                name=f"material stream {stream_id!r}",
            ),
            specific_chemical_exergy_mj_per_kg=factor,
            tier=_tier(
                payload.get("tier", "F2"), f"material stream {stream_id!r} tier"
            ),
            source_id=(str(payload["source_id"]) if payload.get("source_id") else None),
            metadata=dict(metadata),
        )


@dataclass(frozen=True)
class MaterialAccumulation:
    component: str
    mass_change: float
    material: str | None = None
    unit: str = "kg"
    composition: Mapping[str, float] = field(default_factory=dict)
    specific_chemical_exergy_mj_per_kg: float | None = None
    tier: FidelityTier = FidelityTier.F2
    source_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MaterialAccumulation":
        allowed = {
            "component",
            "mass_change",
            "material",
            "unit",
            "composition",
            "specific_chemical_exergy_mj_per_kg",
            "tier",
            "source_id",
            "metadata",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(
                "unknown material-accumulation fields: " + ", ".join(unknown)
            )
        component = _text(payload.get("component"), "material accumulation component")
        if "mass_change" not in payload:
            raise ValueError(
                f"material accumulation for {component!r} requires mass_change"
            )
        material = (
            _text(payload["material"], f"material accumulation {component!r} material")
            if payload.get("material") is not None
            else None
        )
        factor = payload.get("specific_chemical_exergy_mj_per_kg")
        if factor is not None:
            factor = _number(
                factor, f"material accumulation {component!r} chemical exergy"
            )
            if factor < 0.0:
                raise ValueError("specific chemical exergy must be nonnegative")
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise ValueError("material accumulation metadata must be an object")
        return cls(
            component=component,
            mass_change=_number(payload["mass_change"], "mass_change"),
            material=material,
            unit=str(payload.get("unit", "kg")),
            composition=_composition(
                payload.get("composition"),
                material,
                name=f"material accumulation {component!r}",
            ),
            specific_chemical_exergy_mj_per_kg=factor,
            tier=_tier(
                payload.get("tier", "F2"), f"material accumulation {component!r} tier"
            ),
            source_id=(str(payload["source_id"]) if payload.get("source_id") else None),
            metadata=dict(metadata),
        )


@dataclass(frozen=True)
class ResolvedMaterialStream:
    id: str
    mass_kg: float
    material: str | None
    source: str | None
    target: str | None
    role: str
    composition: Mapping[str, float]
    constituent_masses_kg: Mapping[str, float]
    chemical_exergy_mwh: float | None
    specific_chemical_exergy_mj_per_kg: float | None
    tier: FidelityTier
    source_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "material": self.material,
            "mass": self.mass_kg,
            "unit": "kg",
            "source": self.source,
            "target": self.target,
            "role": self.role,
            "composition": dict(self.composition),
            "constituent_masses_kg": dict(self.constituent_masses_kg),
            "specific_chemical_exergy_mj_per_kg": self.specific_chemical_exergy_mj_per_kg,
            "chemical_exergy_mwh": self.chemical_exergy_mwh,
            "tier": self.tier.value,
            "source_id": self.source_id,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ResolvedMaterialAccumulation:
    component: str
    mass_change_kg: float
    material: str | None
    composition: Mapping[str, float]
    constituent_changes_kg: Mapping[str, float]
    chemical_exergy_change_mwh: float | None
    specific_chemical_exergy_mj_per_kg: float | None
    tier: FidelityTier
    source_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "material": self.material,
            "mass_change": self.mass_change_kg,
            "unit": "kg",
            "composition": dict(self.composition),
            "constituent_changes_kg": dict(self.constituent_changes_kg),
            "specific_chemical_exergy_mj_per_kg": self.specific_chemical_exergy_mj_per_kg,
            "chemical_exergy_change_mwh": self.chemical_exergy_change_mwh,
            "tier": self.tier.value,
            "source_id": self.source_id,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class MaterialBalanceResult:
    name: str
    input_mass_kg: float
    product_mass_kg: float
    loss_mass_kg: float
    accumulation_mass_kg: float
    residual_mass_kg: float
    mass_efficiency: float | None
    constituent_balances: Mapping[str, Mapping[str, float]]
    chemical_exergy_complete: bool
    chemical_exergy: Mapping[str, float] | None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mass_unit": "kg",
            "input_mass": self.input_mass_kg,
            "product_mass": self.product_mass_kg,
            "loss_mass": self.loss_mass_kg,
            "accumulation_mass": self.accumulation_mass_kg,
            "residual_mass": self.residual_mass_kg,
            "mass_efficiency": self.mass_efficiency,
            "constituent_balances": {
                key: dict(value) for key, value in self.constituent_balances.items()
            },
            "chemical_exergy_complete": self.chemical_exergy_complete,
            "chemical_exergy": (
                dict(self.chemical_exergy) if self.chemical_exergy is not None else None
            ),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ComponentMaterialBalance:
    component: SystemComponent
    balance: MaterialBalanceResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component.to_dict(),
            "balance": self.balance.to_dict(),
        }


@dataclass(frozen=True)
class MaterialSystemResult:
    name: str
    tier: FidelityTier
    components: tuple[ComponentMaterialBalance, ...]
    streams: tuple[ResolvedMaterialStream, ...]
    accumulations: tuple[ResolvedMaterialAccumulation, ...]
    balance: MaterialBalanceResult
    warnings: tuple[str, ...] = ()
    source_catalog: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MATERIAL_BALANCE_SCHEMA_VERSION,
            "name": self.name,
            "tier": self.tier.value,
            "components": [item.to_dict() for item in self.components],
            "streams": [item.to_dict() for item in self.streams],
            "accumulations": [item.to_dict() for item in self.accumulations],
            "balance": self.balance.to_dict(),
            "warnings": list(self.warnings),
            "source_catalog": {
                key: dict(value) for key, value in self.source_catalog.items()
            },
        }


def _resolve_stream(item: MaterialStream) -> ResolvedMaterialStream:
    mass = _mass_kg(item.mass, item.unit, f"material stream {item.id!r} mass")
    factor = item.specific_chemical_exergy_mj_per_kg
    return ResolvedMaterialStream(
        id=item.id,
        mass_kg=mass,
        material=item.material,
        source=item.source,
        target=item.target,
        role=_role(item.source, item.target, item.role, f"material stream {item.id!r}"),
        composition=dict(item.composition),
        constituent_masses_kg={
            key: mass * value for key, value in item.composition.items()
        },
        chemical_exergy_mwh=(mass * factor / 3600.0 if factor is not None else None),
        specific_chemical_exergy_mj_per_kg=factor,
        tier=item.tier,
        source_id=item.source_id,
        metadata=item.metadata,
    )


def _resolve_accumulation(item: MaterialAccumulation) -> ResolvedMaterialAccumulation:
    mass = _mass_kg(
        item.mass_change,
        item.unit,
        f"material accumulation for {item.component!r}",
    )
    factor = item.specific_chemical_exergy_mj_per_kg
    return ResolvedMaterialAccumulation(
        component=item.component,
        mass_change_kg=mass,
        material=item.material,
        composition=dict(item.composition),
        constituent_changes_kg={
            key: mass * value for key, value in item.composition.items()
        },
        chemical_exergy_change_mwh=(
            mass * factor / 3600.0 if factor is not None else None
        ),
        specific_chemical_exergy_mj_per_kg=factor,
        tier=item.tier,
        source_id=item.source_id,
        metadata=item.metadata,
    )


def _balance(
    name: str,
    *,
    inputs: Sequence[ResolvedMaterialStream],
    products: Sequence[ResolvedMaterialStream],
    losses: Sequence[ResolvedMaterialStream],
    accumulations: Sequence[ResolvedMaterialAccumulation],
    tolerance_kg: float,
) -> MaterialBalanceResult:
    mass_change = sum(item.mass_change_kg for item in accumulations)
    input_mass = sum(item.mass_kg for item in inputs) + max(-mass_change, 0.0)
    product_mass = sum(item.mass_kg for item in products) + max(mass_change, 0.0)
    loss_mass = sum(item.mass_kg for item in losses)
    residual = input_mass - product_mass - loss_mass
    warnings: list[str] = []
    if abs(residual) > tolerance_kg:
        warnings.append(
            f"The material balance does not close; untracked residual is {residual:.6g} kg."
        )
    constituents = sorted(
        {
            key
            for item in (*inputs, *products, *losses)
            for key in item.constituent_masses_kg
        }
        | {key for item in accumulations for key in item.constituent_changes_kg}
    )
    constituent_balances: dict[str, Mapping[str, float]] = {}
    for constituent in constituents:
        change = sum(
            item.constituent_changes_kg.get(constituent, 0.0) for item in accumulations
        )
        incoming = sum(
            item.constituent_masses_kg.get(constituent, 0.0) for item in inputs
        )
        outgoing = sum(
            item.constituent_masses_kg.get(constituent, 0.0) for item in products
        )
        lost = sum(item.constituent_masses_kg.get(constituent, 0.0) for item in losses)
        constituent_balances[constituent] = {
            "input_mass_kg": incoming + max(-change, 0.0),
            "product_mass_kg": outgoing + max(change, 0.0),
            "loss_mass_kg": lost,
            "accumulation_mass_kg": change,
            "residual_mass_kg": incoming
            + max(-change, 0.0)
            - outgoing
            - max(change, 0.0)
            - lost,
        }
    chemical_items = [*inputs, *products, *losses, *accumulations]
    chemical_complete = bool(chemical_items) and all(
        (
            item.chemical_exergy_mwh is not None
            if isinstance(item, ResolvedMaterialStream)
            else item.chemical_exergy_change_mwh is not None
        )
        for item in chemical_items
    )
    chemical: Mapping[str, float] | None = None
    if chemical_complete:
        accumulation_exergy = sum(
            item.chemical_exergy_change_mwh or 0.0 for item in accumulations
        )
        input_exergy = sum(item.chemical_exergy_mwh or 0.0 for item in inputs) + max(
            -accumulation_exergy, 0.0
        )
        product_exergy = sum(
            item.chemical_exergy_mwh or 0.0 for item in products
        ) + max(accumulation_exergy, 0.0)
        loss_exergy = sum(item.chemical_exergy_mwh or 0.0 for item in losses)
        chemical = {
            "unit": "MWh_ex",
            "input_chemical_exergy": input_exergy,
            "product_chemical_exergy": product_exergy,
            "loss_chemical_exergy": loss_exergy,
            "accumulation_chemical_exergy": accumulation_exergy,
            "unreconciled_chemical_exergy": input_exergy - product_exergy - loss_exergy,
        }
        warnings.append(
            "Unreconciled chemical exergy is not labeled destruction without heat, work, and reaction accounting."
        )
    else:
        warnings.append(
            "Chemical-exergy balance omitted because one or more material streams lack an explicit specific factor."
        )
    return MaterialBalanceResult(
        name=name,
        input_mass_kg=input_mass,
        product_mass_kg=product_mass,
        loss_mass_kg=loss_mass,
        accumulation_mass_kg=mass_change,
        residual_mass_kg=residual,
        mass_efficiency=(product_mass / input_mass if input_mass > 0.0 else None),
        constituent_balances=constituent_balances,
        chemical_exergy_complete=chemical_complete,
        chemical_exergy=chemical,
        warnings=tuple(warnings),
    )


def analyze_material_system(
    name: str,
    *,
    components: Iterable[SystemComponent | Mapping[str, Any]],
    streams: Iterable[MaterialStream | Mapping[str, Any]],
    accumulations: Iterable[MaterialAccumulation | Mapping[str, Any]] = (),
    tolerance_kg: float = 1e-6,
    source_catalog: Mapping[str, Mapping[str, Any]] | None = None,
) -> MaterialSystemResult:
    """Analyze mass, constituent, and optionally chemical-exergy balances."""

    system_name = _text(name, "material system name")
    tolerance = _number(tolerance_kg, "tolerance_kg")
    if tolerance < 0.0:
        raise ValueError("tolerance_kg must be nonnegative")
    component_items = tuple(
        item if isinstance(item, SystemComponent) else SystemComponent.from_dict(item)
        for item in components
    )
    if not component_items:
        raise ValueError("at least one component is required")
    component_index = {item.id: item for item in component_items}
    if len(component_index) != len(component_items):
        raise ValueError("component ids must be unique")
    raw_streams = tuple(
        item if isinstance(item, MaterialStream) else MaterialStream.from_dict(item)
        for item in streams
    )
    if not raw_streams:
        raise ValueError("at least one material stream is required")
    if len({item.id for item in raw_streams}) != len(raw_streams):
        raise ValueError("material-stream ids must be unique")
    for item in raw_streams:
        if item.source is not None and item.source not in component_index:
            raise ValueError(
                f"material stream {item.id!r} has unknown source {item.source!r}"
            )
        if item.target is not None and item.target not in component_index:
            raise ValueError(
                f"material stream {item.id!r} has unknown target {item.target!r}"
            )
        if item.source is not None and item.source == item.target:
            raise ValueError(
                f"material stream {item.id!r} cannot connect a component to itself"
            )
    raw_accumulations = tuple(
        item
        if isinstance(item, MaterialAccumulation)
        else MaterialAccumulation.from_dict(item)
        for item in accumulations
    )
    if len({item.component for item in raw_accumulations}) != len(raw_accumulations):
        raise ValueError("only one material accumulation may be declared per component")
    for item in raw_accumulations:
        if item.component not in component_index:
            raise ValueError(
                f"material accumulation has unknown component {item.component!r}"
            )
    catalog = dict(source_catalog or {})
    for source_id, source in catalog.items():
        if not isinstance(source, Mapping):
            raise ValueError(f"material source {source_id!r} must be an object")
        missing = {"title", "license", "applicable_boundary"} - set(source)
        if missing:
            raise ValueError(
                f"material source {source_id!r} is missing: "
                + ", ".join(sorted(missing))
            )
    referenced_sources = {
        item.source_id for item in (*raw_streams, *raw_accumulations) if item.source_id
    }
    missing_sources = sorted(referenced_sources - set(catalog))
    if missing_sources:
        raise ValueError("unknown material source ids: " + ", ".join(missing_sources))
    resolved_streams = tuple(_resolve_stream(item) for item in raw_streams)
    resolved_accumulations = tuple(
        _resolve_accumulation(item) for item in raw_accumulations
    )
    component_results: list[ComponentMaterialBalance] = []
    warning_items: list[str] = [
        "Material and chemical-exergy balances are separate from the energy balance to prevent double counting."
    ]
    for component in component_items:
        incoming = tuple(
            item for item in resolved_streams if item.target == component.id
        )
        outgoing = tuple(
            item for item in resolved_streams if item.source == component.id
        )
        products = tuple(item for item in outgoing if item.role != "loss")
        losses = tuple(item for item in outgoing if item.role == "loss")
        component_accumulations = tuple(
            item for item in resolved_accumulations if item.component == component.id
        )
        result = _balance(
            component.label or component.id,
            inputs=incoming,
            products=products,
            losses=losses,
            accumulations=component_accumulations,
            tolerance_kg=tolerance,
        )
        component_results.append(ComponentMaterialBalance(component, result))
        warning_items.extend(
            f"{component.id}: {message}" for message in result.warnings
        )
    boundary_inputs = tuple(item for item in resolved_streams if item.source is None)
    boundary_products = tuple(
        item
        for item in resolved_streams
        if item.target is None and item.role == "product"
    )
    boundary_losses = tuple(
        item for item in resolved_streams if item.target is None and item.role == "loss"
    )
    system_balance = _balance(
        system_name,
        inputs=boundary_inputs,
        products=boundary_products,
        losses=boundary_losses,
        accumulations=resolved_accumulations,
        tolerance_kg=tolerance,
    )
    warning_items.extend(system_balance.warnings)
    return MaterialSystemResult(
        name=system_name,
        tier=_minimum_tier(
            item.tier for item in (*resolved_streams, *resolved_accumulations)
        ),
        components=tuple(component_results),
        streams=resolved_streams,
        accumulations=resolved_accumulations,
        balance=system_balance,
        warnings=tuple(dict.fromkeys(warning_items)),
        source_catalog={key: dict(catalog[key]) for key in sorted(referenced_sources)},
    )


def analyze_material_definition(payload: Mapping[str, Any]) -> MaterialSystemResult:
    """Analyze the stable JSON-shaped material-balance contract."""

    allowed = {
        "name",
        "components",
        "streams",
        "accumulations",
        "tolerance_kg",
        "source_catalog",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError("unknown material-definition fields: " + ", ".join(unknown))
    return analyze_material_system(
        str(payload.get("name", "material system")),
        components=payload.get("components", ()),
        streams=payload.get("streams", ()),
        accumulations=payload.get("accumulations", ()),
        tolerance_kg=payload.get("tolerance_kg", 1e-6),
        source_catalog=payload.get("source_catalog"),
    )
