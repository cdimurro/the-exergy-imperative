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
