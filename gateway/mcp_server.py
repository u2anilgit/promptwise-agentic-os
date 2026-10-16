# gateway/mcp_server.py
"""In-process MCP server — exposes verify_output to any MCP-capable agent
(Claude Code, Cursor, OpenCode). Thin adapter, same pattern as the FastAPI
routes in app.py: no logic here beyond argument marshalling, everything
real lives in core.verify.gate.verify_output.

Uses the official `mcp` Python SDK's high-level `FastMCP` server class at
`mcp.server.fastmcp`, matching the standard documented pattern — verified
directly against the package actually installed in this project's
environment (`python`, i.e. `pip show mcp` → 1.27.1, the interpreter this
repo's tests run under) before writing this file.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from core.verify.gate import verify_output as _verify_output

mcp_app = FastMCP("promptwise-agentic-os")


def live_tool_spec(name: str) -> tuple[str, dict]:
    """The description + input schema exactly as served to MCP clients
    (what the model reads) — the input to tool-description pinning."""
    tool = mcp_app._tool_manager.get_tool(name)  # noqa: SLF001 — SDK exposes no sync public accessor
    return tool.description, tool.parameters


def live_tool_specs() -> dict[str, tuple[str, dict]]:
    return {t.name: (t.description, t.parameters) for t in mcp_app._tool_manager.list_tools()}  # noqa: SLF001


@mcp_app.tool()
def verify_output(diff: str, spec: str = "", cwd: str = "", ledger_key: str = "") -> dict:
    """Run the verification gate (tests, lint, Semgrep, Gitleaks) against
    the current working tree and report whether the change is safe to
    consider done. Call this after making any code change, before
    declaring the task complete.

    Args:
        diff: A description or unified diff of what changed (for logging
            and the failure-retry ledger — this function does not apply
            the diff itself, it checks the working tree as it stands).
        spec: The requirement/spec this change is meant to satisfy.
        cwd: Working directory to run checks in. Defaults to the server's
            own cwd if empty.
        ledger_key: A stable identifier for this task, used to detect
            repeated identical failures across retries. Leave empty to
            skip retry-loop tracking.
    """
    from pathlib import Path

    from core.config.resolve import resolve_config_auto
    from core.policy.tool_pins import guard_tool

    config = resolve_config_auto()
    description, schema = live_tool_spec("verify_output")
    decision = guard_tool(config, "verify_output", description, schema)
    if not decision.allowed:
        return {"error": f"{decision.reason} (tool_registry.yaml) — rejected at the boundary"}

    result = _verify_output(
        diff=diff,
        spec=spec or None,
        cwd=Path(cwd) if cwd else None,
        ledger_key=ledger_key or None,
    )
    return result.model_dump()


if __name__ == "__main__":
    mcp_app.run()
