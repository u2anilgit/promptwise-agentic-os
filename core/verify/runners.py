"""Test and lint runners — subprocess wrappers over config-declared
commands. Never hardcodes a language or tool (CLAUDE.md goal 1): the
command string is entirely config-driven, empty means "not configured for
this project" and is a no-op pass, not a failure.
"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

from core.verify.models import ToolRunResult
from core.verify.output import truncate_output


def run_command(
    tool_name: str, command: str, cwd: Path | None, timeout: int = 300, max_output_chars: int = 4000
) -> ToolRunResult:
    if not command.strip():
        return ToolRunResult(tool=tool_name, ran=False, passed=True, output=f"{tool_name}: no command configured, skipped")

    try:
        proc = subprocess.run(
            shlex.split(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        return ToolRunResult(
            tool=tool_name, ran=True, passed=proc.returncode == 0, output=truncate_output(output.strip(), max_output_chars)
        )
    except FileNotFoundError as exc:
        return ToolRunResult(tool=tool_name, ran=True, passed=False, output=f"{tool_name}: executable not found — {exc}")
    except subprocess.TimeoutExpired:
        return ToolRunResult(tool=tool_name, ran=True, passed=False, output=f"{tool_name}: timed out after {timeout}s")


def run_tests(config: dict[str, Any], cwd: Path | None = None) -> ToolRunResult:
    command = config.get("verify", {}).get("test_command", "")
    max_output_chars = config.get("verify", {}).get("max_output_chars", 4000)
    return run_command("tests", command, cwd, max_output_chars=max_output_chars)


def run_lint(config: dict[str, Any], cwd: Path | None = None) -> ToolRunResult:
    command = config.get("verify", {}).get("lint_command", "")
    max_output_chars = config.get("verify", {}).get("max_output_chars", 4000)
    return run_command("lint", command, cwd, max_output_chars=max_output_chars)
