import json

import pytest

import exergy_imperative as xi


def test_gas_boiler_works_with_minimal_inputs():
    result = xi.assess(
        technology="gas boiler",
        service="space heating",
        energy=1000,
        unit="MWh",
    )
    assert result.tier is xi.FidelityTier.F1
    assert result.input_exergy.value == pytest.approx(930)
    assert result.useful_exergy.value > 0
    assert result.exergetic_efficiency.value < 0.2
    assert "efficiency" in result.assumptions
    assert result.refinement_opportunities()[0].priority == "high"


def test_missing_energy_returns_normalized_result():
    result = xi.assess(technology="heat pump")
    assert result.normalized
    assert result.input_energy.value == pytest.approx(1)
    assert result.input_energy.unit == "MWh"


def test_refine_replaces_defaults_and_uses_integrated_method():
    original = xi.assess(technology="gas boiler")
    refined = original.refine(
        efficiency=0.93,
        source_temperature="65 C",
        return_temperature="45 C",
        ambient_temperature="5 C",
        input_exergy_factor=0.94,
    )
    assert refined.tier is xi.FidelityTier.F2
    assert "sensible-stream" in refined.method_id
    assert refined.parameters["efficiency"].status is xi.ValueStatus.PROVIDED
    assert refined.parameters["return_temperature_c"].value == pytest.approx(45)


def test_strict_mode_rejects_assumptions():
    with pytest.raises(xi.MissingInputError, match="strict mode"):
        xi.assess(technology="gas boiler", strict=True)


def test_strict_mode_accepts_complete_explicit_case():
    result = xi.assess(
        technology="gas boiler",
        source_temperature=65,
        ambient_temperature=20,
        efficiency=0.93,
        input_exergy_factor=0.94,
        strict=True,
    )
    assert result.tier is xi.FidelityTier.F2


def test_strict_mode_ignores_service_temperatures_when_output_factor_is_explicit():
    result = xi.assess(
        technology="gas boiler",
        efficiency=0.93,
        input_exergy_factor=0.94,
        output_exergy_factor=0.1,
        source_temperature=80,
        ambient_temperature=20,
        strict=True,
    )
    assert result.tier is xi.FidelityTier.F2
    assert result.exergy_factor.value == pytest.approx(0.1)
    assert "source_temperature_c" not in result.parameters
    assert "ambient_temperature_c" not in result.parameters
    assert not {
        "source_temperature",
        "return_temperature",
        "ambient_temperature",
    } & {item.field for item in result.refinements}
    assert any("ignored" in warning for warning in result.warnings)


def test_direct_assessment_rejects_conflicting_input_and_output_boundaries():
    with pytest.raises(ValueError, match="different boundaries"):
        xi.assess(service="space heating", carrier="electricity", energy=1)
    with pytest.raises(ValueError, match="different boundaries"):
        xi.assess(service="space heating", input_exergy_factor=1.0, energy=1)


def test_direct_electricity_assessment():
    result = xi.assess(carrier="electricity", energy=500, unit="kWh")
    assert result.exergy_factor.value == pytest.approx(1)
    assert result.useful_exergy.value == pytest.approx(0.5)
    assert "exergy_factor" in result.parameters
    assert "input_exergy_factor" not in result.parameters


def test_direct_district_heat_assessment():
    result = xi.assess(service="district heating", energy=1, unit="MWh")
    assert result.exergy_factor.value == pytest.approx(0.1698994761)
    assert result.tier is xi.FidelityTier.F1


def test_explicit_temperature_units():
    result = xi.assess(
        service="district heating",
        source_temperature="176 F",
        ambient_temperature="68 F",
    )
    assert result.exergy_factor.value == pytest.approx(
        xi.thermal_exergy_factor_c(80, 20)
    )


def test_cooling_and_chiller_profiles():
    service = xi.assess(service="chilled water", energy=1)
    chiller = xi.assess(technology="electric chiller", energy=1)
    assert service.exergy_factor.value == pytest.approx(
        xi.cooling_exergy_factor_c(7, 30)
    )
    assert 0 < chiller.exergetic_efficiency.value < 1


def test_hydrogen_technology_chain_profiles():
    electrolyzer = xi.assess(technology="pem electrolyzer")
    fuel_cell = xi.assess(technology="pem fuel cell")
    assert electrolyzer.exergetic_efficiency.value == pytest.approx(0.675 * 0.98)
    assert fuel_cell.exergetic_efficiency.value == pytest.approx(0.50 / 0.98)


def test_technology_basis_switch_requires_matching_explicit_performance():
    with pytest.raises(ValueError, match="requires an explicit efficiency"):
        xi.assess(technology="pem fuel cell", basis="HHV")
    explicit = xi.assess(technology="pem fuel cell", basis="HHV", efficiency=0.42)
    assert explicit.carrier_id == "hydrogen-hhv"
    assert explicit.parameters["efficiency"].value == pytest.approx(0.42)

    with pytest.raises(ValueError, match="requires an explicit efficiency"):
        xi.assess(technology="gas boiler", unit="MWh_LHV")


def test_technology_carrier_override_requires_matching_explicit_performance():
    with pytest.raises(ValueError, match="requires an explicit cop"):
        xi.assess(technology="heat pump", carrier="natural gas")

    explicit = xi.assess(
        technology="heat pump", carrier="natural gas", cop=3.0, energy=1
    )
    assert explicit.carrier_id == "natural-gas-hhv"
    assert explicit.parameters["cop"].value == pytest.approx(3.0)


def test_fixed_output_technology_rejects_service_override():
    with pytest.raises(ValueError, match="fixed output carrier"):
        xi.assess(technology="pem electrolyzer", service="space heating")


def test_basis_selects_matching_carrier_profile():
    result = xi.assess(carrier="natural gas", basis="LHV")
    assert result.exergy_factor.value == pytest.approx(1.04)
    assert result.parameters["basis"].value == "LHV"


def test_basis_selection_preserves_matching_custom_hydrogen_profile(tmp_path):
    pack = tmp_path / "custom-hydrogen.json"
    pack.write_text(
        json.dumps(
            {
                "data_version": "site-hydrogen-v1",
                "sources": {"site": {"title": "Site hydrogen characterization"}},
                "profiles": {
                    "carrier": [
                        {
                            "id": "site-hydrogen",
                            "label": "Site hydrogen",
                            "aliases": ["site h2"],
                            "family": "chemical",
                            "basis": "LHV",
                            "source_id": "site",
                            "parameters": {
                                "exergy_factor": {
                                    "value": 0.91,
                                    "unit": "MWh_ex/MWh_LHV",
                                }
                            },
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    result = xi.assess(
        carrier="site h2", basis="LHV", registry=xi.load_registry_pack(pack)
    )

    assert result.carrier_id == "site-hydrogen"
    assert result.exergy_factor.value == pytest.approx(0.91)
    assert result.parameters["exergy_factor"].source_id == "site"


def test_custom_cooling_profile_reports_only_actual_missing_inputs(tmp_path):
    pack = tmp_path / "custom-cooling.json"
    pack.write_text(
        json.dumps(
            {
                "data_version": "site-cooling-v1",
                "profiles": {
                    "service": [
                        {
                            "id": "site-cooling",
                            "label": "Site cooling",
                            "family": "cooling",
                            "source_id": "site",
                            "parameters": {
                                "ambient_temperature_c": {
                                    "value": 30.0,
                                    "unit": "C",
                                }
                            },
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    registry = xi.load_registry_pack(pack)

    incomplete = xi.assess(service="site cooling", registry=registry)

    assert incomplete.tier is xi.FidelityTier.F0
    assert incomplete.missing == ["cold_temperature"]
    complete = xi.assess(
        service="site cooling", cold_temperature=7.0, registry=registry
    )
    assert complete.exergy_factor is not None


def test_custom_service_rejects_unordered_temperature_ranges(tmp_path):
    pack = tmp_path / "invalid-temperature-range.json"
    pack.write_text(
        json.dumps(
            {
                "data_version": "invalid-temperature-v1",
                "profiles": {
                    "service": [
                        {
                            "id": "invalid-heat",
                            "label": "Invalid heat profile",
                            "family": "thermal",
                            "source_id": "site",
                            "parameters": {
                                "source_temperature_c": {
                                    "value": 80.0,
                                    "unit": "C",
                                    "low": 100.0,
                                    "high": 110.0,
                                },
                                "ambient_temperature_c": {
                                    "value": 20.0,
                                    "unit": "C",
                                    "low": 15.0,
                                    "high": 25.0,
                                },
                            },
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="range must satisfy low <= value <= high"):
        xi.assess(service="invalid heat", registry=xi.load_registry_pack(pack))


def test_custom_service_screening_range_contains_central_factor(tmp_path):
    pack = tmp_path / "crossing-temperature-range.json"
    pack.write_text(
        json.dumps(
            {
                "data_version": "crossing-temperature-v1",
                "profiles": {
                    "service": [
                        {
                            "id": "crossing-heat",
                            "label": "Crossing heat profile",
                            "family": "thermal",
                            "source_id": "site",
                            "parameters": {
                                "source_temperature_c": {
                                    "value": 80.0,
                                    "unit": "C",
                                    "low": 20.0,
                                    "high": 100.0,
                                },
                                "ambient_temperature_c": {
                                    "value": 79.0,
                                    "unit": "C",
                                    "low": 0.0,
                                    "high": 90.0,
                                },
                            },
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    result = xi.assess(service="crossing heat", registry=xi.load_registry_pack(pack))

    assert result.exergy_factor.low == pytest.approx(0.0)
    assert result.exergy_factor.value <= result.exergy_factor.high


def test_integrated_heat_range_includes_constrained_source_return_boundary():
    result = xi.assess(service="space heating", return_temperature=45)

    assert result.exergy_factor.low == pytest.approx(xi.thermal_exergy_factor_c(45, 25))
    assert result.exergy_factor.low <= xi.sensible_heat_exergy_factor_c(46, 45, 25)


def test_custom_cooling_screening_range_includes_equality_boundary(tmp_path):
    pack = tmp_path / "crossing-cooling-range.json"
    pack.write_text(
        json.dumps(
            {
                "data_version": "crossing-cooling-v1",
                "profiles": {
                    "service": [
                        {
                            "id": "crossing-cooling",
                            "label": "Crossing cooling profile",
                            "family": "cooling",
                            "source_id": "site",
                            "parameters": {
                                "cold_temperature_c": {
                                    "value": 7.0,
                                    "unit": "C",
                                    "low": 0.0,
                                    "high": 20.0,
                                },
                                "ambient_temperature_c": {
                                    "value": 8.0,
                                    "unit": "C",
                                    "low": 5.0,
                                    "high": 30.0,
                                },
                            },
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    result = xi.assess(service="crossing cooling", registry=xi.load_registry_pack(pack))

    assert result.exergy_factor.low == pytest.approx(0.0)
    assert result.exergy_factor.value <= result.exergy_factor.high


def test_technology_ratio_rejects_zero_carrier_lower_bound(tmp_path):
    pack = tmp_path / "zero-bound-carrier.json"
    pack.write_text(
        json.dumps(
            {
                "data_version": "zero-bound-v1",
                "profiles": {
                    "carrier": [
                        {
                            "id": "uncertain-electricity",
                            "label": "Uncertain electricity",
                            "family": "work",
                            "source_id": "site",
                            "parameters": {
                                "exergy_factor": {
                                    "value": 1.0,
                                    "unit": "MWh_ex/MWh",
                                    "low": 0.0,
                                    "high": 1.0,
                                }
                            },
                        }
                    ],
                    "technology": [
                        {
                            "id": "uncertain-motor",
                            "label": "Uncertain motor",
                            "model": "converter",
                            "input_carrier": "uncertain-electricity",
                            "output_carrier": "electricity",
                            "performance_parameter": "efficiency",
                            "source_id": "site",
                            "parameters": {
                                "efficiency": {
                                    "value": 0.9,
                                    "unit": "dimensionless",
                                }
                            },
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="lower bound must be positive"):
        xi.assess(technology="uncertain motor", registry=xi.load_registry_pack(pack))


def test_typed_unit_selects_fuel_basis_and_rejects_explicit_conflict():
    result = xi.assess(carrier="natural gas", energy=1, unit="MWh_LHV")
    assert result.carrier_id == "methane-lhv"
    assert result.exergy_factor.value == pytest.approx(1.04)
    assert result.parameters["basis"].value == "LHV"
    assert result.impacts().assumptions["combustion_factor"]["basis"] == "LHV"
    with pytest.raises(ValueError, match="conflicts with typed unit"):
        xi.assess(carrier="natural gas", unit="MWh_LHV", basis="HHV")


def test_explicit_basis_is_validated_without_a_carrier_lookup():
    with pytest.raises(ValueError, match="basis must be HHV or LHV"):
        xi.assess(exergy_factor=0.5, basis="bogus")

    result = xi.assess(exergy_factor=0.5, basis=" lhv ")
    assert result.parameters["basis"].value == "LHV"


def test_provenance_only_inputs_do_not_promote_fidelity():
    stream = xi.assess(carrier="electricity", location="Denver")
    technology = xi.assess(technology="gas boiler", location="Denver")
    assert stream.tier is xi.FidelityTier.F1
    assert technology.tier is xi.FidelityTier.F1


def test_model_inputs_promote_fidelity():
    assert (
        xi.assess(carrier="electricity", exergy_factor=0.99).tier is xi.FidelityTier.F2
    )


def test_irrelevant_temperature_does_not_promote_fidelity():
    cooling = xi.assess(service="chilled water", source_temperature=100)
    heating = xi.assess(service="district heating", cold_temperature=5)
    assert cooling.tier is xi.FidelityTier.F1
    assert heating.tier is xi.FidelityTier.F1


def test_empty_assessment_returns_f0():
    result = xi.assess()
    assert result.tier is xi.FidelityTier.F0
    assert result.missing


def test_unknown_profile_fails_loudly():
    with pytest.raises(xi.ProfileNotFoundError):
        xi.assess(technology="perpetual motion machine")


def test_result_is_json_serializable():
    result = xi.assess(technology="gas boiler")
    payload = result.to_dict()
    json.dumps(payload)
    assert payload["registry_version"] == "2026.2"
    assert payload["tier"] == "F1"


def test_negative_energy_and_invalid_efficiency_are_rejected():
    with pytest.raises(ValueError, match="nonnegative"):
        xi.assess(carrier="electricity", energy=-1)
    with pytest.raises(ValueError, match="must not exceed"):
        xi.assess(technology="gas boiler", efficiency=1.1)


def test_zero_energy_technology_period_is_valid():
    result = xi.assess(technology="gas boiler", energy=0)
    assert result.input_exergy.value == pytest.approx(0)
    assert result.useful_exergy.value == pytest.approx(0)
    assert result.exergetic_efficiency.value > 0


def test_strict_mode_rejects_lookup_output_carrier_factor():
    with pytest.raises(xi.MissingInputError, match="output_exergy_factor"):
        xi.assess(
            technology="pem electrolyzer",
            efficiency=0.7,
            input_exergy_factor=1.0,
            strict=True,
        )
    explicit = xi.assess(
        technology="pem electrolyzer",
        efficiency=0.7,
        input_exergy_factor=1.0,
        output_exergy_factor=0.98,
        strict=True,
    )
    assert explicit.tier is xi.FidelityTier.F2


def test_ambiguous_factor_for_technology_is_rejected():
    with pytest.raises(ValueError, match="make the boundary explicit"):
        xi.assess(technology="gas boiler", exergy_factor=0.9)


@pytest.mark.parametrize(
    "factors",
    [
        {"exergy_factor": 0.5, "input_exergy_factor": 0.4},
        {"exergy_factor": 0.5, "output_exergy_factor": 0.2},
        {"input_exergy_factor": 0.4, "output_exergy_factor": 0.2},
    ],
)
def test_direct_stream_rejects_competing_custom_factors(factors):
    with pytest.raises(ValueError, match="mutually exclusive"):
        xi.assess(**factors)


@pytest.mark.parametrize("performance", [{"efficiency": 0.5}, {"cop": 3.0}])
def test_stream_assessment_rejects_performance_without_technology(performance):
    with pytest.raises(ValueError, match="require a technology boundary"):
        xi.assess(service="space heating", **performance)


def test_direct_supplied_input_factor_uses_custom_method_provenance():
    result = xi.assess(input_exergy_factor=0.5, energy=1)
    assert result.method_id == "stream.custom-input-factor.v1"
    assert result.parameters["exergy_factor"].status is xi.ValueStatus.PROVIDED


def test_custom_registry_profile_rejects_negative_exergy_factor(tmp_path):
    pack = tmp_path / "invalid-factor.json"
    pack.write_text(
        __import__("json").dumps(
            {
                "profiles": {
                    "carrier": [
                        {
                            "id": "invalid-carrier",
                            "parameters": {
                                "exergy_factor": {
                                    "value": -1,
                                    "low": -2,
                                    "high": -0.5,
                                }
                            },
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    registry = xi.load_registry_pack(pack)
    with pytest.raises(ValueError, match="exergy factors must be nonnegative"):
        xi.assess(carrier="invalid-carrier", energy=1, registry=registry)


@pytest.mark.parametrize(
    "specification",
    [
        {"value": 0.5, "low": -0.1, "high": 0.8},
        {"value": 0.9, "low": 0.8, "high": 1.1},
    ],
)
def test_custom_technology_rejects_invalid_efficiency_bounds(tmp_path, specification):
    pack = tmp_path / "invalid-performance.json"
    pack.write_text(
        __import__("json").dumps(
            {
                "profiles": {
                    "technology": [
                        {
                            "id": "invalid-machine",
                            "model": "converter",
                            "input_carrier": "electricity",
                            "output_carrier": "electricity",
                            "performance_parameter": "efficiency",
                            "parameters": {"efficiency": specification},
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    registry = xi.load_registry_pack(pack)
    with pytest.raises(ValueError, match="bound|nonnegative"):
        xi.assess(technology="invalid-machine", registry=registry)


def test_quantity_and_quality_interoperability():
    result = xi.from_quantity_quality(
        {"quantity": 1, "unit": "MWh_th", "source_c": 80, "sink_c": 20}
    )
    exported = xi.to_quantity_quality(result)
    assert exported["exergy_factor"] == pytest.approx(0.1698994761)
    assert exported["tier"] == "F2"


def test_quantity_and_quality_round_trip_preserves_normalized_basis():
    result = xi.assess(technology="gas boiler")

    exported = xi.to_quantity_quality(result)
    round_trip = xi.from_quantity_quality(exported)

    assert exported["normalized"] is True
    assert exported["quantity"] == pytest.approx(result.useful_energy.value)
    assert round_trip.normalized is True
    assert round_trip.useful_exergy.value == pytest.approx(result.useful_exergy.value)
    assert "normalized per 1 MWh of input" in round_trip.summary()
    assert "no energy quantity was supplied" not in round_trip.summary()

    refined = round_trip.refine()
    assert refined.normalized is True
    assert refined.useful_exergy.value == pytest.approx(round_trip.useful_exergy.value)

    absolute = round_trip.refine(energy=100)
    assert absolute.normalized is False


def test_quantity_and_quality_export_keeps_technology_output_boundary_consistent():
    result = xi.assess(
        technology="gas boiler",
        energy=10,
        efficiency=0.8,
        source_temperature=80,
        ambient_temperature=20,
        input_exergy_factor=0.95,
    )
    exported = xi.to_quantity_quality(result)
    assert exported["quantity"] == pytest.approx(result.useful_energy.value)
    assert exported["quantity"] * exported["exergy_factor"] == pytest.approx(
        exported["accessible_exergy"]
    )
    round_trip = xi.from_quantity_quality(exported)
    assert round_trip.useful_exergy.value == pytest.approx(result.useful_exergy.value)


def test_direct_custom_factor_strict_mode_ignores_unused_service_defaults():
    result = xi.assess(
        service="space heating", exergy_factor=0.2, energy=1, strict=True
    )
    assert result.useful_exergy.value == pytest.approx(0.2)


def test_direct_custom_factor_bypasses_service_validation_and_refinements():
    result = xi.assess(
        service="space heating",
        exergy_factor=0.2,
        source_temperature=10,
        ambient_temperature=20,
    )
    assert result.useful_exergy.value == pytest.approx(0.2)
    assert not result.refinements
    assert "source_temperature_c" not in result.parameters
    assert any("ignored" in warning for warning in result.warnings)
