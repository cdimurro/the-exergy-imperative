import csv
import json
import sqlite3
from contextlib import closing
from datetime import time, timedelta, timezone
from decimal import Decimal

import pytest

import exergy_imperative as xi


def test_mapping_inference_units_timezone_and_raw_preservation():
    rows = [
        {
            "Date Time": "2026-01-01T12:00:00",
            "Energy (kWh)": "1,500",
            "Supply Temperature (F)": "176",
            "Fuel Type": "natural gas",
            "Site": "A",
        }
    ]
    plan = xi.infer_mapping(rows[0], required=("energy",), timezone="America/Denver")
    result = xi.normalize_records(rows, mapping=plan)
    normalized = result.records[0]
    assert normalized["energy"] == pytest.approx(1.5)
    assert normalized["unit"] == "MWh"
    assert normalized["source_temperature"] == pytest.approx(80)
    assert normalized["timestamp"].endswith("-07:00")
    assert normalized["Site"] == "A"
    assert result.raw_records[0]["Energy (kWh)"] == "1,500"


def test_missing_policies_drop_raise_forward_fill_and_interpolate():
    mapping = xi.MappingPlan(
        fields=(xi.FieldMapping("value", "energy", "MWh"),),
        required=("energy",),
    )
    rows = [{"value": 1}, {"value": ""}, {"value": 3}]
    dropped = xi.normalize_records(rows, mapping=mapping, missing_policy="drop")
    assert len(dropped.records) == 2
    assert dropped.dropped_rows == (2,)
    assert dropped.missing_policy == "drop"
    assert dropped.to_dict()["missing_policy"] == "drop"
    filled = xi.normalize_records(rows, mapping=mapping, missing_policy="forward-fill")
    assert filled.records[1]["energy"] == pytest.approx(1)
    interpolated = xi.normalize_records(
        rows, mapping=mapping, missing_policy="interpolate"
    )
    assert interpolated.records[1]["energy"] == pytest.approx(2)
    with pytest.raises(ValueError, match="row 2"):
        xi.normalize_records(rows, mapping=mapping, missing_policy="raise")


def test_mapping_plan_rejects_duplicate_targets():
    with pytest.raises(ValueError, match="duplicate targets: energy"):
        xi.MappingPlan(
            fields=(
                xi.FieldMapping("gas", "energy", "GJ"),
                xi.FieldMapping("electricity", "energy", "kWh"),
            )
        )


@pytest.mark.parametrize("multiplier", [float("nan"), float("inf"), float("-inf")])
def test_field_mapping_rejects_nonfinite_multiplier(multiplier):
    with pytest.raises(ValueError, match="mapping multiplier must be finite"):
        xi.FieldMapping("value", "energy", multiplier=multiplier)


def test_numeric_mapping_rejects_scaling_overflow():
    mapping = xi.MappingPlan(
        fields=(
            xi.FieldMapping(
                "value", "custom_metric", multiplier=10, data_type="number"
            ),
        )
    )

    result = xi.normalize_records([{"value": 1e308}], mapping=mapping)

    assert "custom_metric" not in result.records[0]
    assert result.issue_counts == {"conversion_error": 1}
    assert "finite after scaling" in result.issues[0].message


def test_conflicting_header_and_row_energy_units_are_rejected():
    mapping = xi.infer_mapping(["Energy (kWh)", "Unit"], required=("energy",))

    result = xi.normalize_records(
        [{"Energy (kWh)": 1000, "Unit": "MWh"}], mapping=mapping
    )

    assert "energy" not in result.records[0]
    assert result.issue_counts == {"unit_conflict": 1, "missing_required": 1}
    assert "conflicts with row unit" in result.issues[0].message


@pytest.mark.parametrize(
    ("header", "row_unit", "expected_unit"),
    [
        ("Energy (MWh)", "MWh_LHV", "MWh_LHV"),
        ("Energy (MWh_HHV)", "MWh", "MWh_HHV"),
    ],
)
def test_one_sided_energy_basis_qualifiers_are_preserved(
    header, row_unit, expected_unit
):
    mapping = xi.infer_mapping([header, "Unit"], required=("energy",))

    result = xi.normalize_records(
        [{header: 1, "Unit": row_unit}],
        mapping=mapping,
    )

    assert result.records[0]["energy"] == pytest.approx(1)
    assert result.records[0]["unit"] == expected_unit
    assert result.issue_counts == {}


def test_explicit_header_and_row_energy_basis_conflict_is_rejected():
    header = "Energy (MWh_HHV)"
    mapping = xi.infer_mapping([header, "Unit"], required=("energy",))

    result = xi.normalize_records(
        [{header: 1, "Unit": "MWh_LHV"}],
        mapping=mapping,
    )

    assert "energy" not in result.records[0]
    assert result.issue_counts == {"unit_conflict": 1, "missing_required": 1}


def test_energy_fill_policies_preserve_typed_basis_and_reject_conflicts():
    mapping = xi.MappingPlan(
        fields=(
            xi.FieldMapping("Energy", "energy"),
            xi.FieldMapping("Unit", "unit"),
        ),
        required=("energy",),
    )
    forward = xi.normalize_records(
        [
            {"Energy": 1, "Unit": "MWh_LHV"},
            {"Energy": None, "Unit": "MWh_LHV"},
        ],
        mapping=mapping,
        missing_policy="forward-fill",
    )
    assert forward.records[1]["unit"] == "MWh_LHV"

    interpolated = xi.normalize_records(
        [
            {"Energy": 1, "Unit": "MWh_HHV"},
            {"Energy": None, "Unit": "MWh_HHV"},
            {"Energy": 3, "Unit": "MWh_HHV"},
        ],
        mapping=mapping,
        missing_policy="interpolate",
    )
    assert interpolated.records[1]["energy"] == pytest.approx(2)
    assert interpolated.records[1]["unit"] == "MWh_HHV"

    conflict = xi.normalize_records(
        [
            {"Energy": 1, "Unit": "MWh_LHV"},
            {"Energy": None, "Unit": "MWh"},
            {"Energy": 3, "Unit": "MWh_HHV"},
        ],
        mapping=mapping,
        missing_policy="interpolate",
    )
    assert "energy" not in conflict.records[1]
    assert conflict.issue_counts["basis_conflict"] == 1

    forward_conflict = xi.normalize_records(
        [
            {"Energy": 1, "Unit": "MWh_LHV"},
            {"Energy": None, "Unit": "MWh_HHV"},
        ],
        mapping=mapping,
        missing_policy="forward-fill",
    )
    assert "energy" not in forward_conflict.records[1]
    assert forward_conflict.records[1]["unit"] == "MWh_HHV"
    assert forward_conflict.issue_counts == {
        "basis_conflict": 1,
        "missing_required": 1,
    }

    interior_conflict = xi.normalize_records(
        [
            {"Energy": 1, "Unit": "MWh_HHV"},
            {"Energy": None, "Unit": "MWh_LHV"},
            {"Energy": 3, "Unit": "MWh_HHV"},
        ],
        mapping=mapping,
        missing_policy="interpolate",
    )
    assert "energy" not in interior_conflict.records[1]
    assert interior_conflict.records[1]["unit"] == "MWh_LHV"
    assert interior_conflict.issue_counts == {
        "basis_conflict": 1,
        "missing_required": 1,
    }


def test_interpolation_respects_boolean_and_integer_types():
    boolean_mapping = xi.MappingPlan(
        fields=(xi.FieldMapping("active", "active", data_type="boolean"),),
        required=("active",),
    )
    boolean_result = xi.normalize_records(
        [{"active": "true"}, {"active": ""}, {"active": "false"}],
        mapping=boolean_mapping,
        missing_policy="interpolate",
    )
    assert "active" not in boolean_result.records[1]
    assert boolean_result.issue_counts == {"missing_required": 1}

    integer_mapping = xi.MappingPlan(
        fields=(xi.FieldMapping("count", "count", data_type="integer"),),
        required=("count",),
    )
    integral = xi.normalize_records(
        [{"count": 1}, {"count": ""}, {"count": 3}],
        mapping=integer_mapping,
        missing_policy="interpolate",
    )
    assert integral.records[1]["count"] == 2
    assert isinstance(integral.records[1]["count"], int)

    fractional = xi.normalize_records(
        [{"count": 1}, {"count": ""}, {"count": 2}],
        mapping=integer_mapping,
        missing_policy="interpolate",
    )
    assert "count" not in fractional.records[1]
    assert fractional.issue_counts == {
        "interpolation_type_conflict": 1,
        "missing_required": 1,
    }


def test_integer_interpolation_preserves_values_above_float_precision():
    mapping = xi.MappingPlan(
        fields=(xi.FieldMapping("count", "count", data_type="integer"),),
        required=("count",),
    )

    result = xi.normalize_records(
        [
            {"count": 9_007_199_254_740_992},
            {"count": ""},
            {"count": 9_007_199_254_740_994},
        ],
        mapping=mapping,
        missing_policy="interpolate",
    )

    assert result.records[1]["count"] == 9_007_199_254_740_993


@pytest.mark.parametrize("policy", ["forward-fill", "interpolate"])
def test_imputed_energy_is_always_labeled_mwh(policy):
    mapping = xi.MappingPlan(
        fields=(
            xi.FieldMapping("value", "energy"),
            xi.FieldMapping("source_unit", "unit"),
        ),
        required=("energy",),
    )
    rows = [
        {"value": 1000, "source_unit": "kWh"},
        {"value": "", "source_unit": "kWh"},
        {"value": 3000, "source_unit": "kWh"},
    ]
    result = xi.normalize_records(rows, mapping=mapping, missing_policy=policy)
    assert result.records[1]["energy"] == pytest.approx(
        2 if policy == "interpolate" else 1
    )
    assert result.records[1]["unit"] == "MWh"


def test_conversion_errors_are_auditable():
    mapping = xi.MappingPlan(
        fields=(xi.FieldMapping("energy", "energy", "MWh"),),
        required=("energy",),
    )
    result = xi.normalize_records([{"energy": "not a number"}], mapping=mapping)
    assert result.issue_counts["conversion_error"] == 1
    assert result.issue_counts["missing_required"] == 1


def test_nonfinite_values_are_missing_for_categorical_requirements():
    mapping = xi.MappingPlan(
        fields=(xi.FieldMapping("fuel", "carrier"),), required=("carrier",)
    )
    dropped = xi.normalize_records(
        [{"fuel": float("nan")}], mapping=mapping, missing_policy="drop"
    )
    assert dropped.records == ()
    assert dropped.dropped_rows == (1,)
    assert dropped.issue_counts == {"missing_required": 1}
    with pytest.raises(ValueError, match="missing required fields"):
        xi.normalize_records(
            [{"fuel": float("inf")}], mapping=mapping, missing_policy="raise"
        )


def test_malformed_explicit_value_cannot_fall_back_to_default():
    mapping = xi.MappingPlan(
        fields=(xi.FieldMapping("measured", "energy", "MWh"),),
        defaults={"energy": 123},
        required=("energy",),
        preserve_unmapped=False,
    )
    dropped = xi.normalize_records(
        [{"measured": "bad"}], mapping=mapping, missing_policy="drop"
    )
    assert not dropped.records
    assert dropped.dropped_rows == (1,)
    assert dropped.issue_counts == {"conversion_error": 1, "missing_required": 1}
    with pytest.raises(ValueError, match="missing required fields"):
        xi.normalize_records(
            [{"measured": "bad"}], mapping=mapping, missing_policy="raise"
        )

    defaulted = xi.normalize_records([{"measured": ""}], mapping=mapping)
    assert defaulted.records[0]["energy"] == pytest.approx(123)


def test_preserved_raw_column_cannot_bypass_an_explicit_target_mapping():
    mapping = xi.MappingPlan(
        fields=(xi.FieldMapping("Measured kWh", "energy", "kWh"),),
        required=("energy",),
    )

    result = xi.normalize_records(
        [{"Measured kWh": "", "energy": 999}], mapping=mapping
    )

    assert "energy" not in result.records[0]
    assert result.issue_counts == {"missing_required": 1}


def test_unit_inference_uses_tokens_and_alias_inference_prefers_specific_match():
    thermal = xi.infer_mapping(["Thermal Delivery"])
    assert thermal.fields[0].target == "energy"
    assert thermal.fields[0].unit is None

    energy_price = xi.infer_mapping(["Energy Price ($/MWh)"])
    fuel_price = xi.infer_mapping(["Fuel Price [USD/MWh]"])
    assert energy_price.fields[0].target == "energy_price_per_mwh"
    assert fuel_price.fields[0].target == "energy_price_per_mwh"

    temperature_plan = xi.infer_mapping(["Supply Temp F"])
    assert temperature_plan.fields[0].unit == "F"
    normalized = xi.normalize_records(
        [{"Supply Temp F": 212}], mapping=temperature_plan
    )
    assert normalized.records[0]["source_temperature"] == pytest.approx(100)


def test_inference_does_not_claim_monetary_columns_as_energy():
    mapping = xi.infer_mapping(["Annual Energy Cost", "Energy (MWh)"])

    assert [(field.source, field.target) for field in mapping.fields] == [
        ("Energy (MWh)", "energy")
    ]
    result = xi.normalize_records(
        [{"Annual Energy Cost": 50_000, "Energy (MWh)": 125}], mapping=mapping
    )
    assert result.records[0]["energy"] == pytest.approx(125)


@pytest.mark.parametrize(
    "header",
    [
        "Energy ($)",
        "Energy (EUR €)",
        "Energy (GBP £)",
        "Energy (JPY ¥)",
        "Energy [USD]",
    ],
)
def test_exact_energy_alias_does_not_claim_monetary_columns(header):
    mapping = xi.infer_mapping([header])

    assert not mapping.fields


def test_inference_does_not_treat_power_or_energy_rates_as_energy_totals():
    mapping = xi.infer_mapping(
        ["Energy Use (MW)", "Fuel Use (MMBtu/hr)", "Energy (MWh)"]
    )

    assert [(field.source, field.target) for field in mapping.fields] == [
        ("Energy (MWh)", "energy")
    ]


@pytest.mark.parametrize(
    ("header", "value", "expected_mwh"),
    [
        ("Energy (kW h)", 1000, 1),
        ("Energy (kW-h)", 1000, 1),
        ("Energy (MW h)", 2, 2),
    ],
)
def test_separated_watt_hour_headers_are_energy_not_power(header, value, expected_mwh):
    mapping = xi.infer_mapping([header], required=("energy",))
    result = xi.normalize_records([{header: value}], mapping=mapping)

    assert mapping.fields[0].target == "energy"
    assert result.records[0]["energy"] == pytest.approx(expected_mwh)


def test_inference_rejects_multiple_columns_for_one_canonical_target():
    with pytest.raises(ValueError, match="both infer target 'energy'"):
        xi.infer_mapping(["Energy (kWh)", "Energy (MWh)"])


def test_inference_converts_explicit_efficiency_percent_to_fraction():
    mapping = xi.infer_mapping(["Efficiency (%)"])
    result = xi.normalize_records([{"Efficiency (%)": 85}], mapping=mapping)

    assert mapping.fields[0].unit == "%"
    assert mapping.fields[0].multiplier == pytest.approx(0.01)
    assert result.records[0]["efficiency"] == pytest.approx(0.85)


def test_compact_header_suffixes_preserve_energy_and_temperature_units():
    mapping = xi.infer_mapping(
        ["ElectricityConsumptionKWh", "SupplyTempF", "AmbientTemperatureF"]
    )
    fields = {item.target: item for item in mapping.fields}
    assert fields["energy"].unit == "kWh"
    assert fields["source_temperature"].unit == "F"
    assert fields["ambient_temperature"].unit == "F"
    result = xi.normalize_records(
        [
            {
                "ElectricityConsumptionKWh": 1000,
                "SupplyTempF": 68,
                "AmbientTemperatureF": 32,
            }
        ],
        mapping=mapping,
    )
    assert result.records[0]["energy"] == pytest.approx(1)
    assert result.records[0]["source_temperature"] == pytest.approx(20)
    assert result.records[0]["ambient_temperature"] == pytest.approx(0)


@pytest.mark.parametrize("header", ["T_supply [F]", "Supply Temperature [F]"])
def test_bracketed_temperature_headers_preserve_inferred_units(header):
    mapping = xi.infer_mapping([header])
    result = xi.normalize_records([{header: 140}], mapping=mapping)

    assert mapping.fields[0].target == "source_temperature"
    assert mapping.fields[0].unit == "F"
    assert result.records[0]["source_temperature"] == pytest.approx(60)


def test_inference_covers_every_supported_energy_unit():
    for unit in xi.SUPPORTED_ENERGY_UNITS:
        header = f"Energy ({unit})"
        mapping = xi.infer_mapping([header])
        assert mapping.fields[0].unit == unit
        result = xi.normalize_records([{header: 1}], mapping=mapping)
        assert result.records[0]["energy"] == pytest.approx(
            xi.convert_energy(1, unit, "MWh")
        )


def test_default_energy_uses_its_default_unit_not_an_empty_source_header_unit():
    mapping = xi.infer_mapping(["Energy (kWh)"], defaults={"energy": 1, "unit": "MWh"})
    result = xi.normalize_records([{"Energy (kWh)": ""}], mapping=mapping)
    assert result.records[0]["energy"] == pytest.approx(1)
    assert result.records[0]["unit"] == "MWh"


def test_normalization_preserves_typed_energy_basis_for_downstream_factors():
    mapping = xi.infer_mapping(["Energy (MWh_LHV)", "Fuel"])
    result = xi.normalize_records(
        [{"Energy (MWh_LHV)": 1, "Fuel": "natural gas"}], mapping=mapping
    )
    record = result.records[0]
    assert record["unit"] == "MWh_LHV"
    impacts = xi.assess_impacts(
        record["energy"], unit=record["unit"], carrier=record["carrier"]
    )
    assert impacts.carrier == "methane-lhv"
    assert impacts.assumptions["energy_basis"] == "LHV"


def test_inferred_energy_price_is_scaled_to_per_mwh():
    mapping = xi.infer_mapping(["Electricity Price ($/kWh)"])
    field = mapping.fields[0]
    assert field.target == "energy_price_per_mwh"
    assert field.unit == "kWh"
    assert field.multiplier == pytest.approx(1000)
    result = xi.normalize_records(
        [{"Electricity Price ($/kWh)": 0.10}], mapping=mapping
    )
    assert result.records[0]["energy_price_per_mwh"] == pytest.approx(100)


@pytest.mark.parametrize(
    ("timestamp", "kind"),
    [
        ("2026-03-08T02:30:00", "nonexistent"),
        ("2026-11-01T01:30:00", "ambiguous"),
    ],
)
def test_naive_dst_boundary_timestamps_require_an_explicit_offset(timestamp, kind):
    mapping = xi.MappingPlan(
        fields=(xi.FieldMapping("when", "timestamp"),),
        timezone="America/Denver",
    )
    result = xi.normalize_records([{"when": timestamp}], mapping=mapping)
    assert "timestamp" not in result.records[0]
    assert result.issue_counts == {"conversion_error": 1}
    assert kind in result.issues[0].message

    explicit = xi.normalize_records([{"when": f"{timestamp}-07:00"}], mapping=mapping)
    assert explicit.records[0]["timestamp"].endswith("-07:00")


def test_generic_time_alias_does_not_claim_runtime_or_lifetime_columns():
    mapping = xi.infer_mapping(["runtime_hours", "lifetime_years", "Date Time"])
    targets = {item.source: item.target for item in mapping.fields}
    assert "runtime_hours" not in targets
    assert "lifetime_years" not in targets
    assert targets["Date Time"] == "timestamp"


def test_declared_string_mapping_coerces_numeric_identifiers():
    mapping = xi.MappingPlan(
        fields=(xi.FieldMapping("site_code", "location", data_type="string"),)
    )
    result = xi.normalize_records([{"site_code": 101}], mapping=mapping)
    assert result.records[0]["location"] == "101"
    assert isinstance(result.records[0]["location"], str)


def test_temperature_mapping_composes_type_scaling_and_unit_conversion():
    mapping = xi.MappingPlan(
        fields=(
            xi.FieldMapping(
                "scaled_temp",
                "source_temperature",
                "F",
                multiplier=0.5,
                data_type="number",
            ),
        )
    )
    result = xi.normalize_records([{"scaled_temp": "136"}], mapping=mapping)
    assert result.records[0]["source_temperature"] == pytest.approx(20)


@pytest.mark.parametrize(("value", "expected"), [("68 F", 20), ("20 °C", 20)])
def test_temperature_normalization_preserves_inline_units(value, expected):
    mapping = xi.MappingPlan(
        fields=(xi.FieldMapping("temperature", "source_temperature"),)
    )
    result = xi.normalize_records([{"temperature": value}], mapping=mapping)
    assert result.records[0]["source_temperature"] == pytest.approx(expected)


def test_failed_energy_unit_conversion_invalidates_required_value():
    mapping = xi.MappingPlan(
        fields=(xi.FieldMapping("value", "energy", "invalid-unit"),),
        required=("energy",),
    )
    dropped = xi.normalize_records(
        [{"value": 10}], mapping=mapping, missing_policy="drop"
    )
    assert not dropped.records
    assert dropped.issue_counts == {"unit_error": 1, "missing_required": 1}
    with pytest.raises(ValueError, match="missing required fields"):
        xi.normalize_records([{"value": 10}], mapping=mapping, missing_policy="raise")


@pytest.mark.parametrize("value", [2, -1, 0.5, [], {}])
def test_non_string_boolean_mapping_rejects_values_outside_boolean_domain(value):
    mapping = xi.MappingPlan(
        fields=(xi.FieldMapping("flag", "flag", data_type="boolean"),)
    )
    result = xi.normalize_records([{"flag": value}], mapping=mapping)
    assert "flag" not in result.records[0]
    assert result.issue_counts == {"conversion_error": 1}


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, True), (False, False), (1, True), (0, False), ("yes", True), ("no", False)],
)
def test_boolean_mapping_accepts_only_documented_values(value, expected):
    mapping = xi.MappingPlan(
        fields=(xi.FieldMapping("flag", "flag", data_type="boolean"),)
    )
    result = xi.normalize_records([{"flag": value}], mapping=mapping)
    assert result.records[0]["flag"] is expected
    assert not result.issues


@pytest.mark.parametrize("value", [9_007_199_254_740_993, "9,007,199,254,740,993"])
def test_integer_mapping_preserves_values_above_binary_float_precision(value):
    mapping = xi.MappingPlan(
        fields=(xi.FieldMapping("counter", "counter", data_type="integer"),)
    )
    result = xi.normalize_records([{"counter": value}], mapping=mapping)
    assert result.records[0]["counter"] == 9_007_199_254_740_993
    assert not result.issues


def test_spreadsheet_outputs_neutralize_formula_like_text(tmp_path):
    records = [
        {
            "=unsafe-header": '=HYPERLINK("https://example.com")',
            "safe": "+1+1",
        }
    ]
    csv_path = tmp_path / "safe.csv"
    xlsx_path = tmp_path / "safe.xlsx"
    xi.write_records(records, csv_path)
    xi.write_records(records, xlsx_path)

    csv_text = csv_path.read_text(encoding="utf-8-sig")
    assert "'=unsafe-header" in csv_text
    assert "'=HYPERLINK" in csv_text
    assert "'+1+1" in csv_text

    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.load_workbook(xlsx_path, data_only=False)
    sheet = workbook["Data"]
    assert sheet["A1"].data_type == "s"
    assert sheet["A2"].data_type == "s"
    assert sheet["A2"].value.startswith("'=")
    workbook.close()


def test_read_write_records_and_excel_compatible_bundle(tmp_path):
    source = tmp_path / "input.csv"
    source.write_text("Energy (kWh),Fuel\n1000,natural gas\n", encoding="utf-8")
    rows = xi.read_records(source)
    result = xi.normalize_records(rows)
    outputs = xi.export_excel_compatible_bundle(result, tmp_path / "excel")
    assert {path.name for path in outputs} == {
        "raw_records.csv",
        "normalized_records.csv",
        "data_quality_issues.csv",
        "mapping.json",
    }
    with (tmp_path / "excel" / "normalized_records.csv").open(
        encoding="utf-8-sig"
    ) as handle:
        normalized = list(csv.DictReader(handle))
    assert float(normalized[0]["energy"]) == pytest.approx(1)
    mapping = json.loads((tmp_path / "excel" / "mapping.json").read_text())
    assert mapping["schema_version"] == "1.0"
    assert mapping["missing_policy"] == "keep"


@pytest.mark.parametrize(("suffix", "delimiter"), [(".csv", ","), (".tsv", "\t")])
def test_csv_and_tsv_header_row_is_applied_and_validated(tmp_path, suffix, delimiter):
    source = tmp_path / f"publisher{suffix}"
    source.write_text(
        f"Publisher metadata{delimiter}release 2026\n"
        f"Energy (MWh){delimiter}Site\n"
        f"1{delimiter}A\n",
        encoding="utf-8",
    )
    assert xi.read_records(source, header_row=2) == [{"Energy (MWh)": "1", "Site": "A"}]
    with pytest.raises(ValueError, match="positive one-based"):
        xi.read_records(source, header_row=0)
    with pytest.raises(ValueError, match="exceeds"):
        xi.read_records(source, header_row=10)
    for invalid in (True, float("nan"), float("inf"), 1.5):
        with pytest.raises(ValueError, match="positive one-based"):
            xi.read_records(source, header_row=invalid)


@pytest.mark.parametrize(("suffix", "delimiter"), [(".csv", ","), (".tsv", "\t")])
def test_delimited_readers_skip_fully_blank_data_rows(tmp_path, suffix, delimiter):
    source = tmp_path / f"blank-rows{suffix}"
    source.write_text(
        f"Energy{delimiter}Site\n1{delimiter}A\n{delimiter}\n\n2{delimiter}B\n",
        encoding="utf-8",
    )

    assert xi.read_records(source) == [
        {"Energy": "1", "Site": "A"},
        {"Energy": "2", "Site": "B"},
    ]


@pytest.mark.parametrize("header", ["energy,energy\n1,2\n", "energy, \n1,2\n"])
def test_tabular_headers_cannot_silently_lose_columns(tmp_path, header):
    source = tmp_path / "ambiguous.csv"
    source.write_text(header, encoding="utf-8")
    with pytest.raises(ValueError, match="headers|header names"):
        xi.read_records(source)


def test_csv_reader_rejects_rows_wider_than_header(tmp_path):
    source = tmp_path / "ragged.csv"
    source.write_text("Energy,Site\n1,A,unexpected\n", encoding="utf-8")

    with pytest.raises(ValueError, match="row 2 has 3 values"):
        xi.read_records(source)


def test_excel_numeric_column_gaps_are_normalized_to_none(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    pytest.importorskip("pandas")
    source = tmp_path / "gaps.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Energy (MWh)", "Site"])
    sheet.append([1.0, "A"])
    sheet.append([None, "B"])
    workbook.save(source)
    workbook.close()

    rows = xi.read_records(source)
    assert rows[1]["Energy (MWh)"] is None
    output = tmp_path / "records.json"
    xi.write_records(rows, output)
    text = output.read_text(encoding="utf-8")
    assert "NaN" not in text
    assert json.loads(text)[1]["Energy (MWh)"] is None


@pytest.mark.parametrize(
    "headers",
    [
        ["Energy", "Energy"],
        ["Energy", None],
        ["Energy", "   "],
    ],
)
def test_excel_headers_cannot_be_silently_mangled(tmp_path, headers):
    openpyxl = pytest.importorskip("openpyxl")
    pytest.importorskip("pandas")
    source = tmp_path / "ambiguous.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(headers)
    sheet.append([1, 2])
    workbook.save(source)
    workbook.close()

    with pytest.raises(ValueError, match="headers|header names"):
        xi.read_records(source)


def test_excel_header_row_is_validated_before_pandas_parsing(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    pytest.importorskip("pandas")
    source = tmp_path / "publisher.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Publisher metadata", "release 2026"])
    sheet.append(["Energy", "Energy"])
    sheet.append([1, 2])
    workbook.save(source)
    workbook.close()

    with pytest.raises(ValueError, match="duplicate tabular headers.*Energy"):
        xi.read_records(source, header_row=2)


def test_json_and_jsonl_ingestion(tmp_path):
    json_path = tmp_path / "records.json"
    jsonl_path = tmp_path / "records.jsonl"
    json_path.write_text(json.dumps({"records": [{"energy": 1}]}))
    jsonl_path.write_text('{"energy": 2}\n')
    assert xi.read_records(json_path) == [{"energy": 1}]
    assert xi.read_records(jsonl_path) == [{"energy": 2}]


def test_excel_dates_and_tabular_scalars_are_json_serializable(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    source = tmp_path / "dated.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Date", "Energy (kWh)"])
    sheet.append(["2026-01-01", 100])
    sheet["A2"] = __import__("datetime").datetime(2026, 1, 1)
    workbook.save(source)
    workbook.close()

    rows = xi.read_records(source)
    normalized = xi.normalize_records(rows)
    output = tmp_path / "dated.json"
    xi.write_records(normalized.records, output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload[0]["Date"].startswith("2026-01-01")
    assert payload[0]["energy"] == pytest.approx(0.1)


def test_sqlite_ingestion(tmp_path):
    path = tmp_path / "telemetry.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("create table readings (energy real, carrier text)")
        connection.execute("insert into readings values (?, ?)", (10, "electricity"))
        connection.commit()
    rows = xi.read_sqlite_records(path, "select * from readings where energy > ?", (5,))
    assert rows == [{"energy": 10.0, "carrier": "electricity"}]


def test_sql_ingestion_rejects_duplicate_result_columns(tmp_path):
    path = tmp_path / "ambiguous.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("create table left_reading (id integer)")
        connection.execute("create table right_reading (id integer)")
        connection.execute("insert into left_reading values (1)")
        connection.execute("insert into right_reading values (2)")
        connection.commit()
    with pytest.raises(ValueError, match="duplicate SQL result columns.*id"):
        xi.read_sqlite_records(
            path,
            "select left_reading.id, right_reading.id "
            "from left_reading cross join right_reading",
        )
    rows = xi.read_sqlite_records(
        path,
        "select left_reading.id as left_id, right_reading.id as right_id "
        "from left_reading cross join right_reading",
    )
    assert rows == [{"left_id": 1, "right_id": 2}]


def test_sqlite_reader_does_not_create_a_missing_database(tmp_path):
    path = tmp_path / "missing.sqlite"

    with pytest.raises(FileNotFoundError, match="does not exist"):
        xi.read_sqlite_records(path, "select 1")

    assert not path.exists()


def test_database_decimal_values_export_to_json(tmp_path):
    class Cursor:
        description = (("amount",), ("count",))

        def execute(self, query, parameters):
            assert query == "select amount, count from costs"
            assert parameters == ()

        def fetchall(self):
            return [(Decimal("1.25"), Decimal("2"))]

        def close(self):
            self.closed = True

    class Connection:
        def cursor(self):
            return Cursor()

    rows = xi.read_sql_records(Connection(), "select amount, count from costs")
    output = tmp_path / "database.json"
    xi.write_records(rows, output)
    assert json.loads(output.read_text(encoding="utf-8")) == [
        {"amount": 1.25, "count": 2}
    ]


def test_ingestion_result_dictionary_is_json_compatible():
    timestamp = __import__("datetime").datetime(2026, 1, 1, 12, 0)
    clock = time(14, 30, tzinfo=timezone(timedelta(hours=-7)))
    result = xi.normalize_records(
        [
            {
                "timestamp_object": timestamp,
                "clock_object": clock,
                "amount": Decimal("1.25"),
            }
        ],
        mapping=xi.MappingPlan(fields=()),
    )
    payload = result.to_dict()
    json.dumps(payload)
    assert payload["records"][0] == {
        "timestamp_object": "2026-01-01T12:00:00",
        "clock_object": "14:30:00-07:00",
        "amount": pytest.approx(1.25),
    }


@pytest.mark.parametrize("suffix", [".json", ".jsonl"])
def test_time_values_export_to_json_formats(tmp_path, suffix):
    path = tmp_path / f"times{suffix}"
    xi.write_records([{"clock": time(9, 15, 30)}], path)
    text = path.read_text(encoding="utf-8")
    payload = json.loads(text) if suffix == ".json" else json.loads(text.strip())
    record = payload[0] if suffix == ".json" else payload
    assert record == {"clock": "09:15:30"}


def test_write_mapping_roundtrip(tmp_path):
    plan = xi.MappingPlan(
        fields=(xi.FieldMapping("Fuel", "carrier"),),
        defaults={"country": "USA"},
        missing_policy="interpolate",
    )
    path = tmp_path / "mapping.json"
    xi.write_mapping(plan, path)
    assert xi.load_mapping(path) == plan


def test_loaded_mapping_applies_its_saved_missing_policy(tmp_path):
    plan = xi.MappingPlan(
        fields=(xi.FieldMapping("value", "energy", "MWh"),),
        required=("energy",),
        missing_policy="drop",
    )
    path = tmp_path / "mapping.json"
    xi.write_mapping(plan, path)

    result = xi.normalize_records([{"value": ""}], mapping=xi.load_mapping(path))

    assert result.missing_policy == "drop"
    assert result.dropped_rows == (1,)
    assert result.mapping.missing_policy == "drop"
