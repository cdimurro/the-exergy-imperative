# Native Excel and local licensed-data workflows

Install the data extra:

```bash
python -m pip install "exergy-imperative[data]"
```

## Editable input workbooks

Create a workbook, edit the yellow input cells, and run it:

```bash
exergy excel-template heat-pump heat-pump-input.xlsx
exergy excel-run heat-pump-input.xlsx --output heat-pump-report.xlsx
```

Templates are available for process assessments, technology economics, GHG
boundaries, methane projects, weather normalization, steam, heat pumps,
furnaces, refrigeration, and compressed air. Python users can call
`create_excel_template()`, `read_excel_template()`, and `run_excel_template()`.

Native report workbooks contain a formatted summary, one sheet per result
table, Excel chart objects, a hidden chart-data sheet, sources, warnings, and a
machine-readable source payload in the Metadata sheet. The existing CSV/JSON
bundle remains available for version-control-friendly workflows.

## User-owned licensed datasets

`adapt_local_dataset()` applies a declarative JSON mapping to a local CSV,
Excel, XLSB, Parquet, JSON, or JSONL file. It does not download or upload the
file. The result retains:

- the adapter and licensing notice;
- the resolved local path, file size, and SHA-256 fingerprint;
- untouched raw records and normalized records;
- conversions, dropped rows, and structured data-quality issues.

```python
result = xi.adapt_local_dataset(
    "my-downloaded-workbook.xlsx",
    "iea-ghg-energy",
    missing_policy="drop",
)
result.export_xlsx("normalized-with-audit-trail.xlsx")
```

Two installed adapters show how to convert Energy Institute total-energy-supply
and IEA energy-related GHG highlight sheets from wide years to tidy records.
They contain field instructions only—no publisher values—and must be reviewed
against the exact workbook release the user obtained. The user remains
responsible for access rights, licensing, derived uses, and redistribution.

Adapter definitions are versioned by the
`local-dataset-adapter` JSON Schema. Changes in publisher workbook layout should
produce a new adapter ID or version rather than silently changing an existing
mapping.

Use `xi.list_bundled_adapters()` to list their stable names and
`xi.load_bundled_adapter(name)` to inspect the complete field instructions and
licensing notice without locating package files on disk.
