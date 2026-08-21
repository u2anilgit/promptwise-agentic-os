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


def run_semgrep(config: dict[str, Any], cwd: Path | None = None) -> ToolRunResult:
    if shutil.which("semgrep") is None:
        return ToolRunResult(tool="semgrep", ran=False, passed=True, output="semgrep not installed on PATH, skipped")

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

    findings: list[VerifyFinding] = []
    try:
        data = json.loads(proc.stdout or "{}")
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
    except json.JSONDecodeError:
        return ToolRunResult(tool="semgrep", ran=True, passed=proc.returncode == 0, output=proc.stdout + proc.stderr)

    has_blocking = any(f.severity == "error" for f in findings)
    return ToolRunResult(tool="semgrep", ran=True, passed=not has_blocking, output=f"{len(findings)} finding(s)", findings=findings)


def run_gitleaks(config: dict[str, Any], cwd: Path | None = None) -> ToolRunResult:
    if shutil.which("gitleaks") is None:
        return ToolRunResult(tool="gitleaks", ran=False, passed=True, output="gitleaks not installed on PATH, skipped")

    try:
        proc = subprocess.run(
            ["gitleaks", "detect", "--source", str(cwd or "."), "--report-format", "json", "--report-path", "-", "--exit-code", "0"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return ToolRunResult(tool="gitleaks", ran=True, passed=False, output="gitleaks timed out")

    findings: list[VerifyFinding] = []
    try:
        data = json.loads(proc.stdout or "[]")
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
    except json.JSONDecodeError:
        return ToolRunResult(tool="gitleaks", ran=True, passed=proc.returncode == 0, output=proc.stdout + proc.stderr)

    # Any detected secret blocks — non-negotiable per CLAUDE.md's security posture.
    return ToolRunResult(tool="gitleaks", ran=True, passed=len(findings) == 0, output=f"{len(findings)} secret(s) detected", findings=findings)
