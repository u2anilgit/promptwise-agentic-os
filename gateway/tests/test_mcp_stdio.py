"""Real-client tests: launch `python -m gateway.mcp_server` exactly as .mcp.json does
and speak MCP over stdio — both the legacy initialize flow and the stateless
(2026-07-28) server/discover flow."""
import json
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import core
from gateway.mcp_server import live_tool_specs


def _params(cwd):
    return StdioServerParameters(command=sys.executable, args=["-m", "gateway.mcp_server"], cwd=str(cwd), env={**os.environ})


async def test_stateless_discover_advertises_the_2026_07_28_protocol_and_our_identity(operator):
    async with stdio_client(_params(operator)) as (read, write):
        async with ClientSession(read, write) as session:
            found = await session.discover()
            assert "2026-07-28" in found.supported_versions
            assert found.result_type == "complete"
            info = found.meta["io.modelcontextprotocol/serverInfo"]
            assert info["name"] == "promptwise-agentic-os" and info["version"] == core.__version__
            assert found.instructions and "untrusted" in found.instructions.lower()
            # Dynamic capabilities we do not implement must not be advertised as active.
            caps = found.capabilities
            assert caps.tools is not None and not caps.tools.list_changed
            assert caps.resources is None or not (caps.resources.subscribe or caps.resources.list_changed)
            assert caps.prompts is None or not caps.prompts.list_changed


async def test_stateless_client_can_list_and_call_governed_tools_without_initialize(operator):
    async with stdio_client(_params(operator)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.discover()
            tools = await session.list_tools()
            assert {t.name for t in tools.tools} == set(live_tool_specs())
            result = await session.call_tool("converge_feature", {"spec_id": "ghost"})
            assert "unknown spec" in json.loads(result.content[0].text)["error"]


async def test_legacy_initialize_flow_still_works(operator):
    async with stdio_client(_params(operator)) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.server_info.name == "promptwise-agentic-os"
            assert init.protocol_version in {"2025-11-25", "2026-07-28"}
            tools = await session.list_tools()
            assert len(tools.tools) == len(live_tool_specs())


async def test_an_out_of_root_path_is_denied_over_the_real_transport(operator, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    async with stdio_client(_params(operator)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.discover()
            result = await session.call_tool("query_code_index", {"symbol": "x", "root": str(elsewhere)})
            assert "outside allowed roots" in json.loads(result.content[0].text)["error"]
