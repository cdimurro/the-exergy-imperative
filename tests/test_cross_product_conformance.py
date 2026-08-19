import pytest

import exergy_imperative as xi


def _contract():
    return xi.load_cross_product_conformance_contract()


def _run(operation, inputs):
    if operation == "thermal_exergy_factor_c":
        return xi.thermal_exergy_factor_c(inputs["source_c"], inputs["reference_c"])
    if operation == "cooling_exergy_factor_c":
        return xi.cooling_exergy_factor_c(inputs["cold_c"], inputs["ambient_c"])
    if operation == "sensible_heat_exergy_factor_c":
        return xi.sensible_heat_exergy_factor_c(
            inputs["supply_c"], inputs["return_c"], inputs["reference_c"]
        )
    if operation == "petela_exergy_factor":
        return xi.petela_exergy_factor(
            inputs["reference_k"], inputs["radiation_temperature_k"]
        )
    if operation == "accessible_exergy":
        return xi.accessible_exergy(inputs["energy"], inputs["exergy_factor"])
    if operation == "weighted_exergy_factor":
        return xi.weighted_exergy_factor(inputs["records"])
    raise AssertionError(f"unhandled contract operation: {operation}")


def test_contract_declares_reference_conditions_and_source_revision():
    contract = _contract()
    assert contract["schema_version"] == "exergy_conformance_contract_v1"
    assert contract["canonical_project"] == "quantity-and-quality"
    assert contract["constants"]["standard_reference_temperature_c"] == 20.0
    assert contract["constants"]["solar_radiation_temperature_k"] == 5778.0
    assert len(contract["reference_data"]["sha256"]) == 64


@pytest.mark.parametrize(
    "case",
    [
        case
        for case in _contract()["valid_cases"]
        if "exergy-imperative" in case["implementations"]
    ],
    ids=lambda case: case["id"],
)
def test_valid_cross_product_case(case):
    assert _run(case["operation"], case["inputs"]) == pytest.approx(
        case["expected"], abs=case["absolute_tolerance"]
    )


@pytest.mark.parametrize(
    "case",
    [
        case
        for case in _contract()["invalid_cases"]
        if "exergy-imperative" in case["implementations"]
    ],
    ids=lambda case: case["id"],
)
def test_invalid_cross_product_case(case):
    with pytest.raises((TypeError, ValueError)):
        _run(case["operation"], case["inputs"])
