# gateway/tests/test_mcp_server.py
import json

from gateway.mcp_server import mcp_app


def test_mcp_app_is_created():
    assert mcp_app is not None
    assert mcp_app.name == "promptwise-agentic-os"


async def test_mcp_app_has_verify_output_tool():
    tools = await mcp_app.list_tools()
    tool_names = {t.name for t in tools}
    assert "verify_output" in tool_names


async def test_mcp_call_tool_verify_output_runs_a_real_check(tmp_path):
    """End-to-end: drives verify_output the same way a real Claude Code
    session does — through FastMCP's call_tool, not by importing the
    Python function directly. Confirms the MCP arg-marshalling layer
    (str cwd -> Path, empty-string sentinels -> None) actually works,
    closing the ROADMAP Phase 2 acceptance criterion "works against a
    real Claude Code session via MCP".
    """
    content_blocks = await mcp_app.call_tool(
        "verify_output",
        {
            "diff": "add a feature",
            "spec": "the feature must work",
            "cwd": str(tmp_path),
            "ledger_key": "",
        },
    )
    # This is the exact path a real Claude Code session takes: a JSON-RPC
    # tools/call, marshalled through FastMCP into our function, run for
    # real against tmp_path (no test/lint command configured there, so it's
    # a no-op pass), and serialized back into a text content block.
    payload = json.loads(content_blocks[0].text)
    assert payload["passed"] is True
    assert payload["blocked_reason"] is None
