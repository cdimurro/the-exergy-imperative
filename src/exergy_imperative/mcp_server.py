"""Optional Model Context Protocol server for exergy-imperative workflows."""

from __future__ import annotations

import argparse
import json
from typing import Any, Mapping, Sequence

from .agent import (
    LIBRARY_VERSION,
    error_response,
    safe_run_recipe,
)
from .agent import (
    describe_workflow as describe_workflow_contract,
)
from .agent import (
    list_capabilities as agent_capabilities,
)
from .agent import search_capabilities as search_agent_capabilities
from .datasets import list_datasets
from .packs import bundled_technology_pack_info, technology_pack_coverage
from .processes import list_process_templates
from .registry import DEFAULT_REGISTRY
from .schema import load_schema


def _mcp_server_class() -> Any:
    try:
        from mcp.server import MCPServer
    except ImportError as exc:  # pragma: no cover - exercised without the extra
        raise ImportError(
            'MCP support requires `python -m pip install "exergy-imperative[mcp]"`'
        ) from exc
    return MCPServer


def _recipe(workflow: str, inputs: Mapping[str, Any], mode: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "workflow": workflow,
        "mode": mode,
        "inputs": dict(inputs),
    }


def create_mcp_server() -> Any:
    """Create the MCP server without starting a transport."""

    MCPServer = _mcp_server_class()
    server = MCPServer(
        "exergy-imperative",
        instructions=(
            "Use these deterministic tools for exergy, emissions, pollutant-hazard, "
            "economic, engineering, data-normalization, and report workflows. "
            "Start with capabilities or describe_workflow when input requirements "
            "are unclear. Use validate-only before unfamiliar recipes and dry-run "
            "before requesting file outputs."
        ),
    )

    @server.tool()
    def capabilities() -> dict[str, Any]:
        """List workflows, input contracts, output schemas, and safety behavior."""

        return agent_capabilities()

    @server.tool()
    def describe_workflow(name: str) -> dict[str, Any]:
        """Describe one workflow's accepted inputs, defaults, and outputs."""

        try:
            return {
                "schema_version": "1.0",
                "ok": True,
                "workflow": describe_workflow_contract(name),
            }
        except Exception as exc:
            return error_response(exc, command="describe_workflow")

    @server.tool()
    def search_capabilities(
        query: str, kind: str = "auto", limit: int = 10
    ) -> dict[str, Any]:
        """Find applicable workflows, profiles, components, packs, and schemas."""

        try:
            return search_agent_capabilities(query, kind=kind, limit=limit)
        except Exception as exc:
            return error_response(exc, command="search_capabilities")

    @server.tool()
    def run_workflow(recipe: dict[str, Any], mode: str | None = None) -> dict[str, Any]:
        """Run any stable exergy-imperative recipe in execute, dry-run, or validate-only mode."""

        return safe_run_recipe(recipe, mode=mode)

    @server.tool()
    def calculate_exergy(
        inputs: dict[str, Any], mode: str = "execute"
    ) -> dict[str, Any]:
        """Assess a carrier, service, or technology with progressive-fidelity exergy accounting."""

        return safe_run_recipe(_recipe("assessment", inputs, mode))

    @server.tool()
    def assess_process(inputs: dict[str, Any], mode: str = "execute") -> dict[str, Any]:
        """Run an integrated process exergy, impact, opportunity, and economic assessment."""

        return safe_run_recipe(_recipe("process-assessment", inputs, mode))

    @server.tool()
    def screen_impacts(inputs: dict[str, Any], mode: str = "execute") -> dict[str, Any]:
        """Screen greenhouse gases, warming horizons, pollutants, and health hazards."""

        return safe_run_recipe(_recipe("impacts", inputs, mode))

    @server.tool()
    def evaluate_project_economics(
        inputs: dict[str, Any], mode: str = "execute"
    ) -> dict[str, Any]:
        """Calculate project cash flow, payback, levelized costs, and abatement economics."""

        return safe_run_recipe(_recipe("economics", inputs, mode))

    @server.tool()
    def normalize_dataset(
        records: list[dict[str, Any]],
        mapping: dict[str, Any] | None = None,
        required: list[str] | None = None,
        timezone: str | None = None,
        missing_policy: str | None = None,
    ) -> dict[str, Any]:
        """Infer or apply a mapping and normalize in-memory industrial records."""

        inputs: dict[str, Any] = {
            "records": records,
            "include_records": True,
        }
        if mapping is not None:
            inputs["mapping"] = mapping
        if required is not None:
            inputs["required"] = required
        if timezone is not None:
            inputs["timezone"] = timezone
        if missing_policy is not None:
            inputs["missing_policy"] = missing_policy
        return safe_run_recipe(_recipe("normalize-records", inputs, "execute"))

    @server.tool()
    def analyze_system(inputs: dict[str, Any], mode: str = "execute") -> dict[str, Any]:
        """Account for energy and exergy across arbitrary connected components."""

        return safe_run_recipe(_recipe("system-analysis", inputs, mode))

    @server.tool()
    def analyze_system_timeseries(
        inputs: dict[str, Any], mode: str = "execute"
    ) -> dict[str, Any]:
        """Aggregate chronological system records supplied as interval quantities."""

        return safe_run_recipe(_recipe("system-timeseries", inputs, mode))

    @server.tool()
    def analyze_material_balance(
        inputs: dict[str, Any], mode: str = "execute"
    ) -> dict[str, Any]:
        """Account for mass, composition, and explicitly supplied chemical exergy."""

        return safe_run_recipe(_recipe("material-balance", inputs, mode))

    @server.tool()
    def evaluate_technology_model(
        inputs: dict[str, Any], mode: str = "execute"
    ) -> dict[str, Any]:
        """Evaluate a registered explicit-performance technology model."""

        return safe_run_recipe(_recipe("technology-model", inputs, mode))

    @server.tool()
    def estimate_technology_intensity(
        inputs: dict[str, Any], mode: str = "execute"
    ) -> dict[str, Any]:
        """Estimate process energy from a sourced mass-normalized pack prior."""

        return safe_run_recipe(_recipe("technology-intensity", inputs, mode))

    @server.tool()
    def estimate_technology_performance(
        inputs: dict[str, Any], mode: str = "execute"
    ) -> dict[str, Any]:
        """Estimate energy output without silently assuming an exergy factor."""

        return safe_run_recipe(_recipe("technology-performance", inputs, mode))

    @server.tool()
    def validate_technology_pack(
        pack: dict[str, Any] | str, mode: str = "execute"
    ) -> dict[str, Any]:
        """Validate an inline, bundled, or explicitly named local technology pack."""

        return safe_run_recipe(
            _recipe("technology-pack-validation", {"pack": pack}, mode)
        )

    @server.tool()
    def generate_report(
        recipe: dict[str, Any], outputs: dict[str, str]
    ) -> dict[str, Any]:
        """Execute a recipe and write only the explicitly requested report paths."""

        payload = dict(recipe)
        payload["outputs"] = dict(outputs)
        payload["mode"] = "execute"
        return safe_run_recipe(payload, mode="execute")

    @server.tool()
    def list_profiles(category: str | None = None) -> dict[str, Any]:
        """List bundled carrier, service, technology, or reference profiles."""

        try:
            items = DEFAULT_REGISTRY.list(category)
            return {
                "schema_version": "1.0",
                "ok": True,
                "category": category,
                "profiles": [item.to_dict() for item in items],
            }
        except Exception as exc:
            return error_response(exc, command="list_profiles")

    @server.tool()
    def public_datasets() -> dict[str, Any]:
        """List opt-in public-data connectors, local adapters, and source terms."""

        return {
            "schema_version": "1.0",
            "datasets": [item.to_dict() for item in list_datasets()],
        }

    @server.tool()
    def technology_packs() -> dict[str, Any]:
        """List bundled data-only domain packs and their default policy."""

        return {
            "schema_version": "1.0",
            "packs": list(bundled_technology_pack_info()),
        }

    @server.tool()
    def technology_pack_default_coverage(pack: str) -> dict[str, Any]:
        """Show which pack technologies have sourced defaults and which need inputs."""

        try:
            return technology_pack_coverage(pack)
        except Exception as exc:
            return error_response(exc, command="technology_pack_default_coverage")

    @server.resource("exergy://capabilities")
    def capabilities_resource() -> str:
        """Machine-readable exergy-imperative agent capabilities."""

        return json.dumps(agent_capabilities(), ensure_ascii=False, sort_keys=True)

    @server.resource("exergy://schema/{name}")
    def schema_resource(name: str) -> str:
        """One packaged JSON Schema by stable name."""

        return json.dumps(load_schema(name), ensure_ascii=False, sort_keys=True)

    @server.resource("exergy://process-templates")
    def process_templates_resource() -> str:
        """Bundled cross-industry process template metadata."""

        return json.dumps(
            [item.to_dict() for item in list_process_templates()],
            ensure_ascii=False,
            sort_keys=True,
        )

    @server.resource("exergy://datasets")
    def datasets_resource() -> str:
        """Dataset access modes, coverage, capabilities, and source terms."""

        return json.dumps(
            [item.to_dict() for item in list_datasets()],
            ensure_ascii=False,
            sort_keys=True,
        )

    @server.resource("exergy://technology-packs")
    def technology_packs_resource() -> str:
        """Bundled domain-pack identifiers, scope, and default policy."""

        return json.dumps(
            list(bundled_technology_pack_info()),
            ensure_ascii=False,
            sort_keys=True,
        )

    @server.prompt()
    def plan_exergy_assessment(goal: str, known_inputs: str = "") -> str:
        """Plan a transparent assessment before calling calculation tools."""

        return (
            "Plan an exergy-imperative assessment for the following goal. "
            "Use capabilities and describe_workflow first, prefer a sparse "
            "validate-only recipe, then dry-run it. Never present screening defaults "
            "as measurements, and preserve all assumptions, sources, warnings, and "
            "Fidelity Tiers in the answer.\n\n"
            f"Goal: {goal}\nKnown inputs: {known_inputs or 'not specified'}"
        )

    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="exergy-mcp",
        description="Serve exergy-imperative tools over Model Context Protocol.",
    )
    parser.add_argument("--version", action="version", version=LIBRARY_VERSION)
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--path", default="/mcp")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Start the optional MCP server; stdio is the safe local default."""

    args = build_parser().parse_args(argv)
    server = create_mcp_server()
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            streamable_http_path=args.path,
            stateless_http=True,
            json_response=True,
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
