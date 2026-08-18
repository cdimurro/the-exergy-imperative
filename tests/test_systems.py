import jsonschema
import pytest

import exergy_imperative as xi


def _plant_definition():
    return {
        "name": "multi-stage plant",
        "components": [
            {"id": "supply", "kind": "source"},
            {"id": "converter", "kind": "converter"},
            {"id": "load", "kind": "sink"},
        ],
        "flows": [
            {
                "id": "fuel",
                "energy": 100,
                "target": "supply",
                "exergy_factor": 1,
            },
            {
                "id": "feed",
                "energy": 100,
                "source": "supply",
                "target": "converter",
                "exergy_factor": 1,
            },
            {
                "id": "useful",
                "energy": 40,
                "source": "converter",
                "target": "load",
                "exergy_factor": 1,
            },
            {
                "id": "waste heat",
                "energy": 60,
                "exergy": 10,
                "source": "converter",
                "role": "loss",
            },
            {
                "id": "service",
                "energy": 40,
                "source": "load",
                "exergy_factor": 1,
            },
        ],
    }


def test_connected_system_keeps_energy_and_exergy_balances_distinct():
    result = xi.analyze_system_definition(_plant_definition())

    assert result.energy.input_energy == pytest.approx(100)
    assert result.energy.product_energy == pytest.approx(40)
    assert result.energy.loss_energy == pytest.approx(60)
    assert result.energy.residual == pytest.approx(0)
    assert result.exergy.loss_exergy == pytest.approx(10)
    assert result.exergy.destruction_exergy == pytest.approx(50)
    assert result.exergy.exergetic_efficiency == pytest.approx(0.4)
    assert len(result.components) == 3
    jsonschema.validate(result.to_dict(), xi.load_schema("system-analysis"))


def test_system_resolves_profile_factor_with_provenance_and_screening_tier():
    payload = {
        "name": "electrical load",
        "components": [{"id": "load", "kind": "converter"}],
        "flows": [
            {
                "id": "electricity in",
                "energy": 10,
                "target": "load",
                "carrier": "electricity",
            },
            {
                "id": "electricity out",
                "energy": 9,
                "source": "load",
                "carrier": "electricity",
            },
            {
                "id": "loss",
                "energy": 1,
                "source": "load",
                "role": "loss",
                "carrier": "electricity",
            },
        ],
    }

    result = xi.analyze_system_definition(payload)

    assert result.tier is xi.FidelityTier.F1
    assert result.flows[0].factor_status == "profile"
    assert result.source_catalog
    assert any("not a measurement" in warning for warning in result.warnings)
    assert any("electricity-to-electricity" in warning for warning in result.warnings)


def test_system_rejects_ambiguous_or_broken_boundaries():
    payload = _plant_definition()
    payload["flows"][1]["role"] = "product"
    with pytest.raises(ValueError, match="connected flow.*internal"):
        xi.analyze_system_definition(payload)

    payload = _plant_definition()
    payload["flows"][1]["target"] = "missing"
    with pytest.raises(ValueError, match="unknown target"):
        xi.analyze_system_definition(payload)


def test_timeseries_aggregates_external_flows_and_net_storage_change():
    result = xi.analyze_system_timeseries(
        "battery duty",
        components=[
            {"id": "battery", "kind": "storage"},
            {"id": "load", "kind": "sink"},
        ],
        records=[
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "duration_hours": 1,
                "flows": [
                    {
                        "id": "charge",
                        "energy": 10,
                        "target": "battery",
                        "carrier": "electricity",
                    }
                ],
                "accumulations": [
                    {
                        "component": "battery",
                        "energy_change": 10,
                        "carrier": "electricity",
                    }
                ],
            },
            {
                "timestamp": "2026-01-01T01:00:00Z",
                "duration_hours": 1,
                "flows": [
                    {
                        "id": "battery output",
                        "energy": 8,
                        "source": "battery",
                        "target": "load",
                        "carrier": "electricity",
                    },
                    {
                        "id": "delivered",
                        "energy": 8,
                        "source": "load",
                        "carrier": "electricity",
                    },
                ],
                "accumulations": [
                    {
                        "component": "battery",
                        "energy_change": -10,
                        "carrier": "electricity",
                    }
                ],
            },
        ],
    )

    assert result.record_count == 2
    assert result.aggregate_energy["input_energy"] == pytest.approx(10)
    assert result.aggregate_energy["product_energy"] == pytest.approx(8)
    assert result.aggregate_energy["accumulation_energy"] == pytest.approx(0)
    assert result.aggregate_energy["efficiency"] == pytest.approx(0.8)
    assert result.aggregate_exergy["destruction_exergy"] == pytest.approx(2)
    assert result.aggregate_exergy["exergetic_efficiency"] == pytest.approx(0.8)
    jsonschema.validate(result.to_dict(), xi.load_schema("system-timeseries"))


def test_timeseries_rejects_duplicate_timestamps_and_power_ambiguity():
    record = {
        "timestamp": "same",
        "flows": [
            {
                "id": "input",
                "energy": 1,
                "target": "load",
                "exergy_factor": 1,
            },
            {
                "id": "output",
                "energy": 1,
                "source": "load",
                "exergy_factor": 1,
            },
        ],
    }
    with pytest.raises(ValueError, match="duplicate"):
        xi.analyze_system_timeseries(
            "duplicate",
            components=[{"id": "load", "kind": "converter"}],
            records=[record, record],
        )
