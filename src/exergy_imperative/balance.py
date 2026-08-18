"""Process- and system-level exergy balances."""

from __future__ import annotations

import math
from collections.abc import Iterable

from .models import BalanceResult, ExergyStream
from .units import convert_energy


def _streams(values: Iterable[ExergyStream], role: str) -> tuple[ExergyStream, ...]:
    records = tuple(values)
    for stream in records:
        if stream.exergy < 0.0:
            raise ValueError(f"{role} stream {stream.name!r} has negative exergy")
    return records


def _converted(stream: ExergyStream, target_unit: str) -> float:
    return convert_energy(stream.exergy, stream.unit, target_unit)


def analyze_balance(
    name: str,
    *,
    inputs: Iterable[ExergyStream],
    products: Iterable[ExergyStream],
    losses: Iterable[ExergyStream] = (),
    destructions: Iterable[ExergyStream] | None = None,
    unit: str = "MWh_ex",
    tolerance: float = 1e-9,
) -> BalanceResult:
    """Close an exergy balance and diagnose inconsistent boundaries.

    If ``destructions`` is omitted, destruction is inferred as the nonnegative
    residual after products and losses. Supplying destruction keeps any remaining
    closure error visible as ``residual``.
    """

    try:
        tolerance = float(tolerance)
    except (TypeError, ValueError) as exc:
        raise ValueError("tolerance must be numeric") from exc
    if not math.isfinite(tolerance) or tolerance < 0.0:
        raise ValueError("tolerance must be finite and nonnegative")
    input_streams = _streams(inputs, "input")
    product_streams = _streams(products, "product")
    loss_streams = _streams(losses, "loss")
    if not input_streams:
        raise ValueError("at least one input stream is required")
    input_total = sum(_converted(stream, unit) for stream in input_streams)
    product_total = sum(_converted(stream, unit) for stream in product_streams)
    loss_total = sum(_converted(stream, unit) for stream in loss_streams)
    if input_total <= 0.0:
        raise ValueError("total input exergy must be positive")

    warnings: list[str] = []
    inferred = destructions is None
    destruction_streams: tuple[ExergyStream, ...]
    if destructions is None:
        inferred_value = input_total - product_total - loss_total
        if inferred_value < -tolerance:
            warnings.append(
                "Products and losses exceed input exergy; check units, boundaries, and time bases."
            )
            destruction_total = 0.0
            residual = inferred_value
            destruction_streams = ()
        else:
            destruction_total = max(inferred_value, 0.0)
            residual = 0.0
            destruction_streams = (
                ExergyStream(
                    "inferred exergy destruction", destruction_total, unit=unit
                ),
            )
    else:
        destruction_streams = _streams(destructions, "destruction")
        destruction_total = sum(
            _converted(stream, unit) for stream in destruction_streams
        )
        residual = input_total - product_total - loss_total - destruction_total
        if abs(residual) > tolerance:
            warnings.append(
                f"The declared exergy balance does not close; residual is {residual:.6g} {unit}."
            )
    efficiency = product_total / input_total
    if efficiency > 1.0 + tolerance:
        warnings.append("Product exergy exceeds input exergy.")

    hotspot_values = [
        *(
            (f"loss: {stream.name}", _converted(stream, unit))
            for stream in loss_streams
        ),
        *(
            (f"destruction: {stream.name}", _converted(stream, unit))
            for stream in destruction_streams
        ),
    ]
    hotspots = tuple(sorted(hotspot_values, key=lambda item: item[1], reverse=True))
    return BalanceResult(
        name=name,
        input_exergy=input_total,
        product_exergy=product_total,
        loss_exergy=loss_total,
        destruction_exergy=destruction_total,
        residual=residual,
        exergetic_efficiency=efficiency,
        unit=unit,
        inferred_destruction=inferred,
        warnings=tuple(warnings),
        hotspots=hotspots,
    )
