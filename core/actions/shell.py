# core/actions/shell.py
"""shell_exec — the governed shell action (docs/superpowers/plans/2026-10-20-governed-shell-exec.md).

Same Action-layer contract as fs_write: policy-gated when the caller enforces policy, audited before the
process starts (if that record cannot be written, nothing runs) and again with the outcome. The audit keeps
the (truncated) command, the policy action, timing and a sha256 of the output — never the output itself,
which may hold secrets a test printed.
"""
from __future__ import annotations

import hashlib
import shlex
import time
from pathlib import Path
from typing import Any

from core.audit.log import record_audit
from core.policy.engine import check_policy
from core.verify.models import ToolRunResult
from core.verify.runners import run_command

MAX_AUDITED_COMMAND_CHARS = 500
# error_kind values meaning governance stopped the command (it did not run). Callers must treat them as a
# blocking failure, never as "not configured".
GOVERNANCE_ERRORS = frozenset({"policy_denied", "audit_unavailable"})


def command_action(command: str, base: Path) -> str:
    """Policy action for a command. A bare program name maps to shell:run:<name>; anything containing a
    path separator maps to its resolved absolute path, so a file merely *named* python cannot ride on an
    allow rule for the real interpreter. Allowing an interpreter still allows arbitrary code run through it."""
    try:
        argv0 = shlex.split(command)[0]
    except (ValueError, IndexError):
        return "shell:run:"
    if "/" in argv0 or chr(92) in argv0:
        return "shell:run:" + (base / argv0).resolve().as_posix()
    name = Path(argv0).name
    return f"shell:run:{name[:-4] if name.lower().endswith('.exe') else name}"


def shell_exec(
    tool_name: str,
    command: str,
    cwd: Path | None,
    config: dict[str, Any],
    actor: str,
    enforce_policy: bool,
    timeout: int = 300,
    max_output_chars: int = 4000,
) -> ToolRunResult:
    if not command.strip():
        return run_command(tool_name, command, cwd)  # "not configured": skipped, nothing to govern

    base = Path(cwd) if cwd is not None else Path.cwd()
    action = command_action(command, base)
    detail = {"tool": tool_name, "command": command[:MAX_AUDITED_COMMAND_CHARS], "cwd": str(base)}

    if enforce_policy:
        decision = check_policy(action, config)
        if not decision.allowed:
            try:
                record_audit(config, actor=actor, action="shell_exec", target=action, result="deny", detail={**detail, "reason": decision.reason})
            except Exception:  # noqa: BLE001 - the denial stands either way; report it, do not crash the caller
                pass
            return ToolRunResult(tool=tool_name, ran=False, passed=False, output=f"{tool_name}: denied by policy ({action})", error_kind="policy_denied")

    try:
        record_audit(config, actor=actor, action="shell_exec", target=action, result="allow", detail={**detail, "phase": "start"})
    except Exception:  # noqa: BLE001 - an action that cannot be audited does not run
        return ToolRunResult(tool=tool_name, ran=False, passed=False, output=f"{tool_name}: not run, the audit log could not be written", error_kind="audit_unavailable")

    started = time.monotonic()
    result = run_command(tool_name, command, cwd, timeout=timeout, max_output_chars=max_output_chars)
    try:
        record_audit(config, actor=actor, action="shell_exec", target=action, result="allow", detail={  # a failing test is an allowed run, not an error
            **detail, "phase": "end", "passed": result.passed, "error_kind": result.error_kind,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "output_sha256": hashlib.sha256(result.output.encode("utf-8")).hexdigest(),
        })
    except Exception:  # noqa: BLE001 - the run already happened; its start record exists
        pass
    return result
