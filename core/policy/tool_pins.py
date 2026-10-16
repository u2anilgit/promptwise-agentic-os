# core/policy/tool_pins.py
"""Tool-description pinning — rug-pull / tool-poisoning defence
(docs/research/2026-10-16-agent-landscape-gap-analysis.md pain point 3).

A tool's description and input schema are text the *model* reads and
obeys, so a silent change to either is an instruction-injection vector
even when the tool name and version are unchanged. The registry may pin
`description_sha256` per tool; guard_tool refuses (and audits) any tool
whose live description/schema no longer hashes to its pin. Applies to our
own MCP server today and to any outbound MCP client later.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel

from core.audit.log import record_audit
from core.policy.tool_registry import load_tool_registry

PinStatus = Literal["ok", "mismatch", "unpinned", "unregistered", "disabled"]


class GuardDecision(BaseModel):
    allowed: bool
    status: PinStatus
    reason: str = ""


def tool_description_hash(description: str, input_schema: dict[str, Any]) -> str:
    canonical = json.dumps({"description": description, "input_schema": input_schema}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def guard_tool(config: dict[str, Any], name: str, description: str, input_schema: dict[str, Any]) -> GuardDecision:
    entry = load_tool_registry(config).get(name)
    if entry is None:
        return GuardDecision(allowed=False, status="unregistered", reason=f"tool '{name}' is not in the tool registry")
    if not entry.enabled:
        return GuardDecision(allowed=False, status="disabled", reason=f"tool '{name}' is disabled in the tool registry")

    if entry.description_sha256 is None:
        if config.get("security", {}).get("require_tool_pins", False):
            return GuardDecision(allowed=False, status="unpinned", reason=f"tool '{name}' has no description_sha256 pin and security.require_tool_pins is set")
        return GuardDecision(allowed=True, status="unpinned", reason="no pin recorded for this tool")

    live = tool_description_hash(description, input_schema)
    if live != entry.description_sha256:
        record_audit(
            config, actor="tool_pins", action="tool_pin_mismatch", target=name, result="deny",
            detail={"pinned": entry.description_sha256, "live": live},
        )
        return GuardDecision(
            allowed=False, status="mismatch",
            reason=f"tool '{name}' description/schema changed since it was pinned — re-review and re-pin (`promptwise pin-tools`)",
        )
    return GuardDecision(allowed=True, status="ok")


def write_pins(config: dict[str, Any], live_tools: dict[str, tuple[str, dict[str, Any]]]) -> list[str]:
    """Record the current live description/schema hash of each registered
    tool in the registry file (leading `#` comment header preserved).
    Returns the names pinned. Tools not in the registry are ignored —
    pinning never registers or enables anything.
    """
    import yaml

    from core.policy.tool_registry import _registry_path

    path = _registry_path(config)
    text = path.read_text(encoding="utf-8")
    header = []
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            header.append(line)
        else:
            break
    data = yaml.safe_load(text) or {}
    tools = data.get("tools", {})
    pinned: list[str] = []
    for name, (description, schema) in live_tools.items():
        if name in tools:
            tools[name]["description_sha256"] = tool_description_hash(description, schema)
            pinned.append(name)
    path.write_text("\n".join(header) + "\n" + yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return pinned
