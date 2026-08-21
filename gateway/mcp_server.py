# gateway/mcp_server.py
"""In-process MCP server — exposes verify_output to any MCP-capable agent
(Claude Code, Cursor, OpenCode). Thin adapter, same pattern as the FastAPI
routes in app.py: no logic here beyond argument marshalling, everything
real lives in core.verify.gate.verify_output.

Note on the `mcp` SDK API used here: the installed `mcp` package (>=2.0)
renamed the high-level server class from `FastMCP` (import path
`mcp.server.fastmcp`) to `MCPServer` (import path `mcp.server.mcpserver`).
The rest of the surface used below — constructor taking a server name,
`.tool()` decorator, async `.list_tools()`, `.run()` — is unchanged from
the documented `FastMCP` pattern. Verified directly against the installed
package (`python -c "import mcp.server.mcpserver as m; print(dir(m))"`)
rather than assumed.
"""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from core.verify.gate import verify_output as _verify_output

mcp_app = MCPServer("promptwise-agentic-os")


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

    result = _verify_output(
        diff=diff,
        spec=spec or None,
        cwd=Path(cwd) if cwd else None,
        ledger_key=ledger_key or None,
    )
    return result.model_dump()


if __name__ == "__main__":
    mcp_app.run()
