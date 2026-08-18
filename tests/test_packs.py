import json

import jsonschema
import pytest

import exergy_imperative as xi
from exergy_imperative.cli import main


def _custom_pack():
    return {
        "schema_version": "1.0",
        "id": "test-pack",
        "version": "2026.1",
        "license": "CC-BY-4.0",
        "description": "Test-only sourced converter and process.",
        "domains": ["tests"],
        "sources": {
            "test-source": {
                "title": "Test engineering record",
                "license": "CC-BY-4.0",
                "applicable_boundary": "Delivered electricity to shaft work",
            }
        },
        "profiles": {
            "technology": [
                {
                    "id": "test-converter",
                    "label": "Test converter",
                    "model": "converter",
                    "input_carrier": "electricity",
                    "output_carrier": "shaft-work",
                    "performance_parameter": "efficiency",
                    "source_id": "test-source",
                    "boundary": "Delivered electricity to shaft work",
                    "parameters": {
                        "efficiency": {
                            "value": 0.8,
                            "unit": "shaft work/electricity input",
                            "low": 0.7,
                            "high": 0.9,
                            "confidence": "screening prior",
                        }
                    },
                }
            ]
        },
        "process_templates": [
            {
                "id": "test-process",
                "label": "Test process",
                "sector": "tests",
                "technology": "test-converter",
                "description": "Integrated test process.",
                "screening_savings_fraction": {
                    "value": 0.1,
                    "low": 0.05,
                    "high": 0.2,
                },
                "major_pollutants": [],
                "priority_inputs": ["measured efficiency"],
                "source_id": "test-source",
            }
        ],
        "metadata": {},
    }


def test_custom_pack_extends_assessment_and_process_without_global_mutation():
    pack = xi.load_technology_pack(_custom_pack())
    validated = xi.validate_technology_pack(pack)
    result = xi.assess_with_pack(pack, technology="test converter", energy=10)
    process = xi.assess_process_with_pack(pack, "test process", energy=10)

    assert validated["valid"] is True
    assert result.useful_energy.value == pytest.approx(8)
    assert process.template.id == "test-process"
    with pytest.raises(xi.ProfileNotFoundError):
        xi.assess(technology="test converter", energy=10)


def test_pack_requires_sources_ranges_licenses_and_boundaries():
    payload = _custom_pack()
    del payload["sources"]["test-source"]["license"]
    with pytest.raises(ValueError, match="license"):
        xi.load_technology_pack(payload)

    payload = _custom_pack()
    del payload["profiles"]["technology"][0]["parameters"]["efficiency"]["high"]
    with pytest.raises(ValueError, match="low and high"):
        xi.load_technology_pack(payload)


def test_published_estimate_contract_requires_source_version_and_applicability():
    payload = _custom_pack()
    parameter = payload["profiles"]["technology"][0]["parameters"]["efficiency"]
    parameter.update(
        {
            "source_id": "test-source",
            "source_version": "test-table-v1",
            "evidence_kind": "published_estimate",
            "statistic": "published representative value",
            "range_basis": "published minimum and maximum",
            "applicability": {
                "technology": "test converter",
                "boundary": "delivered electricity to shaft work",
                "geography": "test geography",
                "vintage": "test vintage",
            },
        }
    )
    assert xi.load_technology_pack(payload)

    del parameter["applicability"]["geography"]
    with pytest.raises(ValueError, match="applicability requires geography"):
        xi.load_technology_pack(payload)

    payload = _custom_pack()
    parameter = payload["profiles"]["technology"][0]["parameters"]["efficiency"]
    parameter["source_id"] = "unknown-source"
    with pytest.raises(ValueError, match="unknown source"):
        xi.load_technology_pack(payload)


def test_bundled_packs_and_scaffold_are_schema_valid(tmp_path):
    schema = xi.load_schema("technology-pack")
    assert set(xi.list_bundled_technology_packs()) == {
        "advanced-materials",
        "buildings",
        "emerging-energy",
        "oil-gas",
        "power",
        "mobility",
        "water-materials",
    }
    for name in xi.list_bundled_technology_packs():
        pack = xi.load_technology_pack(name)
        jsonschema.validate(pack.to_dict(), schema)
        assert xi.validate_technology_pack(pack)["valid"]

    oil_gas = xi.load_technology_pack("oil-gas")
    assert len(oil_gas.material_templates) >= 5
    assert oil_gas.registry().get("technology", "pipeline compressor")
    advanced = xi.load_technology_pack("advanced-materials")
    assert len(advanced.material_templates) >= 8

    compressor = xi.assess_with_pack(
        "oil-gas",
        technology="pipeline compressor",
        energy=10,
        efficiency=0.8,
    )
    assert compressor.useful_energy.value == pytest.approx(8)
    geothermal = xi.assess_with_pack(
        "emerging-energy",
        technology="EGS",
        energy=100,
        efficiency=0.15,
        input_exergy_factor=0.4,
    )
    assert geothermal.useful_energy.value == pytest.approx(15)
    dri = xi.assess_with_pack(
        "advanced-materials",
        technology="H2 DRI",
        energy=100,
        efficiency=0.5,
    )
    assert dri.useful_exergy.value == pytest.approx(50)

    target = tmp_path / "my-pack.json"
    assert xi.write_technology_pack_template(target) == target
    scaffold = json.loads(target.read_text(encoding="utf-8"))
    jsonschema.validate(scaffold, schema)
    assert xi.validate_technology_pack(scaffold)["valid"]
    with pytest.raises(FileExistsError):
        xi.write_technology_pack_template(target)


@pytest.mark.parametrize(
    ("pack", "technology", "energy", "expected", "low", "high"),
    [
        ("buildings", "ground-source heat pump", 10, 36, 31, 48),
        ("power", "gas-turbine generator", 10, 2.94, 2.23, 3.47),
        ("mobility", "electric vehicle drivetrain", 10, 8.9, 8.7, 9.1),
        ("oil-gas", "pipeline compressor", 10, 8.75, 8.4, 9.1),
        ("emerging-energy", "alkaline electrolyzer", 100, 61, 61, 70),
        ("emerging-energy", "redox-flow battery", 100, 72, 67, 77),
        ("emerging-energy", "pumped-thermal energy storage", 100, 62, 52, 72),
    ],
)
def test_bundled_published_priors_are_bounded_sourced_and_explicitly_labeled(
    pack, technology, energy, expected, low, high
):
    result = xi.assess_with_pack(pack, technology=technology, energy=energy)
    name = "cop" if "cop" in result.parameters else "efficiency"
    parameter = result.parameters[name]

    assert result.tier is xi.FidelityTier.F1
    assert result.useful_energy.value == pytest.approx(expected)
    assert result.useful_energy.low == pytest.approx(low)
    assert result.useful_energy.high == pytest.approx(high)
    assert parameter.status is xi.ValueStatus.PUBLISHED_ESTIMATE
    assert parameter.source_id in result.source_catalog
    assert parameter.source_version
    assert parameter.evidence_kind == "published_estimate"
    assert parameter.statistic
    assert parameter.range_basis
    assert set(parameter.applicability) >= {
        "technology",
        "boundary",
        "geography",
        "vintage",
    }
    assert any("not measured site performance" in item for item in result.warnings)
    jsonschema.validate(result.to_dict(), xi.load_schema("assessment"))


def test_published_prior_can_be_overridden_refined_or_rejected_in_strict_mode():
    result = xi.assess_with_pack(
        "buildings", technology="ground-source heat pump", energy=10
    )
    refined = result.refine(cop=4.2)
    direct = xi.assess_with_pack(
        "buildings", technology="ground-source heat pump", energy=10, cop=4.0
    )

    assert refined.useful_energy.value == pytest.approx(42)
    assert refined.parameters["cop"].status is xi.ValueStatus.PROVIDED
    assert not any("published F1" in item for item in refined.warnings)
    assert direct.useful_energy.value == pytest.approx(40)
    with pytest.raises(xi.MissingInputError, match="strict mode"):
        xi.assess_with_pack(
            "buildings",
            technology="ground-source heat pump",
            energy=10,
            strict=True,
        )


def test_agent_recipe_serializes_published_prior_and_retains_recovery_hint():
    recipe = {
        "workflow": "custom-assessment",
        "inputs": {
            "pack": "buildings",
            "assessment": {
                "technology": "ground-source heat pump",
                "energy": 10,
            },
        },
    }
    response = xi.safe_run_recipe(recipe)

    assert response["ok"] is True
    assert response["result"]["parameters"]["cop"]["status"] == "published_estimate"
    assert response["result"]["parameters"]["cop"]["applicability"]["boundary"]

    recipe["inputs"]["assessment"]["strict"] = True
    strict = xi.safe_run_recipe(recipe)
    assert strict["error"]["code"] == "MISSING_INPUT"
    assert "non-strict screening profile" in strict["error"]["hint"]


def test_conditional_published_prior_selects_context_and_discloses_fallback():
    payload = _custom_pack()
    parameter = payload["profiles"]["technology"][0]["parameters"]["efficiency"]
    parameter.update(
        {
            "source_id": "test-source",
            "source_version": "test-table-v1",
            "evidence_kind": "published_estimate",
            "statistic": "family midpoint",
            "range_basis": "family range",
            "applicability": {
                "technology": "test converter family",
                "boundary": "delivered electricity to shaft work",
                "geography": "test geography",
                "vintage": "test vintage",
            },
            "variants": [
                {
                    "id": "large-converter",
                    "when": {
                        "equipment_class": "large",
                        "capacity_kw": {"gte": 50},
                    },
                    "value": 0.9,
                    "low": 0.88,
                    "high": 0.92,
                    "statistic": "large-equipment table midpoint",
                    "range_basis": "large-equipment table range",
                }
            ],
        }
    )
    pack = xi.load_technology_pack(payload)

    selected = xi.assess_with_pack(
        pack,
        technology="test converter",
        energy=10,
        estimate_context={"equipment_class": "large", "capacity_kw": 100},
    )
    fallback = xi.assess_with_pack(pack, technology="test converter", energy=10)

    assert selected.useful_energy.value == pytest.approx(9)
    assert selected.parameters["efficiency"].estimate_variant == "large-converter"
    assert selected.parameters["efficiency"].selection_basis == "conditional_context"
    assert selected.parameters["efficiency"].selection_context == {
        "capacity_kw": 100,
        "equipment_class": "large",
    }
    assert fallback.useful_energy.value == pytest.approx(8)
    assert fallback.parameters["efficiency"].selection_basis == "family_fallback"
    assert any("family fallback" in item for item in fallback.warnings)


def test_conditional_prior_rejects_invalid_rules_and_nonfinite_context():
    payload = _custom_pack()
    payload["profiles"]["technology"][0]["parameters"]["efficiency"]["variants"] = [
        {"id": "bad", "when": {"capacity_kw": {"approximately": 10}}}
    ]
    with pytest.raises(ValueError, match="unknown condition operators"):
        xi.load_technology_pack(payload)

    with pytest.raises(ValueError, match="must be finite"):
        xi.assess_with_pack(
            _custom_pack(),
            technology="test converter",
            energy=10,
            estimate_context={"capacity_kw": float("nan")},
        )


def test_mass_normalized_intensity_is_separate_and_overridable():
    payload = _custom_pack()
    payload["profiles"]["intensity"] = [
        {
            "id": "test-converter-intensity",
            "label": "Test converter product intensity",
            "technology": "test-converter",
            "energy_carrier": "electricity",
            "output_material": "test product",
            "source_id": "test-source",
            "boundary": "Electricity at equipment terminals per tonne of test product",
            "parameters": {
                "specific_energy": {
                    "value": 2.0,
                    "unit": "MWh/t",
                    "low": 1.5,
                    "high": 2.5,
                    "confidence": "screening range",
                    "source_id": "test-source",
                    "source_version": "2026 test edition",
                    "evidence_kind": "published_estimate",
                    "statistic": "Illustrative midpoint",
                    "range_basis": "Illustrative published range",
                    "applicability": {
                        "technology": "Test converter",
                        "boundary": "Equipment electricity per product mass",
                        "geography": "Test geography",
                        "vintage": "2026",
                    },
                }
            },
        }
    ]
    result = xi.assess_intensity_with_pack(
        payload, "test-converter-intensity", 2000, output_unit="kg"
    )
    assert result.input_energy.value == pytest.approx(4.0)
    assert result.input_energy.low == pytest.approx(3.0)
    assert result.input_energy.high == pytest.approx(5.0)
    assert result.specific_energy.status == xi.ValueStatus.PUBLISHED_ESTIMATE
    assert result.to_dict()["model"] == "mass-normalized-energy-intensity"
    assert "useful_energy" not in result.to_dict()

    overridden = xi.assess_intensity_with_pack(
        payload,
        "test-converter-intensity",
        2,
        specific_energy_mwh_per_tonne=1.25,
    )
    assert overridden.input_energy.value == pytest.approx(2.5)
    assert overridden.tier == xi.FidelityTier.F2

    with pytest.raises(ValueError, match="strict mode rejects"):
        xi.assess_intensity_with_pack(
            payload, "test-converter-intensity", 2, strict=True
        )


def test_energy_performance_screen_does_not_invent_heat_exergy_quality():
    result = xi.assess_performance_with_pack(
        "emerging-energy",
        "concentrating-solar-power-block",
        100,
    )

    assert result.output_energy.value == pytest.approx(40)
    assert result.output_energy.low == pytest.approx(35)
    assert result.output_energy.high == pytest.approx(45)
    assert result.performance.status is xi.ValueStatus.PUBLISHED_ESTIMATE
    assert result.tier is xi.FidelityTier.F1
    assert "exergy" not in result.to_dict()
    assert not any("input_exergy" in key for key in result.to_dict())
    jsonschema.validate(result.to_dict(), xi.load_schema("technology-performance"))

    overridden = xi.assess_performance_with_pack(
        "emerging-energy",
        "concentrating-solar-power-block",
        100,
        performance=0.42,
    )
    assert overridden.output_energy.value == pytest.approx(42)
    assert overridden.tier is xi.FidelityTier.F2

    with pytest.raises(ValueError, match="strict mode rejects"):
        xi.assess_performance_with_pack(
            "emerging-energy",
            "concentrating-solar-power-block",
            100,
            strict=True,
        )

    custom_default = xi.assess_performance_with_pack(
        _custom_pack(), "test-converter", 10
    )
    assert custom_default.output_energy.value == pytest.approx(8)
    assert custom_default.tier is xi.FidelityTier.F1
    jsonschema.validate(
        custom_default.to_dict(), xi.load_schema("technology-performance")
    )

    explicit_pack = _custom_pack()
    explicit_pack["profiles"]["technology"][0]["parameters"] = {}
    explicit_pack["profiles"]["technology"][0]["required_inputs"] = ["efficiency"]
    explicit = xi.assess_performance_with_pack(
        explicit_pack, "test-converter", 10, performance=0.75
    )
    assert explicit.output_energy.value == pytest.approx(7.5)
    assert explicit.tier is xi.FidelityTier.F2


def test_every_bundled_technology_has_a_machine_readable_default_status():
    reports = [
        xi.technology_pack_coverage(name) for name in xi.list_bundled_technology_packs()
    ]
    entries = [item for report in reports for item in report["coverage"]]

    assert len(entries) == 80
    assert (
        sum(item["status"] == "automatic_screening_estimate" for item in entries) == 50
    )
    for item in entries:
        assert item["boundary"]
        if item["status"] == "automatic_screening_estimate":
            assert item["available_estimates"]
            assert all(
                estimate["source_id"] for estimate in item["available_estimates"]
            )
        else:
            assert item["required_inputs"]
            assert item["reason"]


def test_every_bundled_performance_prior_executes_as_an_energy_screen():
    count = 0
    for pack_name in xi.list_bundled_technology_packs():
        pack = xi.load_technology_pack(pack_name)
        for profile in pack.profiles.get("technology", ()):
            parameter_name = profile.get("performance_parameter")
            if parameter_name not in profile.get("parameters", {}):
                continue
            result = xi.assess_performance_with_pack(
                pack,
                str(profile["id"]),
                1.0,
            )
            assert result.output_energy.low <= result.output_energy.value
            assert result.output_energy.value <= result.output_energy.high
            assert result.performance.source_id in result.source_catalog
            assert result.performance.applicability["boundary"]
            count += 1
    assert count == 48


def test_every_bundled_intensity_prior_executes_and_keeps_product_boundary():
    count = 0
    for pack_name in xi.list_bundled_technology_packs():
        pack = xi.load_technology_pack(pack_name)
        for profile in pack.profiles.get("intensity", ()):
            result = xi.assess_intensity_with_pack(pack, str(profile["id"]), 1.0)
            assert result.input_energy.low <= result.input_energy.value
            assert result.input_energy.value <= result.input_energy.high
            assert result.specific_energy.source_id in result.source_catalog
            assert result.output_material == profile["output_material"]
            jsonschema.validate(
                result.to_dict(), xi.load_schema("technology-intensity")
            )
            count += 1
    assert count == 3


def test_intensity_profile_rejects_wrong_functional_unit():
    payload = _custom_pack()
    payload["profiles"]["intensity"] = [
        {
            "id": "bad-intensity",
            "label": "Bad intensity",
            "technology": "test-converter",
            "energy_carrier": "electricity",
            "output_material": "product",
            "source_id": "test-source",
            "boundary": "Test boundary",
            "parameters": {
                "specific_energy": {
                    "value": 1.0,
                    "unit": "kWh/item",
                    "confidence": "exact",
                }
            },
        }
    ]
    with pytest.raises(ValueError, match="unit must be MWh/t"):
        xi.load_technology_pack(payload)


def test_pack_cli_search_validation_and_scaffold(tmp_path, capsys):
    assert main(["search", "ground source", "--json"]) == 0
    matches = json.loads(capsys.readouterr().out)["matches"]
    assert any(item["kind"] == "pack" for item in matches)

    assert main(["pack-validate", "buildings", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True

    assert main(["pack-coverage", "emerging-energy", "--json"]) == 0
    coverage = json.loads(capsys.readouterr().out)
    assert coverage["automatic_estimate_count"] == 15

    assert (
        main(
            [
                "performance",
                "emerging-energy",
                "concentrating-solar-power-block",
                "100",
                "--json",
            ]
        )
        == 0
    )
    performance = json.loads(capsys.readouterr().out)
    assert performance["output_energy"]["value"] == pytest.approx(40)

    target = tmp_path / "pack.json"
    assert main(["pack-scaffold", str(target), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["output"] == str(target)


def test_pack_and_system_agent_workflows_are_validated_and_dispatched():
    custom = xi.safe_run_recipe(
        {
            "workflow": "custom-assessment",
            "inputs": {
                "pack": _custom_pack(),
                "assessment": {"technology": "test-converter", "energy": 10},
            },
        }
    )
    assert custom["ok"] is True
    assert custom["result"]["results"]["useful_energy"]["value"] == pytest.approx(8)

    process = xi.safe_run_recipe(
        {
            "workflow": "custom-process-assessment",
            "inputs": {
                "pack": _custom_pack(),
                "template": "test-process",
                "energy": 10,
            },
        }
    )
    assert process["ok"] is True
    assert process["result"]["template"]["id"] == "test-process"

    performance = xi.safe_run_recipe(
        {
            "workflow": "technology-performance",
            "inputs": {
                "pack": "power",
                "technology": "wind-turbine",
                "input_energy": 100,
            },
        }
    )
    assert performance["ok"] is True
    assert performance["result"]["output_energy"]["value"] == pytest.approx(37.5)

    system = xi.safe_run_recipe(
        {"workflow": "system-analysis", "inputs": _simple_system()}
    )
    assert system["ok"] is True
    assert system["result"]["exergy"]["exergetic_efficiency"] == pytest.approx(0.8)

    invalid = xi.safe_run_recipe(
        {
            "workflow": "system-analysis",
            "inputs": {
                "name": "bad",
                "components": [{"id": "c", "kind": "magic"}],
                "flows": [],
            },
        },
        mode="validate-only",
    )
    assert invalid["error"]["code"] == "INVALID_INPUT_VALUE"


def test_pack_recipe_validate_only_does_not_read_missing_local_path(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    response = xi.safe_run_recipe(
        {
            "workflow": "technology-pack-validation",
            "inputs": {"pack": str(missing)},
        },
        mode="validate-only",
    )

    assert response["ok"] is True
    assert response["plan"]["will_execute_calculations"] is False
    assert not missing.exists()


def _simple_system():
    return {
        "name": "converter",
        "components": [{"id": "converter", "kind": "converter"}],
        "flows": [
            {
                "id": "input",
                "energy": 10,
                "target": "converter",
                "exergy_factor": 1,
            },
            {
                "id": "product",
                "energy": 8,
                "source": "converter",
                "exergy_factor": 1,
            },
            {
                "id": "loss",
                "energy": 2,
                "source": "converter",
                "role": "loss",
                "exergy": 0,
            },
        ],
    }
