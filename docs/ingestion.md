# Universal ingestion and Excel-compatible workflows

## Supported sources

`read_records()` accepts CSV, TSV, JSON, JSONL, Excel, XLSB, and Parquet files. Excel
and Parquet use the optional `data` extra. `read_sqlite_records()` and
`read_sql_records()` support local SQLite and any compatible DB-API connection.

No source row is overwritten. `IngestionResult` retains separate raw and
normalized records, the exact mapping, and structured issues.

## Mapping

`infer_mapping()` recognizes common variants for timestamps, energy,
ambient/supply/return/cold temperatures, efficiency, COP, carrier, technology,
service, and location. Units in headers such as
`Energy (kWh)` or `Supply Temp F` are converted to canonical values.

Review and save the inferred plan:

```python
rows = xi.read_records("plant.csv")
plan = xi.infer_mapping(
    rows[0],
    required=("timestamp", "energy"),
    timezone="America/Denver",
)
xi.write_mapping(plan, "plant-mapping.json")
```

Mappings can set defaults, multipliers, required fields, and whether unmapped
columns are preserved.

## Missing values

`normalize_records()` supports five explicit policies:

- `keep`: retain the row and record an issue;
- `drop`: remove rows missing required fields;
- `raise`: stop on missing required data;
- `forward-fill`: use the prior normalized value;
- `interpolate`: linearly fill internal gaps in numeric fields.

Interpolation does not invent endpoints. Always retain the issue table and
report the selected policy with results.

## Excel-compatible outputs

Use `create_excel_template()` for editable input workbooks and
`export_xlsx_report()` for a single native `.xlsx` report with charts, sources,
warnings, tables, and metadata. `adapt_local_dataset()` applies a versioned JSON
adapter to a local publisher or plant workbook while retaining its audit trail.

The dependency-free export remains useful for transparent automation:

`IngestionResult.export_excel_compatible()` writes:

- `raw_records.csv` for untouched source data;
- `normalized_records.csv` for canonical values;
- `data_quality_issues.csv` for data-quality findings;
- `mapping.json` for the complete mapping and selected missing-value policy.

Native ingestion workbooks retain the field mappings and a separate `Mapping Plan`
sheet containing defaults, required fields, timezone, unmapped-column behavior, and
the selected missing-value policy.

Files are UTF-8 with a byte-order mark for reliable Excel import. Report exports
similarly write a summary, one CSV per table, sources, and JSON metadata. This
format stays transparent, diffable, and compatible with Excel, LibreOffice,
Google Sheets, databases, and Python without forcing spreadsheet software into
the base installation.
