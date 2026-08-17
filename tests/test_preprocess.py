import csv

import pytest

import exergy_imperative as xi

ROWS = [
    {
        "datetime": "2025-02-19T00:00:00",
        "t_amb": "0",
        "t_sup_prim": "80",
        "t_ret_prim": "50",
        "t_sup_sec": "58",
        "t_ret_sec": "40",
        "qizm": "10",
    },
    {
        "datetime": "2025-02-19T00:15:00",
        "t_amb": "-2",
        "t_sup_prim": "82",
        "t_ret_prim": "51",
        "t_sup_sec": "59",
        "t_ret_sec": "41",
        "qizm": "20",
    },
]


def test_alias_mapping_and_enrichment():
    result = xi.enrich_xai4heat_record(ROWS[0])
    assert result["exergy_tier"] == "F3"
    assert result["fx_dynamic_ambient"] == pytest.approx(
        xi.thermal_exergy_factor_c(80, 0)
    )
    assert result["fx_primary_integrated"] == pytest.approx(
        xi.sensible_heat_exergy_factor_c(80, 50, 0)
    )
    assert result["accessible_exergy_dynamic"] == pytest.approx(
        10 * result["fx_dynamic_ambient"]
    )


def test_unit_suffixed_xai4heat_aliases_are_canonicalized():
    row = {
        "datetime": "2025-02-19T00:00:00",
        "t_amb (\N{DEGREE SIGN}C)": "0",
        "t_sup_prim [\N{DEGREE SIGN}C]": "80",
        "t_ret_prim (deg C)": "50",
        "qizm": "10",
    }

    result = xi.enrich_xai4heat_record(row)

    assert result["exergy_tier"] == "F3"
    assert result["fx_dynamic_ambient"] == pytest.approx(
        xi.thermal_exergy_factor_c(80, 0)
    )


def test_unit_bearing_delivery_aliases_are_normalized_to_mwh():
    base = {
        "datetime": "2025-02-19T00:00:00",
        "t_amb": "0",
        "t_sup_prim": "80",
        "t_ret_prim": "50",
    }

    from_kwh = xi.enrich_xai4heat_record({**base, "energy_kwh": "1000"})
    from_mwh = xi.enrich_xai4heat_record({**base, "energy_mwh": "1"})

    assert from_kwh["thermal_delivery_weight"] == pytest.approx(1.0)
    assert from_mwh["thermal_delivery_weight"] == pytest.approx(1.0)
    assert from_kwh["accessible_exergy_dynamic"] == pytest.approx(
        from_mwh["accessible_exergy_dynamic"]
    )


def test_equivalent_delivery_aliases_do_not_conflict_after_conversion():
    canonical = xi.canonicalize_record({"energy_kwh": "1000", "energy_mwh": "1"})
    assert canonical["thermal_delivery"] == pytest.approx(1.0)

    with pytest.raises(ValueError, match="conflicting values.*thermal_delivery"):
        xi.canonicalize_record({"energy_kwh": "1000", "energy_mwh": "2"})


def test_mixed_kwh_and_mwh_records_have_consistent_summary_weights():
    records = [
        {
            "t_sup_prim": "80",
            "t_amb": "0",
            "energy_kwh": "1000",
        },
        {
            "t_sup_prim": "100",
            "t_amb": "0",
            "energy_mwh": "1",
        },
    ]

    summary = xi.xai4heat_summary(records)
    expected = (
        xi.thermal_exergy_factor_c(80, 0) + xi.thermal_exergy_factor_c(100, 0)
    ) / 2
    model = summary["models"]["primary_supply_ambient"]
    assert model["weighted_factor"] == pytest.approx(expected)
    assert model["total_weight"] == pytest.approx(2.0)


def test_malformed_timestamp_cannot_receive_interval_telemetry_fidelity():
    result = xi.enrich_xai4heat_record(dict(ROWS[0], datetime="invalid"))

    assert result["exergy_tier"] == "F2"
    assert "invalid_timestamp_fidelity_downgraded" in result["exergy_issues"]


def test_canonicalization_rejects_conflicting_alias_values():
    with pytest.raises(ValueError, match="conflicting values.*ambient_temperature_c"):
        xi.canonicalize_record({"t_amb": 5.0, "ambient_temperature_c": 10.0})

    canonical = xi.canonicalize_record({"t_amb": 5.0, "ambient_temperature_c": 5.0})
    assert canonical["ambient_temperature_c"] == pytest.approx(5.0)


def test_missing_return_only_disables_integrated_model():
    row = dict(ROWS[0], t_ret_prim="")
    result = xi.enrich_xai4heat_record(row)
    assert result["fx_dynamic_ambient"] is not None
    assert result["fx_primary_integrated"] is None
    assert "integrated_model_unavailable" in result["exergy_issues"]


def test_negative_delivery_is_clipped():
    row = dict(ROWS[0], qizm="-5")
    result = xi.enrich_xai4heat_record(row)
    assert result["thermal_delivery_weight"] == 0
    assert "clipped" in result["exergy_issues"]


def test_weighted_summary():
    summary = xi.xai4heat_summary(ROWS)
    first = xi.thermal_exergy_factor_c(80, 0)
    second = xi.thermal_exergy_factor_c(82, -2)
    expected = (10 * first + 20 * second) / 30
    assert summary["models"]["primary_supply_ambient"][
        "weighted_factor"
    ] == pytest.approx(expected)
    assert summary["models"]["primary_supply_ambient"]["valid_intervals"] == 2


def test_weighted_summary_enriches_mixed_raw_and_enriched_rows_individually():
    mixed = [xi.enrich_xai4heat_record(ROWS[0]), ROWS[1]]
    summary = xi.xai4heat_summary(mixed)
    expected = (
        10 * xi.thermal_exergy_factor_c(80, 0) + 20 * xi.thermal_exergy_factor_c(82, -2)
    ) / 30
    model = summary["models"]["primary_supply_ambient"]
    assert model["valid_intervals"] == 2
    assert model["weighted_factor"] == pytest.approx(expected)


def test_weighted_summary_recomputes_enriched_rows_for_requested_reference():
    enriched = xi.enrich_xai4heat_record(ROWS[0], fixed_reference_c=20)
    summary = xi.xai4heat_summary([enriched], fixed_reference_c=25)
    assert summary["fixed_reference_c"] == 25
    assert summary["models"]["primary_supply_fixed_reference"][
        "weighted_factor"
    ] == pytest.approx(xi.thermal_exergy_factor_c(80, 25))


def test_temperature_sensitivity_bounds_base():
    result = xi.xai4heat_temperature_sensitivity(ROWS, uncertainty_c=0.5)
    assert result["low_factor"] < result["base_factor"] < result["high_factor"]
    assert result["approximate_absolute_delta"] > 0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_preprocessing_rejects_nonfinite_fixed_reference(value):
    with pytest.raises(ValueError, match="fixed_reference_c must be finite"):
        xi.enrich_xai4heat_record(ROWS[0], fixed_reference_c=value)
    with pytest.raises(ValueError, match="fixed_reference_c must be finite"):
        xi.xai4heat_summary([], fixed_reference_c=value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_temperature_sensitivity_rejects_nonfinite_uncertainty(value):
    with pytest.raises(ValueError, match="uncertainty_c must be finite"):
        xi.xai4heat_temperature_sensitivity(ROWS, uncertainty_c=value)


def test_temperature_sensitivity_uses_one_common_interval_population():
    records = [
        {"t_sup_prim": "20.25", "t_amb": "20", "qizm": "1000"},
        {"t_sup_prim": "80", "t_amb": "20", "qizm": "1"},
    ]
    result = xi.xai4heat_temperature_sensitivity(records, uncertainty_c=0.5)
    assert result["base_factor"] == pytest.approx(xi.thermal_exergy_factor_c(80, 20))
    assert result["low_factor"] < result["base_factor"] < result["high_factor"]


def test_csv_round_trip(tmp_path):
    source = tmp_path / "source.csv"
    output = tmp_path / "output.csv"
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(ROWS[0]))
        writer.writeheader()
        writer.writerows(ROWS)
    records = xi.enrich_csv(source, output)
    assert len(records) == 2
    loaded = xi.load_csv(output)
    assert loaded[0]["exergy_tier"] == "F3"


@pytest.mark.parametrize(
    "header",
    [
        "timestamp,t_sup_prim,t_sup_prim,t_amb,qizm\n2026-01-01,80,40,20,1\n",
        "timestamp,,t_amb,qizm\n2026-01-01,80,20,1\n",
    ],
)
def test_telemetry_csv_headers_must_be_unique_and_nonblank(tmp_path, header):
    source = tmp_path / "ambiguous.csv"
    source.write_text(header, encoding="utf-8")

    with pytest.raises(ValueError, match="headers|header names"):
        xi.load_csv(source)


def test_telemetry_csv_rejects_rows_wider_than_header(tmp_path):
    source = tmp_path / "oversized.csv"
    source.write_text("timestamp,t_amb\n2026-01-01,20,surplus\n", encoding="utf-8")

    with pytest.raises(ValueError, match="row 2 has 3 values.*2 columns"):
        xi.load_csv(source)


def test_preprocessing_csv_writer_neutralizes_spreadsheet_formulas(tmp_path):
    output = xi.write_csv(
        [{"=unsafe-header": '=HYPERLINK("https://example.com")', "safe": "@SUM(1,1)"}],
        tmp_path / "safe.csv",
    )
    text = output.read_text(encoding="utf-8")
    assert "'=unsafe-header" in text
    assert "'=HYPERLINK" in text
    assert "'@SUM" in text
