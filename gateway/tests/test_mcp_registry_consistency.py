"""The committed tool_registry.yaml must match the live MCP tools exactly.
If this fails after editing a tool's docstring/signature: run `promptwise pin-tools`."""
from pathlib import Path

import yaml

from core.policy.tool_pins import tool_description_hash
from gateway.mcp_server import live_tool_specs


def _registry():
    root = Path(__file__).resolve().parents[2]
    return yaml.safe_load((root / "tool_registry.yaml").read_text(encoding="utf-8"))["tools"]


def test_every_live_tool_is_registered_enabled_and_pinned_to_its_current_text():
    registry = _registry()
    for name, (description, schema) in live_tool_specs().items():
        assert name in registry, f"{name} is not in tool_registry.yaml"
        assert registry[name]["enabled"] is True, name
        assert registry[name].get("description_sha256") == tool_description_hash(description, schema), (
            f"{name}: pin is stale - run `python -m scripts.promptwise pin-tools`"
        )


def test_no_registry_entry_refers_to_a_tool_that_does_not_exist():
    assert set(_registry()) <= set(live_tool_specs())
