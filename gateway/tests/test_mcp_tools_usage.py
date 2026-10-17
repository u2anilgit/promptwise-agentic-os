import json

import pytest

from gateway.mcp_server import mcp_app


async def _call(name, args):
    blocks = await mcp_app.call_tool(name, args)
    return json.loads(blocks.content[0].text)


async def test_record_usage_persists_an_event_with_cost_fixed_from_the_catalog(operator):
    result = await _call("record_usage", {"tier": "cloud-premium", "tokens_in": 1000, "tokens_out": 1000, "agent": "claude", "task_ref": "T-1"})
    assert result["event"]["tier"] == "cloud-premium" and result["event"]["cost_usd"] > 0
    again = await _call("record_usage", {"tier": "local-small", "tokens_in": 5, "tokens_out": 5, "agent": "claude", "task_ref": "T-1"})
    assert again["event"]["cost_usd"] == 0


@pytest.mark.parametrize("args,needle", [
    ({"tier": "cloud-premium", "tokens_in": -1, "tokens_out": 0}, "tokens"),
    ({"tier": "cloud-premium", "tokens_in": 0, "tokens_out": 10**10}, "tokens"),
    ({"tier": "no-such-tier", "tokens_in": 1, "tokens_out": 1}, "unknown tier"),
    ({"tier": "local-small", "tokens_in": 1, "tokens_out": 1, "agent": "x" * 201}, "agent"),
])
async def test_bad_usage_is_an_error_dict_and_writes_nothing(operator, args, needle):
    result = await _call("record_usage", args)
    assert needle in result["error"]
    assert "event" not in result
