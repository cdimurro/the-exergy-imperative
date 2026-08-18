import json

import pytest

from exergy_imperative.mcp_server import create_mcp_server

Client = pytest.importorskip("mcp").Client


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_mcp_server_discovers_and_calls_structured_tools():
    server = create_mcp_server()
    async with Client(server, raise_exceptions=True) as client:
        listed = await client.list_tools()
        tool_names = {tool.name for tool in listed.tools}
        assert tool_names >= {
            "capabilities",
            "run_workflow",
            "calculate_exergy",
            "assess_process",
            "screen_impacts",
            "evaluate_project_economics",
            "normalize_dataset",
            "generate_report",
            "list_profiles",
            "public_datasets",
            "search_capabilities",
            "analyze_system",
            "analyze_system_timeseries",
            "analyze_material_balance",
            "evaluate_technology_model",
            "estimate_technology_performance",
            "estimate_technology_intensity",
            "validate_technology_pack",
            "technology_pack_default_coverage",
            "technology_packs",
        }

        result = await client.call_tool(
            "calculate_exergy",
            {
                "inputs": {"technology": "air-source heat pump"},
                "mode": "dry-run",
            },
        )
        assert not result.is_error
        assert result.structured_content["ok"] is True
        assert result.structured_content["result"]["tier"] == "F1"

        searched = await client.call_tool(
            "search_capabilities", {"query": "ground source heat pump"}
        )
        assert any(
            item["kind"] == "pack" for item in searched.structured_content["matches"]
        )


@pytest.mark.anyio
async def test_mcp_tools_return_recoverable_domain_errors():
    server = create_mcp_server()
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "screen_impacts",
            {"inputs": {"gases_kg": {"CO2": 1}}},
        )
        assert not result.is_error
        assert result.structured_content["ok"] is False
        assert result.structured_content["error"]["code"] == "MISSING_ENERGY_BASIS"


@pytest.mark.anyio
async def test_mcp_normalization_and_explicit_report_artifacts(tmp_path):
    server = create_mcp_server()
    async with Client(server, raise_exceptions=True) as client:
        normalized = await client.call_tool(
            "normalize_dataset",
            {"records": [{"Energy (kWh)": 1000, "Fuel": "natural gas"}]},
        )
        assert normalized.structured_content["ok"] is True
        assert normalized.structured_content["result"]["records"][0]["energy"] == 1

        output = tmp_path / "mcp-assessment.json"
        reported = await client.call_tool(
            "generate_report",
            {
                "recipe": {
                    "workflow": "assessment",
                    "inputs": {"technology": "air-source heat pump"},
                },
                "outputs": {"json": str(output)},
            },
        )
        assert reported.structured_content["ok"] is True
        assert reported.structured_content["artifacts"][0]["path"] == str(output)
        assert output.exists()


@pytest.mark.anyio
async def test_mcp_capability_resource_is_machine_readable():
    server = create_mcp_server()
    async with Client(server, raise_exceptions=True) as client:
        result = await client.read_resource("exergy://capabilities")
        payload = json.loads(result.contents[0].text)
        assert payload["contract"] == "exergy-agent-capabilities"
        assert payload["workflows"]


@pytest.mark.anyio
async def test_mcp_dataset_catalog_is_machine_readable():
    server = create_mcp_server()
    async with Client(server, raise_exceptions=True) as client:
        tool_result = await client.call_tool("public_datasets", {})
        tool_ids = {item["id"] for item in tool_result.structured_content["datasets"]}
        assert tool_ids >= {"world-bank-wdi", "era5-land", "edgar", "egrid"}

        resource_result = await client.read_resource("exergy://datasets")
        resource_ids = {
            item["id"] for item in json.loads(resource_result.contents[0].text)
        }
        assert resource_ids == tool_ids


@pytest.mark.anyio
async def test_mcp_system_and_pack_tools_use_in_memory_contracts():
    server = create_mcp_server()
    async with Client(server, raise_exceptions=True) as client:
        system = await client.call_tool(
            "analyze_system",
            {
                "inputs": {
                    "name": "converter",
                    "components": [{"id": "c", "kind": "converter"}],
                    "flows": [
                        {
                            "id": "input",
                            "energy": 10,
                            "target": "c",
                            "exergy_factor": 1,
                        },
                        {
                            "id": "product",
                            "energy": 8,
                            "source": "c",
                            "exergy_factor": 1,
                        },
                        {
                            "id": "loss",
                            "energy": 2,
                            "exergy": 0,
                            "source": "c",
                            "role": "loss",
                        },
                    ],
                },
                "mode": "dry-run",
            },
        )
        assert system.structured_content["ok"] is True
        assert system.structured_content["result"]["exergy"][
            "exergetic_efficiency"
        ] == pytest.approx(0.8)

        pack = await client.call_tool("validate_technology_pack", {"pack": "buildings"})
        assert pack.structured_content["result"]["valid"] is True

        coverage = await client.call_tool(
            "technology_pack_default_coverage", {"pack": "emerging-energy"}
        )
        assert coverage.structured_content["automatic_estimate_count"] == 15

        performance = await client.call_tool(
            "estimate_technology_performance",
            {
                "inputs": {
                    "pack": "power",
                    "technology": "wind-turbine",
                    "input_energy": 100,
                }
            },
        )
        assert performance.structured_content["result"]["output_energy"][
            "value"
        ] == pytest.approx(37.5)

        intensity = await client.call_tool(
            "estimate_technology_intensity",
            {
                "inputs": {
                    "pack": "advanced-materials",
                    "technology": "electric-arc-furnace-melting",
                    "output_mass": 100,
                }
            },
        )
        assert intensity.structured_content["result"]["input_energy"][
            "value"
        ] == pytest.approx(48.45833333)

        resource = await client.read_resource("exergy://technology-packs")
        assert {item["id"] for item in json.loads(resource.contents[0].text)} >= {
            "buildings",
            "oil-gas",
            "power",
        }

        materials = await client.call_tool(
            "analyze_material_balance",
            {
                "inputs": {
                    "name": "split",
                    "components": [{"id": "s", "kind": "reactor-separator"}],
                    "streams": [
                        {"id": "feed", "mass": 10, "material": "x", "target": "s"},
                        {"id": "product", "mass": 10, "material": "x", "source": "s"},
                    ],
                }
            },
        )
        assert materials.structured_content["ok"] is True
        assert materials.structured_content["result"]["balance"]["residual_mass"] == 0
