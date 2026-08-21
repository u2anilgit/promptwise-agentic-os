# gateway/tests/test_mcp_server.py
from gateway.mcp_server import mcp_app


def test_mcp_app_is_created():
    assert mcp_app is not None
    assert mcp_app.name == "promptwise-agentic-os"


async def test_mcp_app_has_verify_output_tool():
    tools = await mcp_app.list_tools()
    tool_names = {t.name for t in tools}
    assert "verify_output" in tool_names
