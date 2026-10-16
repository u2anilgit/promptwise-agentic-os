# gateway/mcp_guard.py
"""The governed boundary every MCP tool passes through (gateway/CLAUDE.md:
"registry enforcement happens here at the boundary").

Order: tool registry + description pin -> path confinement -> effective
config -> audit -> verb -> errors returned as {"error": ...}, never raised.

Security model: the *agent* controls tool arguments and can write files
in the project it points at, including a `.promptwise/config.yaml`. So the
call runs with the project's config, except the governance keys below are
forced from the *operator's* config (the gateway process's own working
directory) — a project cannot loosen its own policy, audit or verification
requirements. Domain-agnostic: no verb logic lives here.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core.audit.log import record_audit
from core.config.resolve import resolve_config_auto
from core.policy.tool_pins import guard_tool

# Dotted config keys the project may never override via MCP.
TRUSTED_KEYS = (
    "audit",
    "policy",
    "security",
    "gateway",
    "paths.policies_dir",
    "spec.enforce_command_policy",
    "spec.allow_ungrounded",
    "spec.allow_fileless_checks",
    "spec.trivial_max_requirements",
)


@dataclass
class GovernedCall:
    config: dict[str, Any]  # effective config (project config + operator-forced keys)
    root: Path  # confined project root
    paths: dict[str, Path]  # every confined path argument, by parameter name


def allowed_roots(operator_config: dict[str, Any]) -> list[Path]:
    configured = operator_config.get("gateway", {}).get("allowed_roots") or []
    roots = [Path(r).resolve() for r in configured]
    return roots or [Path.cwd().resolve()]


def confine(operator_config: dict[str, Any], value: str) -> Path | None:
    roots = allowed_roots(operator_config)
    if not value:
        return roots[0]
    candidate = Path(value).resolve()  # resolves symlinks and '..'
    for root in roots:
        if candidate == root or root in candidate.parents:
            return candidate
    return None


def _get(cfg: dict[str, Any], dotted: str) -> tuple[bool, Any]:
    cursor: Any = cfg
    for key in dotted.split("."):
        if not isinstance(cursor, dict) or key not in cursor:
            return False, None
        cursor = cursor[key]
    return True, cursor


def _set(cfg: dict[str, Any], dotted: str, value: Any) -> None:
    keys = dotted.split(".")
    cursor = cfg
    for key in keys[:-1]:
        nxt = cursor.get(key)
        if not isinstance(nxt, dict):
            nxt = cursor[key] = {}
        cursor = nxt
    cursor[keys[-1]] = value


def _drop(cfg: dict[str, Any], dotted: str) -> None:
    keys = dotted.split(".")
    cursor: Any = cfg
    for key in keys[:-1]:
        cursor = cursor.get(key) if isinstance(cursor, dict) else None
        if cursor is None:
            return
    if isinstance(cursor, dict):
        cursor.pop(keys[-1], None)


def effective_config(operator_config: dict[str, Any], root: Path) -> dict[str, Any]:
    cfg = resolve_config_auto(root=root)
    for dotted in TRUSTED_KEYS:
        present, value = _get(operator_config, dotted)
        if present:
            _set(cfg, dotted, copy.deepcopy(value))
        else:
            _drop(cfg, dotted)  # operator did not set it: the project must not either
    return cfg


def run_governed(
    name: str,
    paths: dict[str, str],
    body: Callable[[GovernedCall], dict[str, Any]],
    *,
    spec_lookup: Callable[[str], tuple[str, dict[str, Any]]],
    operator_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    op = operator_config if operator_config is not None else resolve_config_auto()

    description, schema = spec_lookup(name)
    decision = guard_tool(op, name, description, schema)
    if not decision.allowed:
        return {"error": f"{decision.reason} (tool_registry.yaml) - rejected at the boundary"}

    confined: dict[str, Path] = {}
    for param, value in paths.items():
        resolved = confine(op, value)
        if resolved is None:
            record_audit(op, actor="mcp", action="mcp_root_denied", target=name, result="deny", detail={"param": param, "value": value})
            return {"error": f"path '{param}' is outside allowed roots"}
        confined[param] = resolved

    root = confined.get("root") or allowed_roots(op)[0]
    try:
        call = GovernedCall(config=effective_config(op, root), root=root, paths=confined)
        result = body(call)
    except ValueError as exc:
        record_audit(op, actor="mcp", action=name, target=str(root), result="error", detail={"error": str(exc)})
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - never leak internals or crash the transport
        record_audit(op, actor="mcp", action=name, target=str(root), result="error", detail={"error_type": type(exc).__name__})
        return {"error": f"internal error: {type(exc).__name__}"}

    record_audit(op, actor="mcp", action=name, target=str(root), result="allow", detail={})
    return result
