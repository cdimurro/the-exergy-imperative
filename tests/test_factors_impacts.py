import json

import pytest

import exergy_imperative as xi


def test_global_grid_pack_has_broad_country_coverage_and_history():
    library = xi.DEFAULT_IMPACT_FACTORS
    assert len(library.grid_locations()) >= 200
    usa = library.grid_emissions("USA", 2024)
    assert usa.country == "United States"
    assert usa.year == 2024
    assert usa.kg_co2e_per_mwh == pytest.approx(383.78)


def test_grid_year_fallback_is_explicit():
    factor = xi.DEFAULT_IMPACT_FACTORS.grid_emissions("United States", 2030)
    assert factor.requested_year == 2030
    assert factor.year < 2030
    assert factor.is_fallback_year


@pytest.mark.parametrize("year", [2024.9, float("nan"), float("inf"), True])
def test_grid_lookup_rejects_nonintegral_years(year):
    with pytest.raises(ValueError, match="grid lookup year must be a finite integer"):
        xi.DEFAULT_IMPACT_FACTORS.grid_emissions("USA", year)


def test_ar6_warming_potentials_support_aliases_and_horizons():
    methane = xi.DEFAULT_IMPACT_FACTORS.warming_potential("fossil methane")
    refrigerant = xi.DEFAULT_IMPACT_FACTORS.warming_potential("R134a")
    assert methane.for_horizon(20) == pytest.approx(82.5)
    assert methane.for_horizon(100) == pytest.approx(29.8)
    assert refrigerant.gwp100 == pytest.approx(1526)
    with pytest.raises(ValueError, match="20 or 100"):
        methane.for_horizon(50)


def test_fuel_factor_is_basis_specific():
    hhv = xi.DEFAULT_IMPACT_FACTORS.fuel_emissions("natural gas")
    lhv = xi.DEFAULT_IMPACT_FACTORS.fuel_emissions("natural gas lhv")
    assert hhv.basis == "HHV"
    assert lhv.basis == "LHV"
    assert lhv.gases_kg_per_mwh["CO2"] > hhv.gases_kg_per_mwh["CO2"]


def test_direct_impacts_respect_typed_energy_basis():
    result = xi.assess_impacts(1, unit="MWh_LHV", carrier="natural gas")
    assert result.carrier == "methane-lhv"
    assert result.assumptions["energy_basis"] == "LHV"
    assert result.assumptions["combustion_factor"]["basis"] == "LHV"
    assert result.gases_kg["CO2"] == pytest.approx(201.96)


def test_natural_gas_impacts_include_gases_pollutants_and_health_screening():
    result = xi.assess_impacts(100, carrier="natural gas")
    assert result.co2e100_kg > 18_000
    assert result.co2e20_kg > result.co2e100_kg
    assert {item.pollutant for item in result.pollutants} >= {
        "SO2",
        "NOx",
        "PM2.5",
        "CO",
    }
    nox = next(item for item in result.pollutants if item.pollutant == "NOx")
    assert nox.profile is not None
    assert "asthma" in " ".join(nox.profile.health_effects).lower()
    assert any("exposure" in warning.lower() for warning in result.warnings)


def test_registry_only_carrier_alias_uses_canonical_fuel_factors():
    canonical = xi.assess_impacts(1, carrier="natural-gas-hhv")
    alias = xi.assess_impacts(1, carrier="methane")
    label = xi.assess_impacts(1, carrier="Natural gas on HHV basis")

    assert alias.carrier == canonical.carrier == label.carrier == "natural-gas-hhv"
    assert alias.gases_kg == canonical.gases_kg == label.gases_kg
    assert alias.co2e100_kg == pytest.approx(canonical.co2e100_kg)
    assert alias.co2e100_kg > 0


def test_electricity_uses_country_factor_and_reports_year():
    result = xi.assess_impacts(2, carrier="electricity", country="France", year=2025)
    assert result.geography == "France"
    assert result.aggregate_grid_co2e_kg == pytest.approx(2 * 41.44)
    assert result.assumptions["grid_factor"]["year"] == 2025


def test_world_factor_is_a_visible_fallback():
    result = xi.assess_impacts(1, carrier="electricity")
    assert result.geography == "World"
    assert result.assumptions["grid_location"] == "World"
    assert any("world grid factor" in warning.lower() for warning in result.warnings)


def test_explicit_grid_factor_without_location_does_not_claim_world_lookup():
    result = xi.assess_impacts(
        1, carrier="electricity", grid_factor_kg_co2e_per_mwh=123
    )
    assert result.geography is None
    assert "grid_location" not in result.assumptions
    assert result.assumptions["grid_factor"]["status"] == "provided"
    assert not any(
        "world grid factor" in warning.lower() for warning in result.warnings
    )


def test_explicit_grid_factor_without_carrier_is_applied_as_electricity():
    result = xi.assess_impacts(2, grid_factor_kg_co2e_per_mwh=123)
    assert result.carrier == "electricity"
    assert result.aggregate_grid_co2e_kg == pytest.approx(246)
    assert result.co2e100_kg == pytest.approx(246)
    assert "electricity inferred" in result.assumptions["carrier"]
    assert any(
        "full energy quantity as electricity" in item for item in result.warnings
    )


def test_positive_energy_requires_an_applicable_factor_basis():
    with pytest.raises(ValueError, match="positive energy quantity requires"):
        xi.assess_impacts(100)

    with pytest.raises(ValueError, match="positive energy quantity requires"):
        xi.assess_impacts()

    explicit = xi.assess_impacts(100, gas_factors_kg_per_mwh={"CO2": 2.0})
    assert explicit.gases_kg["CO2"] == pytest.approx(200)

    inventory = xi.assess_impacts(0, gases_kg={"CO2": 2.0})
    assert inventory.gases_kg["CO2"] == pytest.approx(2)


@pytest.mark.parametrize(
    ("argument", "inventory"),
    (
        ("gases_kg", {"CO2": 2.0}),
        ("pollutant_masses_kg", {"SO2": 0.5}),
        ("refrigerant_leakage_kg", {"R134a": 0.1}),
    ),
)
def test_normalized_impacts_reject_absolute_mass_inputs(argument, inventory):
    with pytest.raises(ValueError, match="absolute mass inputs.*explicit energy"):
        xi.assess_impacts(**{argument: inventory})


def test_normalized_impacts_accept_per_mwh_factor_inputs():
    result = xi.assess_impacts(
        gas_factors_kg_per_mwh={"CO2": 2.0},
        pollutant_factors_kg_per_mwh={"SO2": 0.5},
    )
    assert result.normalized
    assert result.gases_kg["CO2"] == pytest.approx(2.0)
    assert result.pollutants[0].mass.value == pytest.approx(0.5)


def test_explicit_grid_factor_rejects_a_non_electric_carrier():
    with pytest.raises(ValueError, match="grid_factor.*electricity carrier"):
        xi.assess_impacts(
            1,
            carrier="natural gas",
            grid_factor_kg_co2e_per_mwh=123,
        )


def test_normalized_impacts_use_one_mwh_regardless_of_supplied_unit():
    mwh = xi.assess_impacts(carrier="electricity", unit="MWh", country="USA")
    kwh = xi.assess_impacts(carrier="electricity", unit="kWh", country="USA")
    assert kwh.energy_mwh == pytest.approx(1)
    assert kwh.aggregate_grid_co2e_kg == pytest.approx(mwh.aggregate_grid_co2e_kg)
    assert "normalized per 1 MWh" in kwh.assumptions["energy"]
    assert mwh.normalized and kwh.normalized
    assert kwh.to_dict()["normalized"] is True


def test_unknown_supplied_grid_location_is_rejected_instead_of_hidden():
    with pytest.raises(ValueError, match="no grid factor matched.*Denver"):
        xi.assess(carrier="electricity", location="Denver").impacts()


def test_typed_basis_is_checked_against_non_registry_fuel_factor():
    valid = xi.assess_impacts(1, unit="MWh_LHV", carrier="lpg-lhv")
    assert valid.assumptions["combustion_factor"]["basis"] == "LHV"
    with pytest.raises(ValueError, match="conflicts with the LHV basis"):
        xi.assess_impacts(1, unit="MWh_HHV", carrier="lpg-lhv")


def test_refrigerant_leakage_shows_warming_horizon_gap():
    result = xi.assess_impacts(
        0,
        refrigerant_leakage_kg={"R134a": 10},
    )
    assert result.co2e20_kg == pytest.approx(41_440)
    assert result.co2e100_kg == pytest.approx(15_260)
    assert result.warming_horizon_gap_kg_co2e == pytest.approx(26_180)


def test_user_pollutant_damage_cost_is_not_silently_assumed():
    no_cost = xi.assess_impacts(0, pollutant_masses_kg={"SO2": 2})
    with_cost = xi.assess_impacts(
        0,
        pollutant_masses_kg={"SO2": 2},
        damage_costs_per_kg={"SO2": 10},
    )
    assert no_cost.health_externality_cost == 0
    assert no_cost.health_externality_currency is None
    assert with_cost.health_externality_cost == pytest.approx(20)
    assert with_cost.health_externality_currency == "USD"
    assert with_cost.to_dict()["health_externality_currency"] == "USD"
    assert any("user-supplied" in warning for warning in with_cost.warnings)


def test_pollutant_damage_currency_is_normalized_and_validated():
    result = xi.assess_impacts(
        0,
        pollutant_masses_kg={"SO2": 2},
        damage_costs_per_kg={"SO2": 10},
        currency=" usd ",
    )
    assert result.health_externality_currency == "USD"
    assert result.pollutants[0].currency == "USD"
    assert result.assumptions["damage_cost_currency"] == "USD"

    with pytest.raises(ValueError, match="currency must be a non-empty string"):
        xi.assess_impacts(
            0,
            pollutant_masses_kg={"SO2": 2},
            damage_costs_per_kg={"SO2": 10},
            currency=" ",
        )


def test_assessment_impacts_convenience_infers_input_carrier():
    assessment = xi.assess(technology="gas boiler", energy=10)
    result = assessment.impacts()
    assert result.carrier == "natural-gas-hhv"
    assert result.co2e100_kg > 1_800


def test_assessment_impacts_use_resolved_carrier_basis_and_normalized_status():
    lhv = xi.assess(carrier="natural gas", basis="LHV")
    lhv_impacts = lhv.impacts()
    assert lhv.carrier_id == "methane-lhv"
    assert lhv_impacts.carrier == "methane-lhv"
    assert lhv_impacts.assumptions["combustion_factor"]["basis"] == "LHV"
    assert "normalized per 1 MWh" in lhv_impacts.assumptions["energy"]

    electricity = xi.assess(carrier="mwh_e")
    assert electricity.impacts().aggregate_grid_co2e_kg > 0

    direct_electricity = xi.assess_impacts(1, carrier="mwh_e", country="USA")
    assert direct_electricity.carrier == "electricity"
    assert direct_electricity.aggregate_grid_co2e_kg > 0


def test_custom_grid_overlay_versions_the_replacement(tmp_path):
    pack = tmp_path / "grid.json"
    pack.write_text(
        json.dumps(
            {
                "data_version": "site-7",
                "sources": {"site-meter": {"title": "Site meter"}},
                "grid_records": [
                    {
                        "iso3": "USA",
                        "country": "United States",
                        "year": 2025,
                        "kg_co2e_per_mwh": 1.0,
                        "source_id": "site-meter",
                    }
                ],
            }
        )
    )
    library = xi.load_impact_factor_pack(pack)
    factor = library.grid_emissions("USA", 2025)
    assert factor.kg_co2e_per_mwh == pytest.approx(1)
    assert factor.data_version.endswith("+site-7")
    assert factor.source_ids == ("site-meter",)
    result = xi.assess_impacts(
        1,
        carrier="electricity",
        country="USA",
        year=2025,
        factor_library=library,
    )
    assert result.sources == ("site-meter",)
    source = xi.report_view(result).sources[0]
    assert source["title"] == "Site meter"


def test_custom_grid_pack_rejects_negative_or_nonfinite_intensity(tmp_path):
    for value in (-1, float("nan"), float("inf")):
        pack = tmp_path / f"invalid-grid-{str(value).replace('.', '-')}.json"
        pack.write_text(
            json.dumps(
                {
                    "data_version": "invalid-grid",
                    "grid_records": [
                        {
                            "iso3": "BAD",
                            "country": "Invalid grid",
                            "year": 2025,
                            "kg_co2e_per_mwh": value,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="finite and nonnegative"):
            xi.load_impact_factor_pack(pack)


@pytest.mark.parametrize("year", [2024.9, float("nan"), float("inf"), True])
def test_custom_grid_pack_rejects_nonintegral_years(tmp_path, year):
    pack = tmp_path / "invalid-grid-year.json"
    pack.write_text(
        json.dumps(
            {
                "data_version": "invalid-grid-year",
                "grid_records": [
                    {
                        "iso3": "USA",
                        "country": "United States",
                        "year": year,
                        "kg_co2e_per_mwh": 1.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="grid year must be a finite integer"):
        xi.load_impact_factor_pack(pack)


@pytest.mark.parametrize(
    "section",
    [
        {"gwp_sets": {"AR6": {"gases": {"X": {"gwp20": -1, "gwp100": 1}}}}},
        {
            "fuel_combustion": {
                "bad-fuel": {
                    "label": "Bad fuel",
                    "basis": "LHV",
                    "source_id": "site",
                    "gases_kg_per_mwh": {"CO2": -1},
                }
            }
        },
        {
            "fuel_combustion": {
                "bad-fuel": {
                    "label": "Bad fuel",
                    "basis": "LHV",
                    "source_id": "site",
                    "pollutants_kg_per_mwh": {"NOx": {"value": 1, "low": 2, "high": 3}},
                }
            }
        },
    ],
)
def test_custom_impact_pack_rejects_invalid_factor_values(tmp_path, section):
    pack = tmp_path / "invalid-impact.json"
    pack.write_text(
        json.dumps(
            {
                "data_version": "invalid-impact",
                "sources": {"site": {"title": "Invalid test source"}},
                **section,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="nonnegative|low <= value <= high"):
        xi.load_impact_factor_pack(pack)


def test_custom_gwp_pack_extends_existing_assessment_gases(tmp_path):
    pack = tmp_path / "gwp.json"
    pack.write_text(
        json.dumps(
            {
                "data_version": "custom-gwp",
                "gwp_sets": {
                    "AR6": {
                        "gases": {
                            "X-TEST": {
                                "name": "Test gas",
                                "gwp20": 10,
                                "gwp100": 5,
                            }
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    library = xi.load_impact_factor_pack(pack)
    assert library.warming_potential("CO2").gwp100 == pytest.approx(1)
    assert library.warming_potential("CH4-fossil").gwp100 == pytest.approx(29.8)
    assert library.warming_potential("X-TEST").gwp100 == pytest.approx(5)
    assert library.warming_potential("X-TEST").source_id == "unspecified"
    assert library.warming_potential("CO2").source_id == "ipcc-ar6-wgi-2021"


def test_custom_gwp_source_applies_only_to_custom_gases(tmp_path):
    pack = tmp_path / "sourced-gwp.json"
    pack.write_text(
        json.dumps(
            {
                "data_version": "custom-gwp",
                "sources": {"site": {"title": "Site characterization"}},
                "gwp_sets": {
                    "AR6": {
                        "source_id": "site",
                        "gases": {
                            "X-SITE": {"name": "Site gas", "gwp20": 2, "gwp100": 1}
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    library = xi.load_impact_factor_pack(pack)
    assert library.warming_potential("X-SITE").source_id == "site"
    assert library.warming_potential("CO2").source_id == "ipcc-ar6-wgi-2021"


def test_unknown_carrier_remains_usable_with_explicit_emissions():
    result = xi.assess_impacts(
        1,
        carrier="custom fuel",
        gases_kg={"CO2": 12},
        pollutant_masses_kg={"mystery": 1},
    )
    assert result.co2e100_kg == pytest.approx(12)
    assert any("custom fuel" in warning for warning in result.warnings)
    assert any("mystery" in warning for warning in result.warnings)


def test_unknown_carrier_without_explicit_emissions_is_rejected():
    with pytest.raises(ValueError, match="carrier with a matched factor"):
        xi.assess_impacts(1, carrier="diseel")


def test_explicit_pollutant_mass_preserves_default_factor_bounds():
    baseline = xi.assess_impacts(10, carrier="natural gas")
    combined = xi.assess_impacts(
        10, carrier="natural gas", pollutant_masses_kg={"NOx": 2}
    )
    baseline_nox = next(item for item in baseline.pollutants if item.pollutant == "NOx")
    combined_nox = next(item for item in combined.pollutants if item.pollutant == "NOx")
    assert combined_nox.mass.value == pytest.approx(baseline_nox.mass.value + 2)
    assert combined_nox.mass.low == pytest.approx(baseline_nox.mass.low + 2)
    assert combined_nox.mass.high == pytest.approx(baseline_nox.mass.high + 2)


def test_explicit_factor_aliases_override_canonical_bundled_factors():
    result = xi.assess_impacts(
        1,
        carrier="natural gas",
        gas_factors_kg_per_mwh={"carbon dioxide": 0},
        pollutant_factors_kg_per_mwh={"nitrogen oxides": 0},
    )
    assert result.gases_kg["CO2"] == pytest.approx(0)
    assert sum(item.gas == "CO2" for item in result.climate_contributions) == 1
    nox = [item for item in result.pollutants if item.pollutant == "NOx"]
    assert len(nox) == 1
    assert result.assumptions["gas_factor_overrides_kg_per_mwh"] == {"CO2": 0.0}
    assert result.assumptions["pollutant_factor_overrides_kg_per_mwh"] == {"NOx": 0.0}
    assert nox[0].mass.value == pytest.approx(0)
