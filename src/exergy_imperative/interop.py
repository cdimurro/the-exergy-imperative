"""Small adapters for quantity-and-quality records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from .assessment import assess
from .models import AssessmentResult


def from_quantity_quality(record: Mapping[str, Any]) -> AssessmentResult:
    """Create an assessment from the companion project's public record shape."""

    quantity = record.get("quantity", record.get("energy"))
    normalized = record.get("normalized")
    if normalized is not None and not isinstance(normalized, bool):
        raise TypeError("normalized interoperability metadata must be boolean")
    if normalized is False and quantity is None:
        raise ValueError("an absolute interoperability record requires a quantity")

    def preserve_normalization(result: AssessmentResult) -> AssessmentResult:
        if normalized is None or result.normalized is normalized:
            return result
        request = dict(result.request)
        request["_normalized_override"] = normalized
        return replace(result, normalized=normalized, request=request)

    unit = str(record.get("unit", "MWh"))
    factor = record.get("exergy_factor", record.get("fx"))
    if factor is not None:
        return preserve_normalization(
            assess(energy=quantity, unit=unit, exergy_factor=float(factor))
        )
    source = record.get("source_c", record.get("Th_C"))
    sink = record.get("sink_c", record.get("T0_C"))
    return_ = record.get("return_c")
    if source is not None and sink is not None:
        return preserve_normalization(
            assess(
                service="district-heating",
                energy=quantity,
                unit=unit,
                source_temperature=float(source),
                return_temperature=float(return_) if return_ is not None else None,
                ambient_temperature=float(sink),
            )
        )
    reference_id = record.get("reference_id")
    carrier = record.get("carrier")
    if reference_id and "electric" in str(reference_id).lower():
        carrier = "electricity"
    return preserve_normalization(assess(energy=quantity, unit=unit, carrier=carrier))


def to_quantity_quality(result: AssessmentResult) -> dict[str, Any]:
    """Export the stream-level portion of an assessment."""

    factor = result.exergy_factor.value if result.exergy_factor else None
    energy_estimate = result.useful_energy or result.input_energy
    energy = energy_estimate.value if energy_estimate is not None else None
    return {
        "quantity": energy,
        "unit": energy_estimate.unit if energy_estimate else None,
        "normalized": result.normalized,
        "exergy_factor": factor,
        "accessible_exergy": result.useful_exergy.value
        if result.useful_exergy
        else None,
        "accessible_exergy_unit": result.useful_exergy.unit
        if result.useful_exergy
        else None,
        "tier": result.tier.value,
        "method_id": result.method_id,
        "assumptions": {
            name: parameter.to_dict() for name, parameter in result.assumptions.items()
        },
    }
