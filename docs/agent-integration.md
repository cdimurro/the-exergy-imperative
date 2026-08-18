# Agent integration

`exergy-imperative` exposes the same deterministic scientific calculations
through Python recipes, a JSON CLI, and an optional Model Context Protocol
server. The agent layer does not duplicate equations or factor data; it calls
the reviewed public library APIs and returns versioned, machine-readable
contracts.

## Install

The recipe and JSON CLI interfaces are included in the base package. Install
the MCP extra only when an MCP host will use the library:

```bash
python -m pip install "exergy-imperative[mcp]"
```

Add `data`, `reports`, or `properties` when Excel/Parquet readers, PDF reports,
or CoolProp calculations are required:

```bash
python -m pip install "exergy-imperative[mcp,data,reports,properties]"
```

## Discover before calling

```bash
exergy capabilities --json
exergy describe process-assessment --kind workflow --json
exergy describe steam --kind process --json
exergy schema agent-recipe --json
```

The capability document lists every workflow, alias, input schema, default,
output schema, supported export format, and safety behavior. It is also
available in Python:

```python
import exergy_imperative as xi

capabilities = xi.list_capabilities()
process_contract = xi.describe_workflow("process-assessment")
```

## Stable recipe contract

```json
{
  "schema_version": "1.0",
  "workflow": "process-assessment",
  "inputs": {
    "template": "steam",
    "energy": 10000,
    "unit": "MWh",
    "country": "USA"
  },
  "outputs": {
    "html": "output/steam.html",
    "json": "output/steam.json"
  }
}
```

Run it from Python:

```python
response = xi.run_recipe(recipe, mode="dry-run")
payload = response.to_dict()
```

Or from the CLI:

```bash
exergy run examples/agent_process_recipe.json --validate-only --json
exergy run examples/agent_process_recipe.json --dry-run --json
exergy run examples/agent_process_recipe.json --json
```

Modes have strict behavior:

- `validate-only` checks workflow names, fields, required inputs, JSON types,
  enum values, output formats, and paths. It does not calculate or write.
- `dry-run` performs calculations so the agent can inspect selected profiles,
  assumptions, warnings, Fidelity Tier, and refinements. It never writes files.
- `execute` performs the calculation and writes only the output paths explicitly
  included in the recipe.

Recipe workflows never make implicit network requests. NASA POWER access
remains an explicit human or application action outside the generic dispatcher.

## Response and error envelopes

Successful recipe responses contain:

```json
{
  "schema_version": "1.0",
  "contract": "exergy-agent-response",
  "ok": true,
  "workflow": "assessment",
  "mode": "dry-run",
  "artifacts": [],
  "result": {},
  "plan": {}
}
```

Recoverable errors contain stable codes and corrective information:

```json
{
  "schema_version": "1.0",
  "contract": "exergy-agent-response",
  "ok": false,
  "error": {
    "code": "MISSING_ENERGY_BASIS",
    "message": "Absolute mass inputs require an explicit energy quantity.",
    "retryable": false,
    "suggested_fields": ["energy", "unit"],
    "hint": "For a normalized result, use per-MWh factor inputs."
  }
}
```

In CLI JSON mode, standard output contains only successful JSON. Structured
errors are written to standard error, and invalid input returns exit code 2.

## MCP server

Start the local stdio server with:

```bash
exergy-mcp
```

A generic MCP host configuration is:

```json
{
  "mcpServers": {
    "exergy-imperative": {
      "command": "exergy-mcp",
      "args": ["--transport", "stdio"]
    }
  }
}
```

The server exposes these tools:

- `capabilities`
- `describe_workflow`
- `run_workflow`
- `calculate_exergy`
- `assess_process`
- `screen_impacts`
- `evaluate_project_economics`
- `normalize_dataset`
- `generate_report`
- `list_profiles`
- `public_datasets`

Resources are available at `exergy://capabilities`, `exergy://datasets`,
`exergy://schema/{name}`, and `exergy://process-templates`. The
`plan_exergy_assessment` prompt helps a user or agent select a workflow without
misrepresenting screening defaults as measurements.

For a deployed service, Streamable HTTP is available explicitly:

```bash
exergy-mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

Stdio is the preferred local integration. Do not expose the HTTP transport
beyond a trusted local network without appropriate authentication, TLS,
request-size controls, and transport-security configuration.

## MCP side effects

Calculation, discovery, and normalization tools operate in memory. Only
`generate_report` or a generic execute-mode recipe with an `outputs` object
writes files. The tool returns every written artifact path in its response.

Publisher datasets are never sent to a remote service by this integration.
The `public_datasets` MCP tool and `catalog.datasets` capability collection
describe each integration's access mode, Python API, CLI command, optional
extra, source terms, and limitations. They do not fetch anything. World Bank,
NASA POWER, and ERA5 network access occurs only through an explicitly invoked
connector; EDGAR, eGRID, ITAC/IAC, and FIED remain local-file workflows.
Agents remain responsible for the licenses and access boundaries of local files
they choose to read before passing permitted records to `normalize_dataset`.
