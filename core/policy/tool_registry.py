"""MCP tool allowlist with a kill switch — docs/ARCHITECTURE.md §2's tool
registry (closes the P2/P7 gap in the research doc's language). An
unregistered or explicitly-disabled tool is rejected before it ever
reaches core logic — this is the enforcement boundary gateway/CLAUDE.md
describes ("MCP tool registry enforcement happens here at the boundary").
Version-pinning by hash is a Phase 8 (pack ecosystem) concern; this phase
ships name+version+enabled, the minimum needed for a real kill switch.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from core.config.resolve import resolve_path


class ToolRegistryEntry(BaseModel):
    version: str
    enabled: bool


def _registry_path(config: dict[str, Any]) -> Path:
    return resolve_path(config, "policy.tool_registry_path", "tool_registry.yaml")


def load_tool_registry(config: dict[str, Any]) -> dict[str, ToolRegistryEntry]:
    path = _registry_path(config)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    tools = data.get("tools", {})
    return {name: ToolRegistryEntry(**fields) for name, fields in tools.items()}


def is_tool_allowed(config: dict[str, Any], name: str) -> bool:
    registry = load_tool_registry(config)
    entry = registry.get(name)
    if entry is None:
        return False
    return entry.enabled
