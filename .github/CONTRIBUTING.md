# Contributing

Contributions are welcome, especially reviewed profiles, validation cases, new
dataset adapters, unit tests, and documentation from underrepresented regions
and industries.

## Development

```bash
python -m pip install -e ".[dev]"
python -m ruff check src tests examples scripts
python -m pytest --cov=exergy_imperative --cov-report=term-missing
python -m build
python -m twine check dist/*
```

## Data contributions

Every contributed default must include:

- a stable ID and applicable industry/geography;
- units, basis, and boundary;
- central value and a defensible range where appropriate;
- source, version, and redistributable license;
- confidence or data-quality description;
- tests for lookup and at least one resulting calculation.

Avoid false precision. A narrow range must be justified by evidence.

The global electricity pack is rebuilt explicitly with
`python scripts/update_global_electricity.py`. Review the source attribution,
record count, representative countries, years, and fallback behavior before
committing an update. Never replace an older year with a newer factor silently.

Health-related contributions must distinguish emissions, ambient concentration,
exposure, risk, and monetized damage. Bundled text may describe established
hazards, but location-specific exposure or damage factors require an applicable
source and must remain overrideable.

Do not commit commercial, restricted, or non-redistributable workbooks. A local
dataset adapter may name the expected source and columns, but must contain no
publisher values, access credentials, or content copied from the workbook.

## Code contributions

Add tests for scientific formulas, validation behavior, serialization, and the
public API. By submitting a contribution, you agree that software contributions
are licensed under Apache-2.0. Documentation and reference-data contributions
are licensed under CC BY 4.0 unless clearly identified otherwise.

Agent-facing changes must preserve the recipe `1.0` contract, structured error
codes, JSON-only standard output, and the guarantee that validate-only and
dry-run modes never write files. Update capability metadata, packaged schemas,
MCP in-memory tests, and `docs/agent-integration.md` when changing an exposed
workflow.
