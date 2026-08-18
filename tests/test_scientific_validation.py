"""Project-wide scientific assurance and provenance checks.

These tests deliberately distinguish equation/reference validation from
screening defaults, structural contracts, and publisher-owned external data.
"""

from __future__ import annotations

import inspect
import json
import math
import random
from pathlib import Path

import jsonschema
import pytest

import exergy_imperative as xi

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "src" / "exergy_imperative" / "data"


def test_bundled_scientific_suite_is_broad_and_passes():
    cases = xi.load_validation_cases()
    suite = xi.run_bundled_validation_suite()

    assert len(cases) >= 25
    assert suite.total_cases == len(cases)
    assert suite.passed
    assert {item.validation_type for item in cases} >= {
        "analytic",
        "conservation",
        "reference",
        "structural",
    }
    assert all(item.capabilities for item in cases)
    jsonschema.validate(suite.to_dict(), xi.load_schema("validation"))


def test_validation_coverage_is_machine_readable_complete_and_traceable():
    coverage = xi.load_validation_coverage()
    payload = coverage.to_dict()
    jsonschema.validate(payload, xi.load_schema("validation-coverage"))

    case_ids = {case.id for case in xi.load_validation_cases()}
    covered_case_ids = {case_id for item in coverage.items for case_id in item.case_ids}
    assert covered_case_ids <= case_ids
    assert case_ids - covered_case_ids == set()
    assert all(not item.decision_grade for item in coverage.items)
    assert {item.level for item in coverage.items} >= {
        "reference-validated",
        "conservation-validated",
        "screening-only",
        "external-data-required",
        "interface-only",
    }
    for item in coverage.items:
        assert item.public_api
        assert item.limitations
        assert all((ROOT / path).is_file() for path in item.tests)


def test_every_exported_scientific_function_has_a_coverage_classification():
    scientific_modules = {
        "exergy_imperative.assessment",
        "exergy_imperative.balance",
        "exergy_imperative.decision",
        "exergy_imperative.economics",
        "exergy_imperative.engineering",
        "exergy_imperative.factors",
        "exergy_imperative.formulas",
        "exergy_imperative.ghg",
        "exergy_imperative.impacts",
        "exergy_imperative.materials",
        "exergy_imperative.packs",
        "exergy_imperative.processes",
        "exergy_imperative.properties",
        "exergy_imperative.systems",
        "exergy_imperative.technology_models",
        "exergy_imperative.uncertainty",
        "exergy_imperative.units",
        "exergy_imperative.weather",
    }
    exported_functions = {
        name
        for name in xi.__all__
        if inspect.isfunction(getattr(xi, name))
        and getattr(xi, name).__module__ in scientific_modules
    }
    classified = {
        name for item in xi.load_validation_coverage().items for name in item.public_api
    }
    assert exported_functions - classified == set()


def test_primary_emissions_and_gwp_values_are_pinned_to_publisher_tables():
    gwp_expected = {
        "CO2": (1.0, 1.0),
        "CH4-fossil": (82.5, 29.8),
        "CH4-biogenic": (79.7, 27.0),
        "N2O": (273.0, 273.0),
        "HFC-32": (2693.0, 771.0),
        "HFC-134a": (4144.0, 1526.0),
        "CF4": (5301.0, 7380.0),
        "CFC-11": (8321.0, 6226.0),
    }
    for gas, expected in gwp_expected.items():
        factor = xi.DEFAULT_IMPACT_FACTORS.warming_potential(gas)
        assert (factor.gwp20, factor.gwp100) == expected

    # EPA table: 53.06 kg CO2, 1 g CH4, and 0.1 g N2O per MMBtu HHV.
    mwh_per_mmbtu = 1_055.05585262e6 / 3.6e9
    expected_epa = {
        "CO2": 53.06 / mwh_per_mmbtu,
        "CH4-fossil": 0.001 / mwh_per_mmbtu,
        "N2O": 0.0001 / mwh_per_mmbtu,
    }
    actual = xi.DEFAULT_IMPACT_FACTORS.fuel_emissions("natural-gas-hhv")
    for gas, expected in expected_epa.items():
        # The packaged table is rounded to six decimals after conversion.
        assert actual.gases_kg_per_mwh[gas] == pytest.approx(expected, abs=5e-7)

    # IPCC 2006 Tier 1 CO2 values in kg/GJ (numerically equal to t/TJ),
    # converted to kg/MWh on the declared net-calorific-value basis.
    ipcc_co2_kg_per_gj = {
        "methane-lhv": 56.1,
        "diesel-lhv": 74.1,
        "gasoline-lhv": 69.3,
        "coal-lhv": 94.6,
        "lpg-lhv": 63.1,
    }
    for carrier, kg_per_gj in ipcc_co2_kg_per_gj.items():
        factor = xi.DEFAULT_IMPACT_FACTORS.fuel_emissions(carrier)
        assert factor.basis == "LHV"
        assert factor.gases_kg_per_mwh["CO2"] == pytest.approx(
            kg_per_gj * 3.6, abs=1e-12
        )


def test_all_bundled_numerical_sources_declare_license_and_boundary():
    payloads = {
        name: json.loads((DATA / name).read_text(encoding="utf-8"))
        for name in (
            "profiles.json",
            "process_templates.json",
            "impact_factors.json",
            "global_electricity.json",
        )
    }
    for filename, payload in payloads.items():
        sources = payload.get("sources")
        assert sources, f"{filename} has no source catalog"
        for source_id, source in sources.items():
            assert source.get("title"), f"{filename}:{source_id} has no title"
            assert source.get("license"), f"{filename}:{source_id} has no license"
            assert source.get("applicable_boundary"), (
                f"{filename}:{source_id} has no applicable boundary"
            )

    for pack_name in xi.list_bundled_technology_packs():
        pack = xi.load_technology_pack(pack_name)
        for source_id, source in pack.sources.items():
            assert source.get("title"), f"{pack_name}:{source_id} has no title"
            assert source.get("license"), f"{pack_name}:{source_id} has no license"
            assert source.get("applicable_boundary"), (
                f"{pack_name}:{source_id} has no applicable boundary"
            )


def test_profile_and_process_defaults_are_bounded_and_not_mislabeled_measurements():
    profiles = xi.load_bundled_profiles()
    sources = profiles["sources"]
    for category, records in profiles["profiles"].items():
        for profile in records:
            assert profile["source_id"] in sources
            for name, spec in profile.get("parameters", {}).items():
                value = spec["value"]
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                assert math.isfinite(float(value)), f"{profile['id']}.{name}"
                confidence = str(spec.get("confidence", "")).lower()
                assert confidence not in {"measured", "site-measured"}
                if confidence not in {"exact", "convention"}:
                    assert spec["low"] <= value <= spec["high"]

    processes = xi.load_bundled_process_templates()
    assert processes["source_id"] in processes["sources"]
    for template in processes["templates"]:
        prior = template["screening_savings_fraction"]
        assert 0.0 <= prior["low"] <= prior["value"] <= prior["high"] <= 1.0


def test_derived_pack_priors_recompute_from_declared_source_values():
    def parameter(pack_name, category, profile_id, name):
        pack = xi.load_technology_pack(pack_name)
        profile = next(
            item for item in pack.profiles[category] if item["id"] == profile_id
        )
        return profile["parameters"][name]

    fcev = parameter(
        "mobility", "technology", "hydrogen-fuel-cell-drivetrain", "efficiency"
    )
    assert fcev["value"] == pytest.approx(0.55 * 0.89)
    assert fcev["low"] == pytest.approx(0.42 * 0.87)
    assert fcev["high"] == pytest.approx(0.59 * 0.91)

    pump = parameter(
        "water-materials", "technology", "electric-water-pump", "efficiency"
    )
    assert pump["value"] == pytest.approx(0.75 * 0.75)

    electric_compressor = parameter(
        "oil-gas", "technology", "vapor-recovery-unit", "efficiency"
    )
    assert electric_compressor["value"] == pytest.approx(0.85 * 0.96)

    aem = parameter(
        "emerging-energy",
        "technology",
        "anion-exchange-membrane-electrolyzer",
        "efficiency",
    )
    assert aem["value"] == pytest.approx(33.33 / 50.8, abs=5e-5)

    mwh_per_mmbtu = 1_055.05585262 / 3600.0
    tonnes_per_short_ton = 0.90718474
    eaf = parameter(
        "advanced-materials",
        "intensity",
        "electric-arc-furnace-melting",
        "specific_energy",
    )
    assert eaf["value"] == pytest.approx(1.5 * mwh_per_mmbtu / tonnes_per_short_ton)

    tonnes_per_pound = 0.00045359237
    mwh_per_btu = 1_055.05585262 / 3.6e9
    aluminum = parameter(
        "advanced-materials",
        "intensity",
        "hall-heroult-electrolysis",
        "specific_energy",
    )
    assert aluminum["value"] == pytest.approx(23_388 * mwh_per_btu / tonnes_per_pound)
    assert aluminum["low"] == pytest.approx(12_248 * mwh_per_btu / tonnes_per_pound)


def test_grid_snapshot_has_unique_finite_records_and_explicit_scope():
    payload = xi.load_bundled_grid_factors()
    assert payload["generated_on"]
    assert payload["scope"] == "lifecycle electricity-generation intensity"
    keys = [(item["iso3"], item["year"]) for item in payload["records"]]
    assert len(keys) == len(set(keys))
    assert all(
        math.isfinite(float(item["kg_co2e_per_mwh"])) and item["kg_co2e_per_mwh"] >= 0.0
        for item in payload["records"]
    )


def test_methane_defaults_match_declared_thermochemical_reference_conditions():
    molar_mass_kg_per_mol = 0.0160425
    ideal_density = (
        101_325.0 * molar_mass_kg_per_mol / (xi.UNIVERSAL_GAS_CONSTANT * 273.15)
    )
    assert xi.DEFAULT_METHANE_DENSITY_KG_PER_M3 == pytest.approx(
        ideal_density, rel=3e-3
    )

    # NIST gas-phase complete-combustion enthalpy is approximately 802.3 kJ/mol,
    # corresponding to about 50.0 MJ/kg LHV for pure methane.
    lhv_mj_per_kg = xi.DEFAULT_METHANE_LHV_MWH_PER_KG * 3600.0
    nist_lhv_mj_per_kg = 0.8023 / molar_mass_kg_per_mol
    assert lhv_mj_per_kg == pytest.approx(nist_lhv_mj_per_kg, rel=2e-3)

    result = xi.assess_methane_project(
        annual_methane_volume_m3=1.0,
        baseline_mode="vented",
        project_mode="recovered",
    )
    assert (
        "0 C and 101.325 kPa"
        in result.assumptions["methane_density_reference_conditions"]
    )
    assert result.assumptions["methane_energy_basis"] == "lower heating value (LHV)"


def test_methane_combustion_fixture_closes_elemental_mass_independently():
    carbon = 12.0107
    hydrogen = 1.00794
    oxygen = 15.9994
    methane = carbon + 4.0 * hydrogen
    oxygen_feed = 4.0 * oxygen
    carbon_dioxide = carbon + 2.0 * oxygen
    water = 2.0 * hydrogen + oxygen

    result = xi.analyze_material_system(
        "synthetic methane stoichiometry fixture",
        components=[{"id": "reactor", "kind": "reactor-separator"}],
        streams=[
            {
                "id": "methane",
                "mass": methane,
                "target": "reactor",
                "composition": {
                    "C": carbon / methane,
                    "H": 4.0 * hydrogen / methane,
                },
            },
            {
                "id": "oxygen",
                "mass": oxygen_feed,
                "target": "reactor",
                "material": "O",
            },
            {
                "id": "carbon dioxide",
                "mass": carbon_dioxide,
                "source": "reactor",
                "composition": {
                    "C": carbon / carbon_dioxide,
                    "O": 2.0 * oxygen / carbon_dioxide,
                },
            },
            {
                "id": "water",
                "mass": 2.0 * water,
                "source": "reactor",
                "composition": {
                    "H": 2.0 * hydrogen / water,
                    "O": oxygen / water,
                },
            },
        ],
    )
    assert result.balance.residual_mass_kg == pytest.approx(0.0, abs=1e-12)
    for balance in result.balance.constituent_balances.values():
        assert balance["residual_mass_kg"] == pytest.approx(0.0, abs=1e-12)
    assert result.balance.chemical_exergy_complete is False


def test_connected_system_results_are_unit_invariant():
    base = {
        "name": "unit-invariance fixture",
        "components": [{"id": "load", "kind": "converter"}],
        "flows": [
            {
                "id": "input",
                "energy": 1.0,
                "target": "load",
                "exergy_factor": 1.0,
            },
            {
                "id": "product",
                "energy": 0.4,
                "source": "load",
                "exergy_factor": 1.0,
            },
            {
                "id": "loss",
                "energy": 0.6,
                "source": "load",
                "role": "loss",
                "exergy_factor": 0.2,
            },
        ],
    }
    mwh = xi.analyze_system_definition(base)
    gj_payload = json.loads(json.dumps(base))
    gj_payload["unit"] = "GJ"
    for flow in gj_payload["flows"]:
        flow["energy"] *= 3.6
        flow["unit"] = "GJ"
    gj = xi.analyze_system_definition(gj_payload)

    assert gj.energy.efficiency == pytest.approx(mwh.energy.efficiency)
    assert gj.exergy.exergetic_efficiency == pytest.approx(
        mwh.exergy.exergetic_efficiency
    )
    assert gj.energy.residual == pytest.approx(mwh.energy.residual * 3.6)
    assert gj.exergy.residual == pytest.approx(mwh.exergy.residual * 3.6)


def test_bounded_normal_is_truncated_not_clipped_at_bounds():
    distribution = xi.DistributionSpec.normal(0.0, 1.0, low=-0.5, high=0.5)
    generator = random.Random(418)
    values = [distribution.sample(generator) for _ in range(5_000)]

    assert all(-0.5 <= value <= 0.5 for value in values)
    assert not any(value in {-0.5, 0.5} for value in values)
    assert sum(values) / len(values) == pytest.approx(0.0, abs=0.015)


def test_nonfinite_and_ambiguous_inputs_fail_at_scientific_boundaries():
    with pytest.raises(xi.UnitError, match="fuel-specific"):
        xi.convert_energy(1.0, "MWh_HHV", "MWh_LHV")
    with pytest.raises(ValueError, match="absolute zero"):
        xi.Environment(temperature_c=-273.15)
    with pytest.raises(ValueError, match="greater than zero"):
        xi.potential_exergy(1.0, 1.0, gravity=0.0)

    result = xi.analyze_balance(
        "inconsistent",
        inputs=[xi.ExergyStream("input", 10.0)],
        products=[xi.ExergyStream("product", 12.0)],
    )
    assert result.destruction_exergy == 0.0
    assert result.residual == -2.0
    assert result.warnings
