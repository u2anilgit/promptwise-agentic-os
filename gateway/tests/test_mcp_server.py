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


async def test_mcp_call_tool_verify_output_runs_a_real_check(operator):
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
            "cwd": str(operator),
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


async def test_verify_output_tool_is_registered_in_the_tool_registry():
    """The tool registry (core/policy/tool_registry.py) and the MCP server's
    actually-registered tools must agree — verify_output must be in both."""
    import yaml
    from pathlib import Path

    registry_path = Path("tool_registry.yaml")
    with registry_path.open("r", encoding="utf-8") as f:
        registry = yaml.safe_load(f)
    assert "verify_output" in registry["tools"]
    assert registry["tools"]["verify_output"]["enabled"] is True


async def test_live_tool_spec_matches_what_clients_are_served():
    """Pins are computed from live_tool_spec(); it must equal the
    description/schema list_tools serves, or pinning guards the wrong text."""
    from gateway.mcp_server import live_tool_spec

    served = {t.name: t for t in await mcp_app.list_tools()}["verify_output"]
    description, schema = live_tool_spec("verify_output")
    assert description == served.description
    assert schema == served.inputSchema


async def test_verify_output_is_rejected_when_its_pinned_description_changed(tmp_path, monkeypatch):
    from gateway import mcp_server

    registry = tmp_path / "tool_registry.yaml"
    registry.write_text("tools:\n  verify_output:\n    version: '0.1.0'\n    enabled: true\n    description_sha256: 'deadbeef'\n", encoding="utf-8")
    operator_file = tmp_path / "operator.yaml"
    operator_file.write_text(
        f"policy:\n  tool_registry_path: {registry.as_posix()}\naudit:\n  log_path: {(tmp_path / 'a.jsonl').as_posix()}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PROMPTWISE_OPERATOR_CONFIG", str(operator_file))
    monkeypatch.chdir(tmp_path)

    content = await mcp_server.mcp_app.call_tool("verify_output", {"diff": "x", "cwd": str(tmp_path)})
    assert "changed since it was pinned" in json.loads(content[0].text)["error"]


async def test_verify_output_denies_a_cwd_outside_the_allowed_roots(operator, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    content = await mcp_app.call_tool("verify_output", {"diff": "x", "cwd": str(elsewhere)})
    assert "outside allowed roots" in json.loads(content[0].text)["error"]
