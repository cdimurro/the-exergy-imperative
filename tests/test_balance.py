import pytest

import exergy_imperative as xi


def test_balance_infers_destruction():
    result = xi.analyze_balance(
        "plant",
        inputs=[xi.ExergyStream("fuel", 100)],
        products=[xi.ExergyStream("power", 40)],
        losses=[xi.ExergyStream("stack", 10)],
    )
    assert result.destruction_exergy == pytest.approx(50)
    assert result.residual == pytest.approx(0)
    assert result.exergetic_efficiency == pytest.approx(0.4)
    assert result.hotspots[0][0] == "destruction: inferred exergy destruction"


def test_declared_balance_exposes_residual():
    result = xi.analyze_balance(
        "plant",
        inputs=[xi.ExergyStream("fuel", 100)],
        products=[xi.ExergyStream("product", 40)],
        losses=[xi.ExergyStream("stack", 10)],
        destructions=[xi.ExergyStream("combustion", 45)],
    )
    assert result.residual == pytest.approx(5)
    assert result.warnings


def test_invalid_balance_is_diagnosed():
    result = xi.analyze_balance(
        "bad",
        inputs=[xi.ExergyStream("input", 10)],
        products=[xi.ExergyStream("product", 12)],
    )
    assert result.destruction_exergy == pytest.approx(-2)
    assert any("exceed" in warning for warning in result.warnings)


def test_negative_stream_is_rejected():
    with pytest.raises(ValueError, match="negative"):
        xi.analyze_balance(
            "bad",
            inputs=[xi.ExergyStream("input", -1)],
            products=[],
        )


def test_balance_converts_exergy_units():
    result = xi.analyze_balance(
        "mixed units",
        inputs=[xi.ExergyStream("input", 3.6, unit="GJ_ex")],
        products=[xi.ExergyStream("product", 500, unit="kWh_ex")],
        unit="MWh_ex",
    )
    assert result.input_exergy == pytest.approx(1)
    assert result.product_exergy == pytest.approx(0.5)
    assert result.destruction_exergy == pytest.approx(0.5)


@pytest.mark.parametrize("tolerance", [float("nan"), float("inf"), float("-inf")])
def test_balance_rejects_nonfinite_tolerance(tolerance):
    with pytest.raises(ValueError, match="tolerance must be finite and nonnegative"):
        xi.analyze_balance(
            "invalid tolerance",
            inputs=[xi.ExergyStream("input", 10)],
            products=[xi.ExergyStream("product", 5)],
            tolerance=tolerance,
        )
