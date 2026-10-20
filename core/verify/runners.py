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
    except ValueError as exc:  # shlex: e.g. unclosed quote - a handled state, not an exception
        return ToolRunResult(tool=tool_name, ran=True, passed=False, output=f"{tool_name}: could not parse command - {exc}", error_kind="parse")
    except FileNotFoundError as exc:
        return ToolRunResult(tool=tool_name, ran=True, passed=False, output=f"{tool_name}: executable not found — {exc}", error_kind="not_found")
    except subprocess.TimeoutExpired:
        return ToolRunResult(tool=tool_name, ran=True, passed=False, output=f"{tool_name}: timed out after {timeout}s", error_kind="timeout")


def _governed(tool_name: str, command: str, config: dict[str, Any], cwd: Path | None, timeout: int = 300) -> ToolRunResult:
    """Run a configured verify command through the governed shell action: always audited; policy-gated
    when verify.enforce_command_policy is on (off by default: the default policy is deny-all and test
    runners are stack-specific, so their allow rules belong in operator policy or packs)."""
    from core.actions.shell import shell_exec  # deferred: core.actions.shell imports run_command from here

    verify = config.get("verify", {})
    return shell_exec(
        tool_name, command, cwd, config, actor="verify",
        enforce_policy=bool(verify.get("enforce_command_policy", False)),
        timeout=timeout, max_output_chars=verify.get("max_output_chars", 4000),
    )


def run_tests(config: dict[str, Any], cwd: Path | None = None) -> ToolRunResult:
    return _governed("tests", config.get("verify", {}).get("test_command", ""), config, cwd)


def run_mutation(config: dict[str, Any], cwd: Path | None = None) -> ToolRunResult:
    """Operator-supplied mutation-testing command. Exit 0 means the tool's own score threshold was met;
    core never parses scores. Blank = not configured (skipped, ran=False)."""
    verify = config.get("verify", {})
    return _governed("mutation", verify.get("mutation_command", ""), config, cwd, timeout=int(verify.get("mutation_timeout_seconds", 1800)))


def run_lint(config: dict[str, Any], cwd: Path | None = None) -> ToolRunResult:
    return _governed("lint", config.get("verify", {}).get("lint_command", ""), config, cwd)
