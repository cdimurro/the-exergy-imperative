# Agent guide

These instructions apply to the entire repository.

## Purpose

Exergy Imperative is a progressive-fidelity engineering library. Preserve the
distinction between energy quantity, exergy quality, emissions, pollutant
hazards, and economics. Screening defaults must never be presented as
measurements or site-specific design results.

## Development setup

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check src tests examples scripts
python -m ruff format --check src tests examples scripts
```

Before release-related work, also run:

```bash
python -m pytest --cov=exergy_imperative --cov-report=term-missing
python examples/quickstart.py
python examples/engineering_workflows.py
python -m build
python -m twine check dist/*
```

## Stable public surfaces

- Python imports exported from `exergy_imperative.__init__`.
- Existing `exergy` CLI commands and their exit codes.
- Agent recipe contract version `1.0` in `exergy_imperative.agent`.
- Packaged JSON Schemas under `src/exergy_imperative/data/schemas`.
- MCP tools created by `exergy_imperative.mcp_server.create_mcp_server`.

Changes to these surfaces must remain backward compatible within the current
minor version or be accompanied by a documented version change, schema update,
and regression tests.

## Agent-native workflow

Use `list_capabilities()` or `exergy capabilities --json` before constructing
an unfamiliar recipe. Prefer this sequence:

1. `validate-only` for contract validation without calculations or writes.
2. `dry-run` to calculate and inspect defaults while suppressing file writes.
3. `execute` only when the caller explicitly requested calculation and any
   output paths.

Agent errors must retain stable codes, corrective hints, and suggested fields.
Standard output in JSON mode and MCP stdio output must never contain logs or
informal prose.

## Scientific and data rules

- Preserve units, HHV/LHV basis, boundaries, source versions, warnings, and
  Fidelity Tiers.
- Reject nonfinite numbers and ambiguous absolute-versus-normalized inventories.
- Do not silently substitute an unknown geography, profile, year, or unit.
- Add a source, license, applicable boundary, range, and tests for new defaults.
- Do not commit proprietary IEA, Energy Institute, or other restricted source
  data. Local adapters may contain field mappings but no publisher values.
- Pollutant outputs are inventory and hazard screens unless a dedicated,
  sourced exposure model is explicitly implemented.

## Change checklist

- Add focused tests for successful results, invalid inputs, serialization, and
  agent error recovery.
- Update capability metadata and schemas when a workflow changes.
- Test MCP behavior with the in-memory `mcp.Client`; do not open a port in unit
  tests.
- Keep the base package dependency-light. Optional data, report, property, and
  MCP dependencies belong in their extras.
- Never add implicit network access or file writes to recipe dry-run or
  validate-only modes.
