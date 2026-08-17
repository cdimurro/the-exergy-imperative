"""Monte Carlo propagation, sensitivity, and value-of-information tools."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from statistics import fmean, pstdev
from typing import Any, Callable, Mapping, Sequence


def _positive_integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if not math.isfinite(number) or not number.is_integer() or number <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return int(number)


@dataclass(frozen=True)
class DistributionSpec:
    """One transparent uncertain input distribution."""

    kind: str
    value: float | None = None
    low: float | None = None
    mode: float | None = None
    high: float | None = None
    mean: float | None = None
    standard_deviation: float | None = None
    unit: str | None = None
    source_id: str | None = None
    note: str | None = None

    @classmethod
    def fixed(cls, value: float, **metadata: Any) -> "DistributionSpec":
        return cls("fixed", value=float(value), **metadata)

    @classmethod
    def uniform(cls, low: float, high: float, **metadata: Any) -> "DistributionSpec":
        return cls("uniform", low=float(low), high=float(high), **metadata)

    @classmethod
    def triangular(
        cls, low: float, mode: float, high: float, **metadata: Any
    ) -> "DistributionSpec":
        return cls(
            "triangular",
            low=float(low),
            mode=float(mode),
            high=float(high),
            **metadata,
        )

    @classmethod
    def normal(
        cls,
        mean: float,
        standard_deviation: float,
        *,
        low: float | None = None,
        high: float | None = None,
        **metadata: Any,
    ) -> "DistributionSpec":
        return cls(
            "normal",
            mean=float(mean),
            standard_deviation=float(standard_deviation),
            low=float(low) if low is not None else None,
            high=float(high) if high is not None else None,
            **metadata,
        )

    def __post_init__(self) -> None:
        if self.kind not in {"fixed", "uniform", "triangular", "normal"}:
            raise ValueError("kind must be fixed, uniform, triangular, or normal")
        values = (
            self.value,
            self.low,
            self.mode,
            self.high,
            self.mean,
            self.standard_deviation,
        )
        if any(item is not None and not math.isfinite(item) for item in values):
            raise ValueError("distribution parameters must be finite")
        if self.kind == "fixed" and self.value is None:
            raise ValueError("fixed distributions require value")
        if self.kind in {"uniform", "triangular"} and (
            self.low is None or self.high is None or self.low > self.high
        ):
            raise ValueError(f"{self.kind} distributions require low <= high")
        if self.kind == "triangular" and (
            self.mode is None or not self.low <= self.mode <= self.high
        ):
            raise ValueError("triangular distributions require low <= mode <= high")
        if self.kind == "normal" and (
            self.mean is None
            or self.standard_deviation is None
            or self.standard_deviation < 0.0
        ):
            raise ValueError("normal distributions require mean and nonnegative sd")
        if (
            self.kind == "normal"
            and self.low is not None
            and self.high is not None
            and self.low > self.high
        ):
            raise ValueError("normal distribution bounds require low <= high")

    def sample(self, generator: random.Random) -> float:
        if self.kind == "fixed":
            return float(self.value)
        if self.kind == "uniform":
            return generator.uniform(float(self.low), float(self.high))
        if self.kind == "triangular":
            return generator.triangular(
                float(self.low), float(self.high), float(self.mode)
            )
        value = generator.gauss(float(self.mean), float(self.standard_deviation))
        if self.low is not None:
            value = max(value, self.low)
        if self.high is not None:
            value = min(value, self.high)
        return value

    def central_value(self) -> float:
        if self.kind == "fixed":
            return float(self.value)
        if self.kind == "uniform":
            return (float(self.low) + float(self.high)) / 2.0
        if self.kind == "triangular":
            return float(self.mode)
        return float(self.mean)

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in self.__dict__.items() if value is not None}


@dataclass(frozen=True)
class OutputStatistics:
    mean: float
    standard_deviation: float
    minimum: float
    p05: float
    p50: float
    p95: float
    maximum: float

    def to_dict(self) -> dict[str, float]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class SensitivityRanking:
    input_name: str
    output_name: str
    rank_correlation: float
    squared_rank_correlation: float

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class MonteCarloResult:
    requested_samples: int
    valid_samples: int
    failed_samples: int
    seed: int | None
    inputs: Mapping[str, DistributionSpec]
    outputs: Mapping[str, OutputStatistics]
    sensitivities: tuple[SensitivityRanking, ...]
    output_samples: Mapping[str, tuple[float, ...]]
    input_samples: Mapping[str, tuple[float, ...]]
    failure_messages: tuple[str, ...] = ()

    def to_dict(self, *, include_samples: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": "1.0",
            "requested_samples": self.requested_samples,
            "valid_samples": self.valid_samples,
            "failed_samples": self.failed_samples,
            "seed": self.seed,
            "inputs": {name: spec.to_dict() for name, spec in self.inputs.items()},
            "outputs": {
                name: statistics.to_dict() for name, statistics in self.outputs.items()
            },
            "sensitivities": [item.to_dict() for item in self.sensitivities],
            "failure_messages": list(self.failure_messages),
        }
        if include_samples:
            result["input_samples"] = {
                name: list(values) for name, values in self.input_samples.items()
            }
            result["output_samples"] = {
                name: list(values) for name, values in self.output_samples.items()
            }
        return result


def _percentile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("cannot calculate a percentile of no values")
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def _statistics(values: Sequence[float]) -> OutputStatistics:
    ordered = sorted(values)
    return OutputStatistics(
        mean=fmean(values),
        standard_deviation=pstdev(values),
        minimum=ordered[0],
        p05=_percentile(ordered, 0.05),
        p50=_percentile(ordered, 0.50),
        p95=_percentile(ordered, 0.95),
        maximum=ordered[-1],
    )


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        end = index + 1
        while end < len(order) and values[order[end]] == values[order[index]]:
            end += 1
        average = (index + end - 1) / 2.0 + 1.0
        for position in order[index:end]:
            ranks[position] = average
        index = end
    return ranks


def _correlation(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("correlation inputs must have the same nonzero length")
    left_mean = fmean(left)
    right_mean = fmean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_sum = sum((value - left_mean) ** 2 for value in left)
    right_sum = sum((value - right_mean) ** 2 for value in right)
    denominator = math.sqrt(left_sum * right_sum)
    return numerator / denominator if denominator else 0.0


def _model_outputs(value: Any) -> dict[str, float]:
    if isinstance(value, Mapping):
        outputs = {str(name): float(item) for name, item in value.items()}
    else:
        outputs = {"result": float(value)}
    if not outputs or any(not math.isfinite(item) for item in outputs.values()):
        raise ValueError("model outputs must be finite numeric values")
    return outputs


def monte_carlo(
    model: Callable[..., Any],
    inputs: Mapping[str, DistributionSpec | float],
    *,
    samples: int = 1000,
    seed: int | None = 42,
    max_failure_fraction: float = 0.10,
) -> MonteCarloResult:
    """Propagate input distributions through any callable model."""

    sample_count = _positive_integer(samples, "samples")
    failure_limit = float(max_failure_fraction)
    if not math.isfinite(failure_limit) or not 0.0 <= failure_limit <= 1.0:
        raise ValueError("max_failure_fraction must be finite and between zero and one")
    specs = {
        str(name): (
            value
            if isinstance(value, DistributionSpec)
            else DistributionSpec.fixed(value)
        )
        for name, value in inputs.items()
    }
    generator = random.Random(seed)
    input_draws: dict[str, list[float]] = {name: [] for name in specs}
    output_draws: dict[str, list[float]] = {}
    failure_messages: list[str] = []
    for _ in range(sample_count):
        draw = {name: spec.sample(generator) for name, spec in specs.items()}
        try:
            outputs = _model_outputs(model(**draw))
        except (ArithmeticError, TypeError, ValueError) as exc:
            if len(failure_messages) < 10:
                failure_messages.append(str(exc))
            continue
        if output_draws and set(outputs) != set(output_draws):
            raise ValueError("model must return the same output names for every sample")
        for name, value in draw.items():
            input_draws[name].append(value)
        for name, value in outputs.items():
            output_draws.setdefault(name, []).append(value)

    valid = len(next(iter(output_draws.values()), ()))
    failed = sample_count - valid
    if valid == 0 or failed / sample_count > failure_limit:
        raise ValueError(
            f"Monte Carlo model failed for {failed} of {samples} samples; "
            "review input bounds or increase max_failure_fraction"
        )

    sensitivities: list[SensitivityRanking] = []
    for output_name, output_values in output_draws.items():
        output_ranks = _ranks(output_values)
        for input_name, input_values in input_draws.items():
            coefficient = _correlation(_ranks(input_values), output_ranks)
            sensitivities.append(
                SensitivityRanking(
                    input_name,
                    output_name,
                    coefficient,
                    coefficient**2,
                )
            )
    sensitivities.sort(
        key=lambda item: (
            item.output_name,
            -item.squared_rank_correlation,
            item.input_name,
        )
    )
    return MonteCarloResult(
        requested_samples=sample_count,
        valid_samples=valid,
        failed_samples=failed,
        seed=seed,
        inputs=specs,
        outputs={name: _statistics(values) for name, values in output_draws.items()},
        sensitivities=tuple(sensitivities),
        output_samples={name: tuple(values) for name, values in output_draws.items()},
        input_samples={name: tuple(values) for name, values in input_draws.items()},
        failure_messages=tuple(failure_messages),
    )


@dataclass(frozen=True)
class OneAtATimeSensitivity:
    input_name: str
    base_value: float
    low_value: float
    high_value: float
    low_output: float
    base_output: float
    high_output: float
    normalized_sensitivity: float | None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def one_at_a_time_sensitivity(
    model: Callable[..., float],
    base_inputs: Mapping[str, float],
    ranges: Mapping[str, tuple[float, float]],
) -> tuple[OneAtATimeSensitivity, ...]:
    """Calculate auditable low/base/high sensitivity for selected inputs."""

    def finite(value: Any, label: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be numeric") from exc
        if not math.isfinite(number):
            raise ValueError(f"{label} must be finite")
        return number

    base = {
        name: finite(value, f"sensitivity base input {name!r}")
        for name, value in base_inputs.items()
    }
    validated_ranges: list[tuple[str, float, float]] = []
    for name, (low, high) in ranges.items():
        if name not in base:
            raise KeyError(f"sensitivity input {name!r} is not in base_inputs")
        low_value = finite(low, f"sensitivity low input {name!r}")
        high_value = finite(high, f"sensitivity high input {name!r}")
        if not low_value <= base[name] <= high_value:
            raise ValueError(
                f"sensitivity range for {name!r} must satisfy low <= base <= high"
            )
        validated_ranges.append((name, low_value, high_value))

    base_output = finite(model(**base), "sensitivity base output")
    results: list[OneAtATimeSensitivity] = []
    for name, low_value, high_value in validated_ranges:
        low_inputs = dict(base)
        high_inputs = dict(base)
        low_inputs[name] = low_value
        high_inputs[name] = high_value
        low_output = finite(model(**low_inputs), f"sensitivity low output for {name!r}")
        high_output = finite(
            model(**high_inputs), f"sensitivity high output for {name!r}"
        )
        input_span = finite(
            high_value - low_value, f"sensitivity input span for {name!r}"
        )
        output_span = finite(
            high_output - low_output, f"sensitivity output span for {name!r}"
        )
        normalized = None
        if input_span and base_output and base[name]:
            normalized = finite(
                (output_span / base_output) / (input_span / base[name]),
                f"normalized sensitivity for {name!r}",
            )
        results.append(
            OneAtATimeSensitivity(
                name,
                base[name],
                low_value,
                high_value,
                low_output,
                base_output,
                high_output,
                normalized,
            )
        )
    results.sort(key=lambda item: abs(item.normalized_sensitivity or 0.0), reverse=True)
    return tuple(results)


@dataclass(frozen=True)
class ValueOfInformationResult:
    recommended_without_information: str
    expected_value_without_information: float
    expected_value_with_perfect_information: float
    expected_value_of_perfect_information: float
    expected_values: Mapping[str, float]
    sample_count: int
    currency: str

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def expected_value_of_perfect_information(
    scenario_net_benefit_samples: Mapping[str, Sequence[float]],
    *,
    currency: str = "USD",
) -> ValueOfInformationResult:
    """Return EVPI from paired uncertain net-benefit samples by decision."""

    if not scenario_net_benefit_samples:
        raise ValueError("at least one scenario is required")
    lengths = {len(values) for values in scenario_net_benefit_samples.values()}
    if len(lengths) != 1 or not next(iter(lengths)):
        raise ValueError("scenario samples must have the same nonzero length")
    samples: dict[str, tuple[float, ...]] = {}
    for name, values in scenario_net_benefit_samples.items():
        try:
            converted = tuple(float(value) for value in values)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"scenario {name!r} samples must be numeric") from exc
        if any(not math.isfinite(value) for value in converted):
            raise ValueError(f"scenario {name!r} samples must be finite")
        samples[name] = converted
    expected = {name: fmean(values) for name, values in samples.items()}
    recommended = max(expected, key=expected.get)
    without_information = expected[recommended]
    sample_count = next(iter(lengths))
    with_information = fmean(
        max(values[index] for values in samples.values())
        for index in range(sample_count)
    )
    return ValueOfInformationResult(
        recommended_without_information=recommended,
        expected_value_without_information=without_information,
        expected_value_with_perfect_information=with_information,
        expected_value_of_perfect_information=max(
            0.0, with_information - without_information
        ),
        expected_values=expected,
        sample_count=sample_count,
        currency=currency,
    )
