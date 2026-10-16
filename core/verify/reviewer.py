# core/verify/reviewer.py
"""Independent reviewer hook (docs/superpowers/specs/2026-10-17-independent-verification-design.md, Ruling 3).

The operator configures `verify.reviewer_command`: any program that reads one JSON document on stdin
and prints `{"approved": bool, "reasons": [str]}` on stdout. It can call a different model, a different
agent, or put a human in the loop — core calls no LLM. Everything that is not a clean, explicit
approval is a rejection (fail closed): non-zero exit, timeout, missing program, unparsable command,
malformed or wrongly-typed JSON.
"""
from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel

MAX_REASONS = 10
MAX_REASON_CHARS = 300
MAX_STDOUT_CHARS = 200_000


class ReviewerVerdict(BaseModel):
    ran: bool
    approved: bool = False
    reasons: list[str] = []
    error: str | None = None


def _bounded(reasons: Any) -> list[str]:
    if not isinstance(reasons, list):
        return []
    return [str(r)[:MAX_REASON_CHARS] for r in reasons[:MAX_REASONS]]


def run_reviewer(config: dict[str, Any], cwd: Path | None, payload: dict[str, Any]) -> ReviewerVerdict:
    verify = config.get("verify", {})
    command = (verify.get("reviewer_command") or "").strip()
    if not command:
        return ReviewerVerdict(ran=False)
    timeout = int(verify.get("reviewer_timeout_seconds", 300))

    try:
        proc = subprocess.run(
            shlex.split(command), input=json.dumps(payload), cwd=cwd,
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ReviewerVerdict(ran=True, error=f"reviewer timed out after {timeout}s")
    except (FileNotFoundError, PermissionError) as exc:
        return ReviewerVerdict(ran=True, error=f"reviewer could not start: {exc}")
    except ValueError as exc:  # shlex: unparsable command
        return ReviewerVerdict(ran=True, error=f"reviewer command could not be parsed: {exc}")

    if proc.returncode != 0:
        return ReviewerVerdict(ran=True, error=f"reviewer exited with status {proc.returncode}")
    try:
        verdict = json.loads((proc.stdout or "")[:MAX_STDOUT_CHARS].strip())
    except ValueError:
        return ReviewerVerdict(ran=True, error="reviewer printed malformed JSON")
    if not isinstance(verdict, dict) or not isinstance(verdict.get("approved"), bool):
        return ReviewerVerdict(ran=True, error="reviewer verdict must be an object with a boolean 'approved'")
    return ReviewerVerdict(ran=True, approved=verdict["approved"], reasons=_bounded(verdict.get("reasons")))
