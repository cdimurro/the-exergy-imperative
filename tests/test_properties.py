import pytest

import exergy_imperative as xi


def test_coolprop_physical_exergy_for_hot_water():
    if not xi.coolprop_available():
        pytest.skip("CoolProp optional dependency is not installed")
    result = xi.coolprop_physical_exergy(
        "Water",
        "80 C",
        200,
        environment=xi.Environment.reporting_20c(),
        mass_flow_kg_s=1.5,
    )
    assert result.physical_exergy_j_per_kg > 0
    assert result.exergy_rate_kw == pytest.approx(
        result.physical_exergy_j_per_kg * 1.5 / 1000
    )
    assert result.method_id.endswith("v1")


@pytest.mark.parametrize("mass_flow", [float("nan"), float("inf"), -1.0])
def test_coolprop_rejects_invalid_mass_flow(mass_flow):
    if not xi.coolprop_available():
        pytest.skip("CoolProp optional dependency is not installed")
    with pytest.raises(
        ValueError, match="mass_flow_kg_s must be finite and nonnegative"
    ):
        xi.coolprop_physical_exergy(
            "Water",
            80,
            200,
            mass_flow_kg_s=mass_flow,
        )
