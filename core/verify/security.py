# core/verify/security.py
"""Semgrep + Gitleaks security scanners. Both are external CLI tools, not
Python libraries called in-process — checked for on PATH first; a missing
binary WARNs and is skipped, it never fails the gate (same convention as
core/diagnostics/checks.py's services.* checks).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from core.verify.models import ToolRunResult, VerifyFinding
from core.verify.output import truncate_output as _truncate_output


def run_semgrep(config: dict[str, Any], cwd: Path | None = None) -> ToolRunResult:
    if shutil.which("semgrep") is None:
        return ToolRunResult(tool="semgrep", ran=False, passed=True, output="semgrep not installed on PATH, skipped")

    max_output_chars = config.get("verify", {}).get("max_output_chars", 4000)
    semgrep_config = config.get("verify", {}).get("semgrep_config", "auto")
    try:
        proc = subprocess.run(
            ["semgrep", "--config", semgrep_config, "--json", "--quiet"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return ToolRunResult(tool="semgrep", ran=True, passed=False, output="semgrep timed out")

    # semgrep's exit-code convention: 0 = no findings, 1 = findings present,
    # anything else is a real run failure (bad config, rule-load error, ...)
    # that must NOT be reported as "0 findings, clean".
    if proc.returncode not in (0, 1):
        return ToolRunResult(
            tool="semgrep",
            ran=True,
            passed=False,
            output=_truncate_output(
                f"semgrep exited with code {proc.returncode}\n{proc.stdout}{proc.stderr}", max_output_chars
            ),
        )

    findings: list[VerifyFinding] = []
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return ToolRunResult(
            tool="semgrep", ran=True, passed=False, output=_truncate_output(proc.stdout + proc.stderr, max_output_chars)
        )

    errors = data.get("errors") or []
    if errors:
        return ToolRunResult(
            tool="semgrep",
            ran=True,
            passed=False,
            output=_truncate_output(f"semgrep reported {len(errors)} error(s): {errors}", max_output_chars),
        )

    for result in data.get("results", []):
        severity_raw = result.get("extra", {}).get("severity", "WARNING").upper()
        severity = "error" if severity_raw == "ERROR" else ("info" if severity_raw == "INFO" else "warning")
        findings.append(
            VerifyFinding(
                tool="semgrep",
                severity=severity,
                message=result.get("extra", {}).get("message", "semgrep finding"),
                file=result.get("path"),
                line=result.get("start", {}).get("line"),
            )
        )

    has_blocking = any(f.severity == "error" for f in findings)
    return ToolRunResult(tool="semgrep", ran=True, passed=not has_blocking, output=f"{len(findings)} finding(s)", findings=findings)


def run_gitleaks(config: dict[str, Any], cwd: Path | None = None) -> ToolRunResult:
    if shutil.which("gitleaks") is None:
        return ToolRunResult(tool="gitleaks", ran=False, passed=True, output="gitleaks not installed on PATH, skipped")

    max_output_chars = config.get("verify", {}).get("max_output_chars", 4000)
    try:
        proc = subprocess.run(
            ["gitleaks", "detect", "--source", str(cwd or "."), "--report-format", "json", "--report-path", "-"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return ToolRunResult(tool="gitleaks", ran=True, passed=False, output="gitleaks timed out")

    # gitleaks' real exit-code convention: 0 = no leaks, 1 = leaks found. Any
    # other code means the scan itself didn't run correctly — that must
    # never be reported as "0 secrets detected" (fail-open), regardless of
    # what (if anything) happened to be on stdout.
    if proc.returncode not in (0, 1):
        return ToolRunResult(
            tool="gitleaks",
            ran=True,
            passed=False,
            output=_truncate_output(
                f"gitleaks exited with code {proc.returncode}\n{proc.stdout}{proc.stderr}", max_output_chars
            ),
        )

    findings: list[VerifyFinding] = []
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return ToolRunResult(
            tool="gitleaks", ran=True, passed=False, output=_truncate_output(proc.stdout + proc.stderr, max_output_chars)
        )

    for leak in data:
        findings.append(
            VerifyFinding(
                tool="gitleaks",
                severity="error",
                message=f"secret detected: {leak.get('RuleID', 'unknown rule')}",
                file=leak.get("File"),
                line=leak.get("StartLine"),
            )
        )

    # Any detected secret blocks — non-negotiable per CLAUDE.md's security
    # posture. `passed` also depends on the exit code above, never solely
    # on "did JSON parse to an empty list".
    passed = proc.returncode == 0 and len(findings) == 0
    return ToolRunResult(tool="gitleaks", ran=True, passed=passed, output=f"{len(findings)} secret(s) detected", findings=findings)
