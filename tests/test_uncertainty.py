import pytest

import exergy_imperative as xi


def test_distribution_validation_and_sampling():
    with pytest.raises(ValueError, match="low <= high"):
        xi.DistributionSpec.uniform(2, 1)
    with pytest.raises(ValueError, match="low <= mode"):
        xi.DistributionSpec.triangular(0, 2, 1)
    with pytest.raises(ValueError, match="bounds require low <= high"):
        xi.DistributionSpec.normal(0, 1, low=10, high=0)


def test_monte_carlo_is_reproducible_and_ranks_drivers():
    inputs = {
        "efficiency": xi.DistributionSpec.triangular(0.05, 0.10, 0.20),
        "price": xi.DistributionSpec.uniform(40, 80),
    }

    def model(efficiency, price):
        return {"annual_savings": 1000 * efficiency * price}

    first = xi.monte_carlo(model, inputs, samples=500, seed=7)
    second = xi.monte_carlo(model, inputs, samples=500, seed=7)
    assert first.outputs == second.outputs
    assert first.valid_samples == 500
    rankings = [
        item for item in first.sensitivities if item.output_name == "annual_savings"
    ]
    assert rankings[0].squared_rank_correlation >= rankings[1].squared_rank_correlation
    assert first.outputs["annual_savings"].p05 < first.outputs["annual_savings"].p95


@pytest.mark.parametrize("samples", [True, float("nan"), float("inf"), 1.5])
def test_monte_carlo_rejects_invalid_sample_counts(samples):
    with pytest.raises(ValueError, match="samples must be a positive integer"):
        xi.monte_carlo(lambda x: x, {"x": 1}, samples=samples)


def test_rank_sensitivity_is_not_mislabeled_as_variance_importance():
    result = xi.monte_carlo(
        lambda x: x**2,
        {"x": xi.DistributionSpec.uniform(-1, 1)},
        samples=1000,
        seed=7,
    )
    ranking = result.sensitivities[0]
    assert ranking.squared_rank_correlation == pytest.approx(
        ranking.rank_correlation**2
    )
    assert "variance_importance" not in ranking.to_dict()


def test_monte_carlo_tracks_small_failure_rate():
    spec = {"x": xi.DistributionSpec.uniform(-1, 1)}
    result = xi.monte_carlo(
        lambda x: 1 / x if abs(x) > 0.01 else (_ for _ in ()).throw(ValueError("gap")),
        spec,
        samples=200,
        seed=1,
        max_failure_fraction=0.1,
    )
    assert result.failed_samples > 0
    assert result.failure_messages


@pytest.mark.parametrize("limit", [-0.1, 1.1, float("nan"), float("inf")])
def test_monte_carlo_validates_failure_fraction(limit):
    with pytest.raises(ValueError, match="max_failure_fraction"):
        xi.monte_carlo(
            lambda x: x,
            {"x": xi.DistributionSpec.fixed(1)},
            samples=10,
            max_failure_fraction=limit,
        )


def test_one_at_a_time_sensitivity():
    result = xi.one_at_a_time_sensitivity(
        lambda energy, factor: energy * factor,
        {"energy": 100, "factor": 0.2},
        {"energy": (80, 120), "factor": (0.1, 0.3)},
    )
    assert {item.input_name for item in result} == {"energy", "factor"}
    assert all(item.base_output == pytest.approx(20) for item in result)


@pytest.mark.parametrize("bounds", [(2, 0), (0, 0.5), (1.5, 2)])
def test_one_at_a_time_sensitivity_requires_ranges_to_bound_base(bounds):
    with pytest.raises(ValueError, match="low <= base <= high"):
        xi.one_at_a_time_sensitivity(
            lambda x: x,
            {"x": 1},
            {"x": bounds},
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_one_at_a_time_sensitivity_rejects_nonfinite_model_outputs(value):
    with pytest.raises(ValueError, match="sensitivity base output must be finite"):
        xi.one_at_a_time_sensitivity(
            lambda x: value,
            {"x": 1},
            {"x": (0, 2)},
        )


def test_expected_value_of_perfect_information():
    result = xi.expected_value_of_perfect_information(
        {
            "do nothing": [0, 0, 0, 0],
            "project": [-10, 20, -10, 20],
        }
    )
    assert result.recommended_without_information == "project"
    assert result.expected_value_without_information == pytest.approx(5)
    assert result.expected_value_with_perfect_information == pytest.approx(10)
    assert result.expected_value_of_perfect_information == pytest.approx(5)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_expected_value_of_perfect_information_rejects_nonfinite_samples(invalid):
    with pytest.raises(ValueError, match="scenario 'project' samples must be finite"):
        xi.expected_value_of_perfect_information(
            {"baseline": [0, 0], "project": [1, invalid]}
        )
