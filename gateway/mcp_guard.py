# gateway/mcp_guard.py
"""The governed boundary every MCP tool passes through (gateway/CLAUDE.md:
"registry enforcement happens here at the boundary").

Order: tool registry + description pin -> path confinement -> effective
config -> pre-call audit -> verb -> post-call audit -> errors returned as
{"error": ...}, never raised. No verb runs if its pre-call audit record
cannot be written.

Threat model: the MCP caller is an AI agent that is only partly trusted. It
chooses every tool argument and can write files inside the project it points
at, including `.promptwise/config.yaml`. So a call runs on the *operator's*
config, and a project may contribute exactly two things: its
`verify.test_command` / `verify.lint_command`, and only when the operator has
pre-approved that exact string in `gateway.allowed_verify_commands`. Every
other key (state paths, endpoints, policy, limits, timeouts) is the
operator's, and governance state files (audit, ledger, JIT grants, undo
buffer, spec database) are pinned to the gateway's own directory. Domain-
agnostic: no verb logic lives here.
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from core.audit.log import record_audit
from core.config.resolve import resolve_config, resolve_config_auto, resolve_path
from core.policy.tool_pins import guard_tool

# The only project-supplied values an MCP call will honour (see module docstring).
PROJECT_VERIFY_KEYS = ("test_command", "lint_command")

# Governance state that must live with the gateway, never under a project:
# (dotted config key, default relative path).
OPERATOR_STATE_PATHS = (
    ("database.path", ".promptwise/agentic.sqlite3"),
    ("verify.failure_ledger_path", ".promptwise/failure_ledger.json"),
    ("policy.jit_grants_path", ".promptwise/jit_grants.json"),
    ("actions.undo_buffer_path", ".promptwise/undo_buffer.json"),
)

OPERATOR_CONFIG_ENV = "PROMPTWISE_OPERATOR_CONFIG"


def operator_config(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The gateway operator's governance config: system defaults + an
    optional operator-owned file (path in $PROMPTWISE_OPERATOR_CONFIG) +
    the process environment. Deliberately NOT the working directory's
    org/project/local layers — the gateway's cwd may be the very project
    an agent is editing, so those files are agent-writable. For a hardened
    deployment keep the operator file, policies dir, tool registry, audit
    log and database outside any path the agent can write.
    """
    env = env if env is not None else os.environ
    path = env.get(OPERATOR_CONFIG_ENV)
    return resolve_config(org_path=Path(path) if path else None, project_path=None, local_path=None, env=env)


@dataclass
class GovernedCall:
    config: dict[str, Any]  # effective config (operator config + approved project verify commands)
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


def _set(cfg: dict[str, Any], dotted: str, value: Any) -> None:
    keys = dotted.split(".")
    cursor = cfg
    for key in keys[:-1]:
        nxt = cursor.get(key)
        if not isinstance(nxt, dict):
            nxt = cursor[key] = {}
        cursor = nxt
    cursor[keys[-1]] = value


def _pin_state_paths(cfg: dict[str, Any], operator_config: dict[str, Any]) -> dict[str, Any]:
    gateway_root = Path.cwd()
    for dotted, default in OPERATOR_STATE_PATHS:
        _set(cfg, dotted, str(resolve_path(operator_config, dotted, default, root=gateway_root)))
    return cfg


def pinned_config(operator_config: dict[str, Any]) -> dict[str, Any]:
    """Operator config with governance state pinned to the gateway directory and NO project layer at
    all — for read-only consumers (dashboard API) that must not be affected by agent-writable files."""
    return _pin_state_paths(copy.deepcopy(operator_config), operator_config)


def effective_config(operator_config: dict[str, Any], root: Path) -> dict[str, Any]:
    cfg = copy.deepcopy(operator_config)

    project = resolve_config_auto(root=root)
    project_verify = project.get("verify") if isinstance(project.get("verify"), dict) else {}
    allowed = operator_config.get("gateway", {}).get("allowed_verify_commands") or []
    for key in PROJECT_VERIFY_KEYS:
        value = project_verify.get(key)
        if isinstance(value, str) and value and value in allowed:
            _set(cfg, f"verify.{key}", value)

    return _pin_state_paths(cfg, operator_config)


def _safe_audit(op: dict[str, Any], **fields: Any) -> bool:
    try:
        record_audit(op, actor="mcp", **fields)
        return True
    except Exception:  # noqa: BLE001 - callers decide what an unwritable audit log means
        return False


def run_governed(
    name: str,
    paths: dict[str, str],
    body: Callable[[GovernedCall], dict[str, Any]],
    *,
    spec_lookup: Callable[[str], tuple[str, dict[str, Any]]],
    operator_config_override: dict[str, Any] | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    op = operator_config_override if operator_config_override is not None else operator_config()
    extra = dict(detail or {})

    description, schema = spec_lookup(name)
    decision = guard_tool(op, name, description, schema)
    if not decision.allowed:
        _safe_audit(op, action="mcp_tool_denied", target=name, result="deny", detail={"status": decision.status, **extra})
        return {"error": f"{decision.reason} (tool_registry.yaml) - rejected at the boundary"}

    confined: dict[str, Path] = {}
    for param, value in paths.items():
        resolved = confine(op, value)
        if resolved is None:
            _safe_audit(op, action="mcp_root_denied", target=name, result="deny", detail={"param": param, "value": value, **extra})
            return {"error": f"path '{param}' is outside allowed roots"}
        confined[param] = resolved

    root = confined.get("root") or allowed_roots(op)[0]
    audit_detail = {**extra, **{f"path_{k}": str(v) for k, v in confined.items()}}

    # Fail closed: no tool runs without a written pre-call record.
    if not _safe_audit(op, action=name, target=str(root), result="allow", detail={"phase": "start", **audit_detail}):
        return {"error": "audit log unavailable - refusing to run the tool"}

    try:
        result = body(GovernedCall(config=effective_config(op, root), root=root, paths=confined))
        outcome, outcome_detail = "allow", {"phase": "done", **audit_detail}
    except ValueError as exc:
        result, outcome, outcome_detail = {"error": str(exc)}, "error", {"phase": "done", "error": str(exc), **audit_detail}
    except Exception as exc:  # noqa: BLE001 - never leak internals or crash the transport
        result = {"error": f"internal error: {type(exc).__name__}"}
        outcome, outcome_detail = "error", {"phase": "done", "error_type": type(exc).__name__, **audit_detail}

    if not _safe_audit(op, action=name, target=str(root), result=outcome, detail=outcome_detail):  # type: ignore[arg-type]
        result = {**result, "audit_warning": "the tool ran but its completion record could not be written"}
    return result
