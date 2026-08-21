# Phase 2 — Verification Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `verify_output(diff, spec, ...)` — the mandatory verification gate (`docs/ROADMAP.md` Phase 2 row, `CLAUDE.md` goal 3): runs the project's own tests, lint, Semgrep, and Gitleaks against a working tree; blocks until they pass; tracks a failure ledger that breaks an identical-failure retry loop after N attempts; exposed to any MCP-capable agent (Claude Code, Cursor, OpenCode) via an in-process MCP server, and to HTTP callers via a gateway route.

**Architecture:** `core/verify/` is a new self-contained package: `models.py` (typed shapes), `ledger.py` (the failure ledger — a config-resolved JSON file, no database yet), `runners.py` (test + lint subprocess runners), `security.py` (Semgrep + Gitleaks subprocess runners), `gate.py` (`verify_output` — the orchestrator). Every runner is **config-driven, never hardcoded to a language or tool** (`CLAUDE.md` goal 1): `verify.test_command`/`verify.lint_command` are empty by default and a project's own `promptwise.config.yaml` supplies them (this plan adds one for this repo itself — `pytest -q` — so the gate dogfoods on its own codebase from day one). Semgrep/Gitleaks are checked for on `PATH` before running; a missing binary WARNs and is skipped, never FAILs or crashes the gate (same pattern Phase 0's doctor checks established). The MCP server (`gateway/mcp_server.py`) is a thin adapter, same pattern as the FastAPI routes: it decorates the pure `verify_output` function, no logic of its own.

**Tech Stack:** Python 3.12, Pydantic v2, `mcp` (official Python MCP SDK, `FastMCP` high-level API) — new dependency, added in the task that first uses it. `semgrep` (pip-installable, added as an optional dev/runtime dependency) and `gitleaks` (a Go binary, not pip-installable — documented as an external tool the operator installs; the gate degrades to WARN when it's absent, never requiring it). No database — the failure ledger is a JSON file, same tier of durability as Phase 0's `hardware_profile.yaml`; a durable store is Phase 4+.

**Spec:** `docs/ROADMAP.md` (Phase 2 row), `docs/ARCHITECTURE.md` §2 (`verify_output(diff, spec)` signature line) and §3 (`verify-rules/` pack directory — extra rules layered onto this gate, not built here), `CLAUDE.md` goal 3 (verification gate is mandatory, not optional — the product's main differentiator).

## Global Constraints

- No domain-specific logic in `core/` or `gateway/` (root `CLAUDE.md` goal 1) — every runner's command is a config value, never a hardcoded `pytest`/`ruff`/language check in code. A project supplies its own commands via `promptwise.config.yaml`.
- Every core function reads config only through `core/config/resolve.py` (`resolve_config_auto`/`resolve_path` — both already exist from Phase 1) — never `open()` a config file elsewhere.
- Every core function is covered by a failing-test-first cycle (`superpowers:test-driven-development`).
- Zero cloud calls, zero paid services — Semgrep and Gitleaks both run fully local/offline; this plan does not wire the "diff-vs-spec self-review by a second model" leg from `docs/research/aug2026-findings.md` Part 5 row 1 (that needs a real LLM call, which needs LiteLLM wiring that doesn't exist yet — explicitly deferred, not silently dropped, to a follow-up once a model-calling primitive exists).
- A missing external tool (Semgrep, Gitleaks) WARNs and is skipped — it never FAILs the gate or crashes it, mirroring `core/diagnostics/checks.py`'s established WARN-not-crash convention.
- Conventional Commits, no AI-attribution trailers.

---

### Task 1: Verify core models + config defaults

**Files:**
- Create: `core/verify/__init__.py`
- Create: `core/verify/models.py`
- Modify: `core/config/defaults.yaml`
- Create: `promptwise.config.yaml` (repo root — this project's own org config, dogfooding Phase 1's config layering)
- Test: `core/tests/verify/__init__.py`
- Test: `core/tests/verify/test_models.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Severity = Literal["error", "warning", "info"]`, `VerifyFinding(BaseModel)` (tool: str, severity: Severity, message: str, file: str | None = None, line: int | None = None), `ToolRunResult(BaseModel)` (tool: str, ran: bool, passed: bool, output: str, findings: list[VerifyFinding] = []), `VerifyResult(BaseModel)` (passed: bool, results: list[ToolRunResult], blocked_reason: str | None = None, retry_loop_broken: bool = False). Tasks 2-6 all import these.

- [ ] **Step 1: Write the failing test**

```python
# core/tests/verify/__init__.py
```

```python
# core/tests/verify/test_models.py
from core.verify.models import ToolRunResult, VerifyFinding, VerifyResult


def test_verify_finding_defaults():
    finding = VerifyFinding(tool="semgrep", severity="error", message="hardcoded secret")
    assert finding.file is None
    assert finding.line is None


def test_tool_run_result_defaults_to_no_findings():
    result = ToolRunResult(tool="pytest", ran=True, passed=True, output="5 passed")
    assert result.findings == []


def test_verify_result_defaults():
    result = VerifyResult(passed=True, results=[])
    assert result.blocked_reason is None
    assert result.retry_loop_broken is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/tests/verify/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.verify'`

- [ ] **Step 3: Write `core/verify/__init__.py`** (empty package marker)

```python
# core/verify/__init__.py
```

- [ ] **Step 4: Write `core/verify/models.py`**

```python
# core/verify/models.py
from typing import Literal

from pydantic import BaseModel

Severity = Literal["error", "warning", "info"]


class VerifyFinding(BaseModel):
    tool: str
    severity: Severity
    message: str
    file: str | None = None
    line: int | None = None


class ToolRunResult(BaseModel):
    tool: str
    ran: bool
    passed: bool
    output: str
    findings: list[VerifyFinding] = []


class VerifyResult(BaseModel):
    passed: bool
    results: list[ToolRunResult]
    blocked_reason: str | None = None
    retry_loop_broken: bool = False
```

- [ ] **Step 5: Modify `core/config/defaults.yaml`** — add a `verify:` section

Add this block (keep every existing key untouched):

```yaml
verify:
  test_command: ""
  lint_command: ""
  lint_blocks: false
  semgrep_config: "auto"
  max_identical_failures: 3
  failure_ledger_path: .promptwise/failure_ledger.json
```

- [ ] **Step 6: Create `promptwise.config.yaml`** at the repo root — this project's own org config, giving `verify_output` a real command to run against this codebase

```yaml
verify:
  test_command: "pytest -q"
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest core/tests/verify/test_models.py -v`
Expected: PASS (3 tests)

- [ ] **Step 8: Run the full suite to confirm nothing else broke**

Run: `pytest -v`
Expected: PASS (all tests)

- [ ] **Step 9: Commit**

```bash
git add core/verify/__init__.py core/verify/models.py core/config/defaults.yaml promptwise.config.yaml core/tests/verify/__init__.py core/tests/verify/test_models.py
git commit -m "feat: verify_output core models and config defaults"
```

---

### Task 2: Failure ledger

**Files:**
- Create: `core/verify/ledger.py`
- Test: `core/tests/verify/test_ledger.py`

**Interfaces:**
- Consumes: `resolve_path` (from `core.config.resolve`, added in Phase 1's final-review fix wave), `resolve_config_auto`.
- Produces: `LedgerEntry(BaseModel)` (key: str, failure_count: int, last_signature: str, last_seen: str), `record_failure(config: dict, key: str, signature: str) -> bool` (appends/updates the ledger, returns `True` if this signature has now repeated `>= config["verify"]["max_identical_failures"]` times consecutively — the "break the retry loop" signal), `record_success(config: dict, key: str) -> None` (clears the entry for `key` — a pass resets the streak), `load_ledger(config: dict) -> dict[str, LedgerEntry]`, `save_ledger(config: dict, ledger: dict[str, LedgerEntry]) -> None`. Task 5's `verify_output` calls `record_failure`/`record_success`.

- [ ] **Step 1: Write the failing test**

```python
# core/tests/verify/test_ledger.py
from pathlib import Path

from core.verify.ledger import load_ledger, record_failure, record_success


def _config(tmp_path, max_failures=3):
    return {
        "verify": {
            "failure_ledger_path": str(tmp_path / "failure_ledger.json"),
            "max_identical_failures": max_failures,
        }
    }


def test_record_failure_does_not_break_loop_below_threshold(tmp_path):
    config = _config(tmp_path, max_failures=3)
    assert record_failure(config, "task-1", "same-error") is False
    assert record_failure(config, "task-1", "same-error") is False


def test_record_failure_breaks_loop_at_threshold(tmp_path):
    config = _config(tmp_path, max_failures=3)
    record_failure(config, "task-1", "same-error")
    record_failure(config, "task-1", "same-error")
    assert record_failure(config, "task-1", "same-error") is True


def test_different_signature_resets_the_streak(tmp_path):
    config = _config(tmp_path, max_failures=3)
    record_failure(config, "task-1", "error-A")
    record_failure(config, "task-1", "error-A")
    assert record_failure(config, "task-1", "error-B") is False  # different failure, streak resets
    ledger = load_ledger(config)
    assert ledger["task-1"].failure_count == 1


def test_record_success_clears_the_entry(tmp_path):
    config = _config(tmp_path, max_failures=3)
    record_failure(config, "task-1", "same-error")
    record_failure(config, "task-1", "same-error")
    record_success(config, "task-1")
    ledger = load_ledger(config)
    assert "task-1" not in ledger


def test_ledger_persists_across_calls(tmp_path):
    config = _config(tmp_path, max_failures=5)
    record_failure(config, "task-1", "same-error")
    ledger = load_ledger(config)
    assert ledger["task-1"].failure_count == 1
    record_failure(config, "task-1", "same-error")
    ledger = load_ledger(config)
    assert ledger["task-1"].failure_count == 2


def test_missing_ledger_file_starts_empty(tmp_path):
    config = _config(tmp_path)
    ledger = load_ledger(config)
    assert ledger == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/tests/verify/test_ledger.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.verify.ledger'`

- [ ] **Step 3: Write `core/verify/ledger.py`**

```python
# core/verify/ledger.py
"""Failure ledger — docs/ROADMAP.md Phase 2 row: breaks an identical-failure
retry loop after N attempts. A JSON file, config-resolved via resolve_path
(same pattern Phase 1 established for packs/catalog paths) — no database
yet, that's a Phase 4+ concern.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from core.config.resolve import resolve_path


class LedgerEntry(BaseModel):
    key: str
    failure_count: int
    last_signature: str
    last_seen: str


def _ledger_path(config: dict[str, Any]) -> Path:
    return resolve_path(config, "verify.failure_ledger_path", ".promptwise/failure_ledger.json")


def load_ledger(config: dict[str, Any]) -> dict[str, LedgerEntry]:
    path = _ledger_path(config)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return {key: LedgerEntry(**value) for key, value in raw.items()}


def save_ledger(config: dict[str, Any], ledger: dict[str, LedgerEntry]) -> None:
    path = _ledger_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump({key: entry.model_dump() for key, entry in ledger.items()}, f, indent=2)


def record_failure(config: dict[str, Any], key: str, signature: str) -> bool:
    """Records a failure under `key`. Returns True if this exact `signature`
    has now repeated `max_identical_failures` times in a row — the caller
    should stop retrying and surface this to the human/agent instead.
    """
    ledger = load_ledger(config)
    max_identical = config.get("verify", {}).get("max_identical_failures", 3)
    now = datetime.now(timezone.utc).isoformat()

    existing = ledger.get(key)
    if existing is not None and existing.last_signature == signature:
        count = existing.failure_count + 1
    else:
        count = 1

    ledger[key] = LedgerEntry(key=key, failure_count=count, last_signature=signature, last_seen=now)
    save_ledger(config, ledger)
    return count >= max_identical


def record_success(config: dict[str, Any], key: str) -> None:
    ledger = load_ledger(config)
    if key in ledger:
        del ledger[key]
        save_ledger(config, ledger)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest core/tests/verify/test_ledger.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/verify/ledger.py core/tests/verify/test_ledger.py
git commit -m "feat: failure ledger that breaks identical-failure retry loops"
```

---

### Task 3: Test + lint runners

**Files:**
- Create: `core/verify/runners.py`
- Test: `core/tests/verify/test_runners.py`

**Interfaces:**
- Consumes: `ToolRunResult`, `VerifyFinding` (Task 1).
- Produces: `run_command(tool_name: str, command: str, cwd: Path | None = None, timeout: int = 300) -> ToolRunResult` (the shared subprocess primitive — empty `command` means "not configured", returns `ran=False, passed=True` so an unconfigured check never blocks), `run_tests(config: dict, cwd: Path | None = None) -> ToolRunResult` (reads `verify.test_command`), `run_lint(config: dict, cwd: Path | None = None) -> ToolRunResult` (reads `verify.lint_command`). Task 5's `verify_output` calls `run_tests`/`run_lint`.

- [ ] **Step 1: Write the failing test**

```python
# core/tests/verify/test_runners.py
from core.verify.runners import run_command, run_lint, run_tests


def test_run_command_with_empty_command_is_a_noop_pass():
    result = run_command("tests", "", None)
    assert result.ran is False
    assert result.passed is True


def test_run_command_runs_a_passing_command(tmp_path):
    result = run_command("tests", "python -c \"print('ok')\"", tmp_path)
    assert result.ran is True
    assert result.passed is True
    assert "ok" in result.output


def test_run_command_runs_a_failing_command(tmp_path):
    result = run_command("tests", "python -c \"import sys; sys.exit(1)\"", tmp_path)
    assert result.ran is True
    assert result.passed is False


def test_run_tests_reads_verify_test_command(tmp_path):
    config = {"verify": {"test_command": "python -c \"print('tests ran')\""}}
    result = run_tests(config, tmp_path)
    assert result.tool == "tests"
    assert result.passed is True
    assert "tests ran" in result.output


def test_run_tests_with_no_configured_command_is_skipped():
    result = run_tests({"verify": {}}, None)
    assert result.ran is False
    assert result.passed is True


def test_run_lint_reads_verify_lint_command(tmp_path):
    config = {"verify": {"lint_command": "python -c \"print('lint ran')\""}}
    result = run_lint(config, tmp_path)
    assert result.tool == "lint"
    assert result.passed is True


def test_run_command_handles_a_nonexistent_executable_without_crashing(tmp_path):
    result = run_command("tests", "this-binary-does-not-exist-anywhere --flag", tmp_path)
    assert result.ran is True
    assert result.passed is False
    assert "error" in result.output.lower() or "not found" in result.output.lower() or "no such file" in result.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/tests/verify/test_runners.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.verify.runners'`

- [ ] **Step 3: Write `core/verify/runners.py`**

```python
# core/verify/runners.py
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


def run_command(tool_name: str, command: str, cwd: Path | None, timeout: int = 300) -> ToolRunResult:
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
        return ToolRunResult(tool=tool_name, ran=True, passed=proc.returncode == 0, output=output.strip())
    except FileNotFoundError as exc:
        return ToolRunResult(tool=tool_name, ran=True, passed=False, output=f"{tool_name}: executable not found — {exc}")
    except subprocess.TimeoutExpired:
        return ToolRunResult(tool=tool_name, ran=True, passed=False, output=f"{tool_name}: timed out after {timeout}s")


def run_tests(config: dict[str, Any], cwd: Path | None = None) -> ToolRunResult:
    command = config.get("verify", {}).get("test_command", "")
    return run_command("tests", command, cwd)


def run_lint(config: dict[str, Any], cwd: Path | None = None) -> ToolRunResult:
    command = config.get("verify", {}).get("lint_command", "")
    return run_command("lint", command, cwd)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest core/tests/verify/test_runners.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/verify/runners.py core/tests/verify/test_runners.py
git commit -m "feat: config-driven test and lint runners for the verification gate"
```

---

### Task 4: Semgrep + Gitleaks security runners

**Files:**
- Create: `core/verify/security.py`
- Test: `core/tests/verify/test_security.py`

**Interfaces:**
- Consumes: `ToolRunResult`, `VerifyFinding` (Task 1), `run_command`-style graceful-skip convention (Task 3, though this task doesn't literally call `run_command` since it needs JSON parsing — same skip/never-crash contract).
- Produces: `run_semgrep(config: dict, cwd: Path | None = None) -> ToolRunResult`, `run_gitleaks(config: dict, cwd: Path | None = None) -> ToolRunResult`. Both WARN-and-skip (`ran=False, passed=True`) when the binary isn't on `PATH` — checked via `shutil.which`. Task 5's `verify_output` calls both.

- [ ] **Step 1: Write the failing test**

```python
# core/tests/verify/test_security.py
import shutil

import pytest

from core.verify.security import run_gitleaks, run_semgrep


def test_run_semgrep_skips_gracefully_when_binary_missing(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    result = run_semgrep({"verify": {}}, None)
    assert result.ran is False
    assert result.passed is True


def test_run_gitleaks_skips_gracefully_when_binary_missing(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    result = run_gitleaks({"verify": {}}, None)
    assert result.ran is False
    assert result.passed is True


@pytest.mark.skipif(shutil.which("semgrep") is None, reason="semgrep not installed in this environment")
def test_run_semgrep_actually_runs_when_installed(tmp_path):
    (tmp_path / "clean.py").write_text("x = 1\n")
    result = run_semgrep({"verify": {"semgrep_config": "auto"}}, tmp_path)
    assert result.ran is True
    assert result.tool == "semgrep"


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks not installed in this environment")
def test_run_gitleaks_detects_a_planted_secret(tmp_path):
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    (tmp_path / "leaked.py").write_text('AWS_KEY = "AKIAABCDEFGHIJKLMNOP"\n')
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True)
    result = run_gitleaks({"verify": {}}, tmp_path)
    assert result.ran is True
    assert result.passed is False
    assert len(result.findings) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/tests/verify/test_security.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.verify.security'`

- [ ] **Step 3: Write `core/verify/security.py`**

```python
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
```

Note on the `gitleaks` command line above: gitleaks' exact flag set has shifted across versions (v7 vs v8 use different subcommands/flags). Before trusting the snippet verbatim, run `gitleaks --help` and `gitleaks detect --help` against whatever version is actually installed in this environment (if any — the skip-gracefully tests don't need it) and adjust the argument list to match; the JSON-parsing logic (`RuleID`/`File`/`StartLine` keys) is what the `test_run_gitleaks_detects_a_planted_secret` test (which only runs when gitleaks is actually installed) will tell you if wrong.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest core/tests/verify/test_security.py -v`
Expected: PASS (2 tests always run; the 2 `skipif`-guarded tests run only if semgrep/gitleaks happen to be installed in this environment — either outcome is fine, do not install them just to make these pass)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/verify/security.py core/tests/verify/test_security.py
git commit -m "feat: Semgrep and Gitleaks runners, graceful skip when not installed"
```

---

### Task 5: `verify_output` orchestrator

**Files:**
- Create: `core/verify/gate.py`
- Test: `core/tests/verify/test_gate.py`

**Interfaces:**
- Consumes: `run_tests`, `run_lint` (Task 3); `run_semgrep`, `run_gitleaks` (Task 4); `record_failure`, `record_success` (Task 2); `resolve_config_auto` (Phase 1).
- Produces: `verify_output(diff: str, spec: str | None = None, cwd: Path | None = None, config: dict | None = None, ledger_key: str | None = None) -> VerifyResult`. The gateway (Task 6) and the MCP server (Task 7) both call this directly. `diff` and `spec` are assumed already applied/available in `cwd`'s working tree — `verify_output` runs checks against `cwd` as it currently stands, it does not `git apply` anything itself (that responsibility belongs to whatever orchestrates the agent loop, a later phase's `orchestrate_tasks`).

- [ ] **Step 1: Write the failing test**

```python
# core/tests/verify/test_gate.py
from pathlib import Path

from core.verify.gate import verify_output


def _write_project(tmp_path: Path, test_command: str) -> dict:
    return {"verify": {"test_command": test_command, "lint_command": "", "max_identical_failures": 3, "failure_ledger_path": str(tmp_path / "ledger.json")}}


def test_verify_output_blocks_a_deliberately_broken_diff(tmp_path):
    config = _write_project(tmp_path, "python -c \"import sys; sys.exit(1)\"")
    result = verify_output(diff="broken change", spec="add a feature", cwd=tmp_path, config=config)
    assert result.passed is False
    assert result.blocked_reason is not None


def test_verify_output_passes_a_correct_diff(tmp_path):
    config = _write_project(tmp_path, "python -c \"print('all good')\"")
    result = verify_output(diff="correct change", spec="add a feature", cwd=tmp_path, config=config)
    assert result.passed is True
    assert result.blocked_reason is None


def test_verify_output_records_failure_and_breaks_loop_after_max_identical(tmp_path):
    config = _write_project(tmp_path, "python -c \"import sys; sys.exit(1)\"")
    config["verify"]["max_identical_failures"] = 2
    r1 = verify_output(diff="d", spec="s", cwd=tmp_path, config=config, ledger_key="task-x")
    assert r1.retry_loop_broken is False
    r2 = verify_output(diff="d", spec="s", cwd=tmp_path, config=config, ledger_key="task-x")
    assert r2.retry_loop_broken is True


def test_verify_output_success_clears_the_ledger(tmp_path):
    fail_config = _write_project(tmp_path, "python -c \"import sys; sys.exit(1)\"")
    fail_config["verify"]["max_identical_failures"] = 5
    verify_output(diff="d", spec="s", cwd=tmp_path, config=fail_config, ledger_key="task-y")

    from core.verify.ledger import load_ledger

    ledger = load_ledger(fail_config)
    assert "task-y" in ledger

    pass_config = _write_project(tmp_path, "python -c \"print('ok')\"")
    pass_config["verify"]["failure_ledger_path"] = fail_config["verify"]["failure_ledger_path"]
    verify_output(diff="d2", spec="s", cwd=tmp_path, config=pass_config, ledger_key="task-y")

    ledger = load_ledger(pass_config)
    assert "task-y" not in ledger


def test_verify_output_without_ledger_key_never_touches_the_ledger(tmp_path):
    config = _write_project(tmp_path, "python -c \"import sys; sys.exit(1)\"")
    result = verify_output(diff="d", spec="s", cwd=tmp_path, config=config)  # no ledger_key
    assert result.passed is False
    assert result.retry_loop_broken is False


def test_verify_output_no_test_command_configured_still_passes(tmp_path):
    config = {"verify": {"test_command": "", "lint_command": "", "max_identical_failures": 3, "failure_ledger_path": str(tmp_path / "ledger.json")}}
    result = verify_output(diff="d", spec="s", cwd=tmp_path, config=config)
    assert result.passed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/tests/verify/test_gate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.verify.gate'`

- [ ] **Step 3: Write `core/verify/gate.py`**

```python
# core/verify/gate.py
"""verify_output — docs/ARCHITECTURE.md §2, the mandatory verification
gate (CLAUDE.md goal 3). Runs tests + lint + Semgrep + Gitleaks against a
working tree, blocks until they pass, and tracks a failure ledger that
breaks an identical-failure retry loop after N attempts.

Does NOT apply `diff` to the working tree itself — `cwd` is assumed to
already reflect the change under review. `diff`/`spec` are carried through
for logging and as the failure ledger's signature source; a future phase's
LLM-based "diff-vs-spec self-review" leg is not implemented here (needs a
model-calling primitive that doesn't exist yet) — deliberately deferred.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from core.config.resolve import resolve_config_auto
from core.verify.ledger import record_failure, record_success
from core.verify.models import VerifyResult
from core.verify.runners import run_lint, run_tests
from core.verify.security import run_gitleaks, run_semgrep


def _signature(results: list) -> str:
    """A stable signature for 'the same failure' — used to detect an
    identical-failure retry loop. Based on which tools failed and their
    pass/fail shape, not full output text (output often contains
    timestamps/paths that vary run to run without the failure itself
    changing).
    """
    parts = [f"{r.tool}:{r.passed}" for r in results]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def verify_output(
    diff: str,
    spec: str | None = None,
    cwd: Path | None = None,
    config: dict[str, Any] | None = None,
    ledger_key: str | None = None,
) -> VerifyResult:
    config = config if config is not None else resolve_config_auto()

    test_result = run_tests(config, cwd)
    lint_result = run_lint(config, cwd)
    semgrep_result = run_semgrep(config, cwd)
    gitleaks_result = run_gitleaks(config, cwd)

    results = [test_result, lint_result, semgrep_result, gitleaks_result]

    lint_blocks = bool(config.get("verify", {}).get("lint_blocks", False))
    blocking_failures = []
    if not test_result.passed:
        blocking_failures.append("tests failed")
    if lint_blocks and not lint_result.passed:
        blocking_failures.append("lint failed")
    if not semgrep_result.passed:
        blocking_failures.append("semgrep found blocking (error-severity) findings")
    if not gitleaks_result.passed:
        blocking_failures.append("gitleaks detected a secret")

    passed = len(blocking_failures) == 0
    blocked_reason = "; ".join(blocking_failures) if blocking_failures else None

    retry_loop_broken = False
    if ledger_key is not None:
        if passed:
            record_success(config, ledger_key)
        else:
            retry_loop_broken = record_failure(config, ledger_key, _signature(results))

    return VerifyResult(passed=passed, results=results, blocked_reason=blocked_reason, retry_loop_broken=retry_loop_broken)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest core/tests/verify/test_gate.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Run the full suite** — this is also the moment this repo's own `promptwise.config.yaml` (Task 1) gets exercised for real: `verify_output` with no explicit `config` argument will discover it via `resolve_config_auto()` and run `pytest -q` against whatever `cwd` it's pointed at

Run: `pytest -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add core/verify/gate.py core/tests/verify/test_gate.py
git commit -m "feat: verify_output orchestrator with failure-ledger retry-loop breaking"
```

---

### Task 6: Gateway `POST /verify` endpoint

**Files:**
- Modify: `gateway/app.py`
- Test: `gateway/tests/test_app.py` (append)

**Interfaces:**
- Consumes: `verify_output` (Task 5).
- Produces: `POST /verify` (body: `{"diff": str, "spec": str | null, "cwd": str | null, "ledger_key": str | null}`, returns: `VerifyResult` JSON).

- [ ] **Step 1: Write the failing test**

```python
# gateway/tests/test_app.py — append
def test_verify_endpoint_passes_with_no_test_command_configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    response = client.post("/verify", json={"diff": "some change", "spec": "some spec"})
    assert response.status_code == 200
    body = response.json()
    assert "passed" in body
    assert "results" in body


def test_verify_endpoint_accepts_a_cwd_override(tmp_path):
    (tmp_path / "pass_marker.txt").write_text("ok")
    response = client.post(
        "/verify",
        json={
            "diff": "d",
            "spec": "s",
            "cwd": str(tmp_path),
        },
    )
    assert response.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest gateway/tests/test_app.py -v`
Expected: FAIL with `404` for `/verify` (route doesn't exist yet)

- [ ] **Step 3: Modify `gateway/app.py`**

The file currently has `/healthz`, `/diagnostics`, `/route`, `/cost-report`, and a `lifespan` hook (`Path` and `HTTPException` are already imported; `BaseModel` is not). Add one new import line, a request model, and one route — do not change anything else. Full new file:

```python
# gateway/app.py
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core.config.resolve import resolve_config_auto
from core.diagnostics.checks import run_diagnostics
from core.diagnostics.hardware import detect_hardware, write_hardware_profile
from core.routing.catalog import load_catalog
from core.routing.cost import CostRecord, cost_report
from core.routing.router import RouteRequest, RoutingDecision, route_request
from core.verify.gate import verify_output
from core.verify.models import VerifyResult
from gateway.healthcheck import is_alive


@asynccontextmanager
async def lifespan(app: FastAPI):
    path = Path(resolve_config_auto()["diagnostics"]["hardware_profile_path"])
    write_hardware_profile(detect_hardware(), path)
    yield


app = FastAPI(title="PromptWise Agentic OS Gateway", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok" if is_alive() else "down"}


@app.get("/diagnostics")
def diagnostics() -> list[dict[str, str]]:
    return [result.model_dump() for result in run_diagnostics()]


@app.post("/route", response_model=RoutingDecision)
def route(request: RouteRequest) -> RoutingDecision:
    return route_request(request)


@app.post("/cost-report")
def cost_report_endpoint(records: list[CostRecord]) -> dict:
    catalog = load_catalog()
    for record in records:
        if record.tier not in catalog:
            raise HTTPException(status_code=422, detail=f"unknown tier: {record.tier}")
    return cost_report(records, catalog)


class VerifyRequest(BaseModel):
    diff: str
    spec: str | None = None
    cwd: str | None = None
    ledger_key: str | None = None


@app.post("/verify", response_model=VerifyResult)
def verify(request: VerifyRequest) -> VerifyResult:
    cwd = Path(request.cwd) if request.cwd else None
    return verify_output(diff=request.diff, spec=request.spec, cwd=cwd, ledger_key=request.ledger_key)
```

This is a straight superset of the file's current content — verify against what's actually on disk before overwriting; only the 3 new import lines, the `VerifyRequest` class, and the `/verify` route should differ.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest gateway/tests/test_app.py -v`
Expected: PASS (all tests, including the 2 new ones)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add gateway/app.py gateway/tests/test_app.py
git commit -m "feat: gateway POST /verify endpoint"
```

---

### Task 7: In-process MCP server exposing `verify_output`

**Files:**
- Modify: `pyproject.toml` (add `mcp` dependency)
- Create: `gateway/mcp_server.py`
- Test: `gateway/tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `verify_output` (Task 5).
- Produces: `mcp_app` — a `FastMCP` instance (from the official `mcp` Python SDK) with one registered tool, `verify_output`, callable by any MCP-capable agent (Claude Code, Cursor, OpenCode) once configured to connect to it. This is the plan's implementation of `CLAUDE.md`'s "MCP server via the official Python `mcp` SDK, hosted in-process inside the gateway" decision (resolved during this plan's kickoff, see `CLAUDE.md`'s Tech Stack section).

**A note on this task's code, before you start:** the `mcp` Python SDK's exact API (import paths, decorator names, tool-introspection methods) may have moved since this plan was written — its `FastMCP` high-level API is the best-effort code below, written from the standard, well-documented pattern, but you are expected to verify it against whatever version `pip install mcp` actually installs and adjust names/imports to match if they differ. This is the one task in this plan where "the plan text is wrong, the installed library is right" is an expected, not exceptional, outcome — if you hit an import or attribute error, run `python -c "import mcp; help(mcp)"` (or `pip show mcp` and read its docs) to find the real name, use it, and note the deviation in your report. Do not treat a mismatched API name here as a blocker to escalate — resolve it yourself and keep going.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`'s `dependencies` list (in `[project]`), add `"mcp>=1.2"`.

- [ ] **Step 2: Install it**

Run: `pip install -e ".[dev]"`

- [ ] **Step 3: Write the failing test**

```python
# gateway/tests/test_mcp_server.py
from gateway.mcp_server import mcp_app


def test_mcp_app_is_created():
    assert mcp_app is not None
    assert mcp_app.name == "promptwise-agentic-os"


async def test_mcp_app_has_verify_output_tool():
    tools = await mcp_app.list_tools()
    tool_names = {t.name for t in tools}
    assert "verify_output" in tool_names
```

(If `list_tools()` isn't `async` in the installed SDK version, or isn't the correct method name, adjust — see the note above. The test's intent — proving the server object exists and has registered a tool named `verify_output` — is what matters, not this exact method call.)

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest gateway/tests/test_mcp_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gateway.mcp_server'`

- [ ] **Step 5: Write `gateway/mcp_server.py`**

```python
# gateway/mcp_server.py
"""In-process MCP server — exposes verify_output to any MCP-capable agent
(Claude Code, Cursor, OpenCode). Thin adapter, same pattern as the FastAPI
routes in app.py: no logic here beyond argument marshalling, everything
real lives in core.verify.gate.verify_output.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from core.verify.gate import verify_output as _verify_output

mcp_app = FastMCP("promptwise-agentic-os")


@mcp_app.tool()
def verify_output(diff: str, spec: str = "", cwd: str = "", ledger_key: str = "") -> dict:
    """Run the verification gate (tests, lint, Semgrep, Gitleaks) against
    the current working tree and report whether the change is safe to
    consider done. Call this after making any code change, before
    declaring the task complete.

    Args:
        diff: A description or unified diff of what changed (for logging
            and the failure-retry ledger — this function does not apply
            the diff itself, it checks the working tree as it stands).
        spec: The requirement/spec this change is meant to satisfy.
        cwd: Working directory to run checks in. Defaults to the server's
            own cwd if empty.
        ledger_key: A stable identifier for this task, used to detect
            repeated identical failures across retries. Leave empty to
            skip retry-loop tracking.
    """
    from pathlib import Path

    result = _verify_output(
        diff=diff,
        spec=spec or None,
        cwd=Path(cwd) if cwd else None,
        ledger_key=ledger_key or None,
    )
    return result.model_dump()


if __name__ == "__main__":
    mcp_app.run()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest gateway/tests/test_mcp_server.py -v`
Expected: PASS (2 tests) — adjust the test/implementation together if the SDK's real API differs from the guess above, per this task's opening note

- [ ] **Step 7: Run the full suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 8: Live smoke test (manual, not a pytest assertion — mirrors Phase 0 Task 7's live `docker compose up` verification)**

Run: `python -m gateway.mcp_server` (or `python gateway/mcp_server.py`) in one terminal — it should start and wait for a client on stdio without crashing. This proves the server is at least launchable; a full round-trip test against a real Claude Code session (adding this server to a `.mcp.json` and invoking `verify_output` from an actual Claude Code conversation) is the true ROADMAP acceptance criterion ("works against a real Claude Code session via MCP") and is a manual step for whoever executes this task to perform and report on — record what you tried and what happened in the task report, even if you can't fully automate it in this sandbox.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml gateway/mcp_server.py gateway/tests/test_mcp_server.py
git commit -m "feat: in-process MCP server exposing verify_output"
```

---

## Self-Review Notes (already applied above)

- **Spec coverage:** ROADMAP Phase 2's four acceptance criteria are covered — Task 5's tests directly prove `verify_output` blocks a deliberately-broken diff and passes a correct one; Task 4 wires Semgrep/Gitleaks (gracefully optional, per Global Constraints); Task 2 + Task 5's retry-loop tests prove the failure ledger breaks after N identical failures; Task 7 builds the MCP exposure, with an explicit, honest note that the live "real Claude Code session" leg is a manual verification step this plan cannot fully automate in a sandboxed subagent run. The "diff-vs-spec self-review by a second model" leg from the research doc is explicitly out of scope (Global Constraints), not silently dropped.
- **Placeholder scan:** no TBD/TODO. Task 7's API-uncertainty note is a deliberate, bounded instruction (verify against the installed library), not a placeholder — the code given is real, best-effort, working code, not a stub.
- **Type consistency:** `VerifyResult`/`ToolRunResult`/`VerifyFinding` (Task 1) are the single shapes used by every runner (Tasks 3-4), the orchestrator (Task 5), the gateway route (Task 6), and the MCP tool (Task 7) — verified consistent across all five.
- **Config-driven, not hardcoded:** every runner reads its command from `config["verify"][...]`, resolved via `resolve_config_auto`/`resolve_path` (Phase 1) — no task hardcodes `pytest`, `ruff`, or any other language-specific tool inside `core/`. This repo's own `pytest -q` command lives in `promptwise.config.yaml` (Task 1), a project-level config file, not core code — exactly the "packs/projects supply behavior, core stays generic" pattern `CLAUDE.md` goal 1 requires.

## Next plan after this one

Phase 3 — Governed system control + tool registry (`docs/ROADMAP.md` row 4): `check_policy`, JIT grants, undo buffer, hash-chained audit, MCP tool allowlist with pinned versions/hashes and a kill switch (the tool registry this phase's MCP server should eventually be gated behind), untrusted-content marking. Write that plan only after Phase 2's acceptance criteria are green — including the manual MCP smoke test from Task 7.
