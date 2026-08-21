# Phase 0 — Compose Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the compose foundation (Ollama + Qdrant + LiteLLM + FastAPI gateway) with a working config resolver, hardware profiler, and `promptwise doctor` diagnostics baseline — the first phase from `docs/ROADMAP.md`.

**Architecture:** Python 3.12 core engine (`core/`) exposes typed, testable functions with zero I/O side effects beyond what's declared; a thin FastAPI gateway (`gateway/`) wraps them for HTTP; a Typer CLI (`scripts/promptwise.py`) wraps them for local ops; Docker Compose wires the whole thing plus Ollama and Qdrant as sidecar services. Every core function is TDD'd before the gateway/CLI wrapper is written.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, PyYAML, Typer, pytest, Docker Compose. No database yet (Phase 1+); no Qdrant client calls yet (Phase 4) — this phase only proves the service is *reachable*, per the `services.qdrant` doctor check.

**Spec:** `docs/ROADMAP.md` (Phase 0 row), `docs/ARCHITECTURE.md` §4 (config layering), `docs/MAINTENANCE.md` §2 (doctor checks).

## Global Constraints

- No domain-specific logic in `core/` or `gateway/` (root `CLAUDE.md` goal 1).
- Every core function reads config only through `core/config/resolve.py` (`ARCHITECTURE.md` §4) — never `open()` a config file elsewhere.
- Every core function is covered by a failing-test-first cycle (`superpowers:test-driven-development`).
- Zero cloud calls, zero paid services — everything runs via `docker compose up` at $0 (root `CLAUDE.md` goal 5).
- Conventional Commits, no AI-attribution trailers.

---

### Task 1: Project scaffolding & Python packaging

**Files:**
- Create: `pyproject.toml`
- Create: `core/__init__.py`
- Create: `core/config/__init__.py`
- Create: `.gitignore`
- Test: `core/tests/test_scaffold.py`

**Interfaces:**
- Produces: importable `core` package installable in editable mode (`pip install -e .`), pytest discoverable under `core/tests/`.

- [ ] **Step 1: Write the failing test**

```python
# core/tests/test_scaffold.py
import core

def test_core_package_has_version():
    assert hasattr(core, "__version__")
    assert core.__version__ == "0.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/tests/test_scaffold.py -v`
Expected: FAIL with `AttributeError: module 'core' has no attribute '__version__'` (or `ModuleNotFoundError: No module named 'core'` if not yet installed — install first per Step 3).

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[project]
name = "promptwise-core"
version = "0.1.0"
description = "PromptWise Agentic OS — core engine"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.8",
    "pyyaml>=6.0",
    "typer>=0.12",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27"]

[project.scripts]
promptwise = "scripts.promptwise:app"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["core*", "gateway*", "scripts*"]

[tool.pytest.ini_options]
testpaths = ["core/tests", "gateway/tests"]
```

- [ ] **Step 4: Write `core/__init__.py`**

```python
# core/__init__.py
__version__ = "0.1.0"
```

- [ ] **Step 5: Write `core/config/__init__.py`** (empty package marker for now)

```python
# core/config/__init__.py
```

- [ ] **Step 6: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
*.egg-info/
.pytest_cache/
packs/installed/*
!packs/installed/.gitkeep
config/hardware_profile.yaml
.promptwise/local.yaml
```

- [ ] **Step 7: Install editable and run test**

Run: `pip install -e ".[dev]"` then `pytest core/tests/test_scaffold.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml core/__init__.py core/config/__init__.py .gitignore core/tests/test_scaffold.py
git commit -m "chore: scaffold Python package for core engine"
```

---

### Task 2: Config resolver (layered configuration)

**Files:**
- Create: `core/config/defaults.yaml`
- Create: `core/config/resolve.py`
- Test: `core/tests/config/test_resolve.py`

**Interfaces:**
- Consumes: nothing (first real module).
- Produces: `resolve_config(org_path: Path | None = None, project_path: Path | None = None, local_path: Path | None = None, env: Mapping[str, str] | None = None) -> dict` — merges the 5 layers from `docs/ARCHITECTURE.md` §4, later layers win. Later tasks (hardware profiler, diagnostics, gateway) import `resolve_config` from `core.config.resolve`.

- [ ] **Step 1: Write the failing test**

```python
# core/tests/config/test_resolve.py
from pathlib import Path
from core.config.resolve import resolve_config

def test_defaults_only():
    cfg = resolve_config()
    assert cfg["engine"]["name"] == "promptwise-agentic-os"
    assert cfg["engine"]["local_only"] is True

def test_org_overrides_defaults(tmp_path):
    org_file = tmp_path / "promptwise.config.yaml"
    org_file.write_text("engine:\n  local_only: false\n")
    cfg = resolve_config(org_path=org_file)
    assert cfg["engine"]["local_only"] is False
    assert cfg["engine"]["name"] == "promptwise-agentic-os"  # untouched key survives merge

def test_env_wins_over_everything(tmp_path, monkeypatch):
    org_file = tmp_path / "promptwise.config.yaml"
    org_file.write_text("engine:\n  local_only: false\n")
    cfg = resolve_config(org_path=org_file, env={"PROMPTWISE_ENGINE__LOCAL_ONLY": "true"})
    assert cfg["engine"]["local_only"] is True

def test_missing_optional_layers_are_skipped(tmp_path):
    cfg = resolve_config(
        org_path=tmp_path / "does-not-exist.yaml",
        project_path=tmp_path / "also-missing.yaml",
    )
    assert cfg["engine"]["name"] == "promptwise-agentic-os"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/tests/config/test_resolve.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.config.resolve'`

- [ ] **Step 3: Write `core/config/defaults.yaml`**

```yaml
engine:
  name: promptwise-agentic-os
  local_only: true
routing:
  default_tier: local-small
policy:
  default_effect: deny
diagnostics:
  log_retention_days: 14
```

- [ ] **Step 4: Write `core/config/resolve.py`**

```python
# core/config/resolve.py
"""Layered config resolution — docs/ARCHITECTURE.md §4.

Precedence, later wins: system defaults < org config < project config <
user local overrides < environment variables.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Mapping

import yaml

DEFAULTS_PATH = Path(__file__).parent / "defaults.yaml"
ENV_PREFIX = "PROMPTWISE_"


def _load_yaml(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _coerce_scalar(raw: str) -> Any:
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _env_overrides(env: Mapping[str, str]) -> dict[str, Any]:
    """PROMPTWISE_ENGINE__LOCAL_ONLY=true -> {"engine": {"local_only": True}}"""
    result: dict[str, Any] = {}
    for key, raw_value in env.items():
        if not key.startswith(ENV_PREFIX):
            continue
        path = key[len(ENV_PREFIX):].lower().split("__")
        cursor = result
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = _coerce_scalar(raw_value)
    return result


def resolve_config(
    org_path: Path | None = None,
    project_path: Path | None = None,
    local_path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    cfg = _load_yaml(DEFAULTS_PATH)
    for path in (org_path, project_path, local_path):
        cfg = _deep_merge(cfg, _load_yaml(path))
    cfg = _deep_merge(cfg, _env_overrides(env if env is not None else os.environ))
    return cfg
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest core/tests/config/test_resolve.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 6: Commit**

```bash
git add core/config/defaults.yaml core/config/resolve.py core/tests/config/test_resolve.py
git commit -m "feat: layered config resolver (defaults/org/project/local/env)"
```

---

### Task 3: Hardware profiler

**Files:**
- Create: `core/diagnostics/__init__.py`
- Create: `core/diagnostics/hardware.py`
- Test: `core/tests/diagnostics/test_hardware.py`

**Interfaces:**
- Consumes: nothing external (uses `os`, `shutil`, stdlib only for v1 — no `psutil` dependency yet, keeps Task 1's dependency list minimal).
- Produces: `detect_hardware() -> HardwareProfile` (Pydantic model with `total_ram_gb: float`, `available_ram_gb: float`, `cpu_count: int`, `has_gpu: bool`) and `write_hardware_profile(profile: HardwareProfile, path: Path) -> None`. Task 4's `run_diagnostics` imports `detect_hardware`.

- [ ] **Step 1: Write the failing test**

```python
# core/tests/diagnostics/test_hardware.py
from pathlib import Path

from core.diagnostics.hardware import HardwareProfile, detect_hardware, write_hardware_profile


def test_detect_hardware_returns_positive_values():
    profile = detect_hardware()
    assert profile.total_ram_gb > 0
    assert profile.available_ram_gb > 0
    assert profile.cpu_count >= 1
    assert isinstance(profile.has_gpu, bool)


def test_write_hardware_profile_creates_yaml(tmp_path):
    profile = HardwareProfile(total_ram_gb=16.0, available_ram_gb=9.5, cpu_count=8, has_gpu=False)
    out_path = tmp_path / "hardware_profile.yaml"
    write_hardware_profile(profile, out_path)
    assert out_path.exists()
    content = out_path.read_text()
    assert "total_ram_gb: 16.0" in content
    assert "cpu_count: 8" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/tests/diagnostics/test_hardware.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.diagnostics'`

- [ ] **Step 3: Write `core/diagnostics/__init__.py`** (empty package marker)

```python
# core/diagnostics/__init__.py
```

- [ ] **Step 4: Write `core/diagnostics/hardware.py`**

```python
# core/diagnostics/hardware.py
"""Hardware Profiler — docs/research/v3-implementation-plan.md.

Stdlib-only for v1: works cross-platform without extra dependencies.
Windows uses ctypes for available RAM; POSIX reads /proc/meminfo when present.
"""
from __future__ import annotations

import ctypes
import os
import platform
import shutil
from pathlib import Path

import yaml
from pydantic import BaseModel


class HardwareProfile(BaseModel):
    total_ram_gb: float
    available_ram_gb: float
    cpu_count: int
    has_gpu: bool


def _ram_windows() -> tuple[float, float]:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
    gb = 1024 ** 3
    return stat.ullTotalPhys / gb, stat.ullAvailPhys / gb


def _ram_proc_meminfo() -> tuple[float, float]:
    values: dict[str, int] = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as f:
        for line in f:
            key, _, rest = line.partition(":")
            kb = rest.strip().split()[0]
            values[key] = int(kb)
    total_gb = values.get("MemTotal", 0) / (1024 ** 2)
    available_gb = values.get("MemAvailable", values.get("MemFree", 0)) / (1024 ** 2)
    return total_gb, available_gb


def _detect_ram() -> tuple[float, float]:
    if platform.system() == "Windows":
        return _ram_windows()
    if os.path.exists("/proc/meminfo"):
        return _ram_proc_meminfo()
    # Fallback (e.g. macOS without extra deps): unknown, report 0 so doctor WARNs, not crashes.
    return 0.0, 0.0


def _detect_gpu() -> bool:
    return shutil.which("nvidia-smi") is not None


def detect_hardware() -> HardwareProfile:
    total_ram_gb, available_ram_gb = _detect_ram()
    return HardwareProfile(
        total_ram_gb=round(total_ram_gb, 1),
        available_ram_gb=round(available_ram_gb, 1),
        cpu_count=os.cpu_count() or 1,
        has_gpu=_detect_gpu(),
    )


def write_hardware_profile(profile: HardwareProfile, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(profile.model_dump(), f, sort_keys=False)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest core/tests/diagnostics/test_hardware.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add core/diagnostics/__init__.py core/diagnostics/hardware.py core/tests/diagnostics/test_hardware.py
git commit -m "feat: hardware profiler (RAM/CPU/GPU detection, writes hardware_profile.yaml)"
```

---

### Task 4: Diagnostics — `run_diagnostics()` core checks

**Files:**
- Create: `core/diagnostics/checks.py`
- Create: `core/diagnostics/models.py`
- Test: `core/tests/diagnostics/test_checks.py`

**Interfaces:**
- Consumes: `detect_hardware()` from Task 3, `resolve_config()` from Task 2.
- Produces: `CheckResult(name: str, status: Literal["PASS","WARN","FAIL"], message: str)` and `run_diagnostics(config: dict | None = None) -> list[CheckResult]`. Gateway Task 5's `/healthz`-adjacent `/diagnostics` route and the CLI's `promptwise doctor` command both call `run_diagnostics`.
- Phase 0 implements 4 of the 8 checks from `docs/MAINTENANCE.md` §2 (`hardware.ram`, `config.resolve`, `services.gateway` is checked by the CLI/gateway directly — not here — `packs.integrity` trivially PASSes with zero packs installed). The remaining checks (`services.ollama`, `services.qdrant`, `policy.load`, `audit.chain`) are stubbed to WARN "not yet implemented — lands in Phase 1/3" so `run_diagnostics()` never crashes on a fresh Phase-0-only install, and the overall exit code is still 0 (WARN does not fail the run, only FAIL does).

- [ ] **Step 1: Write the failing test**

```python
# core/tests/diagnostics/test_checks.py
from core.diagnostics.checks import run_diagnostics


def test_run_diagnostics_returns_all_check_names():
    results = run_diagnostics()
    names = {r.name for r in results}
    assert names == {
        "hardware.ram",
        "config.resolve",
        "packs.integrity",
        "services.ollama",
        "services.qdrant",
        "policy.load",
        "audit.chain",
    }


def test_hardware_ram_check_passes_on_a_real_machine():
    results = run_diagnostics()
    ram_check = next(r for r in results if r.name == "hardware.ram")
    assert ram_check.status in ("PASS", "WARN")  # WARN only if <4GB available


def test_config_resolve_check_passes_with_defaults():
    results = run_diagnostics()
    config_check = next(r for r in results if r.name == "config.resolve")
    assert config_check.status == "PASS"


def test_packs_integrity_passes_with_zero_packs():
    results = run_diagnostics()
    packs_check = next(r for r in results if r.name == "packs.integrity")
    assert packs_check.status == "PASS"
    assert "0 packs" in packs_check.message


def test_unimplemented_checks_warn_not_fail():
    results = run_diagnostics()
    for name in ("services.ollama", "services.qdrant", "policy.load", "audit.chain"):
        check = next(r for r in results if r.name == name)
        assert check.status == "WARN"


def test_no_failures_means_clean_exit():
    results = run_diagnostics()
    assert not any(r.status == "FAIL" for r in results)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/tests/diagnostics/test_checks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.diagnostics.checks'`

- [ ] **Step 3: Write `core/diagnostics/models.py`**

```python
# core/diagnostics/models.py
from typing import Literal

from pydantic import BaseModel

Status = Literal["PASS", "WARN", "FAIL"]


class CheckResult(BaseModel):
    name: str
    status: Status
    message: str
```

- [ ] **Step 4: Write `core/diagnostics/checks.py`**

```python
# core/diagnostics/checks.py
"""promptwise doctor — core health checks. docs/MAINTENANCE.md §2."""
from __future__ import annotations

from pathlib import Path

from core.config.resolve import resolve_config
from core.diagnostics.hardware import detect_hardware
from core.diagnostics.models import CheckResult

MIN_AVAILABLE_RAM_GB = 4.0
PACKS_INSTALLED_DIR = Path("packs/installed")


def _check_hardware_ram() -> CheckResult:
    profile = detect_hardware()
    if profile.available_ram_gb == 0.0:
        return CheckResult(
            name="hardware.ram",
            status="WARN",
            message="could not detect available RAM on this platform — routing will assume local-small tier only",
        )
    if profile.available_ram_gb < MIN_AVAILABLE_RAM_GB:
        return CheckResult(
            name="hardware.ram",
            status="WARN",
            message=f"{profile.available_ram_gb}GB free, below the {MIN_AVAILABLE_RAM_GB}GB local-small floor — cloud-cheap tier will be preferred",
        )
    return CheckResult(
        name="hardware.ram",
        status="PASS",
        message=f"{profile.available_ram_gb}GB available of {profile.total_ram_gb}GB total",
    )


def _check_config_resolve() -> CheckResult:
    try:
        cfg = resolve_config()
        assert cfg["engine"]["name"]
    except Exception as exc:  # noqa: BLE001 — doctor must never crash on a bad config
        return CheckResult(name="config.resolve", status="FAIL", message=f"config failed to resolve: {exc}")
    return CheckResult(name="config.resolve", status="PASS", message="all config layers merged cleanly")


def _check_packs_integrity() -> CheckResult:
    if not PACKS_INSTALLED_DIR.exists():
        return CheckResult(name="packs.integrity", status="PASS", message="0 packs installed")
    pack_dirs = [p for p in PACKS_INSTALLED_DIR.iterdir() if p.is_dir()]
    # Phase 8 adds real manifest validation here; Phase 0 only counts.
    return CheckResult(name="packs.integrity", status="PASS", message=f"{len(pack_dirs)} packs installed")


def _not_yet_implemented(name: str, phase: str) -> CheckResult:
    return CheckResult(name=name, status="WARN", message=f"not yet implemented — lands in {phase}")


def run_diagnostics(config: dict | None = None) -> list[CheckResult]:
    return [
        _check_hardware_ram(),
        _check_config_resolve(),
        _check_packs_integrity(),
        _not_yet_implemented("services.ollama", "Phase 1"),
        _not_yet_implemented("services.qdrant", "Phase 4"),
        _not_yet_implemented("policy.load", "Phase 3"),
        _not_yet_implemented("audit.chain", "Phase 3"),
    ]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest core/tests/diagnostics/test_checks.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add core/diagnostics/models.py core/diagnostics/checks.py core/tests/diagnostics/test_checks.py
git commit -m "feat: run_diagnostics core health checks (doctor baseline)"
```

---

### Task 5: FastAPI gateway skeleton (`/healthz`, `/diagnostics`)

**Files:**
- Create: `gateway/__init__.py`
- Create: `gateway/app.py`
- Create: `gateway/healthcheck.py`
- Test: `gateway/tests/test_app.py`

**Interfaces:**
- Consumes: `run_diagnostics()` from Task 4.
- Produces: `app` (FastAPI instance) importable as `gateway.app:app` for `uvicorn`; `GET /healthz` (fast, no deep checks — used by Compose healthcheck); `GET /diagnostics` (full `run_diagnostics()` output as JSON — used by dashboard's Diagnostics panel in Phase 6 and by `promptwise doctor --remote` later).

- [ ] **Step 1: Write the failing test**

```python
# gateway/tests/test_app.py
from fastapi.testclient import TestClient

from gateway.app import app

client = TestClient(app)


def test_healthz_returns_ok():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_diagnostics_returns_check_list():
    response = client.get("/diagnostics")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    names = {item["name"] for item in body}
    assert "config.resolve" in names


def test_diagnostics_status_field_is_valid():
    response = client.get("/diagnostics")
    for item in response.json():
        assert item["status"] in ("PASS", "WARN", "FAIL")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest gateway/tests/test_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gateway'`

- [ ] **Step 3: Write `gateway/__init__.py`** (empty package marker)

```python
# gateway/__init__.py
```

- [ ] **Step 4: Write `gateway/healthcheck.py`**

```python
# gateway/healthcheck.py
"""Fast liveness check — backs docker-compose's healthcheck directive.
Deliberately shallow (<200ms budget): no deep dependency checks here.
Deep checks live in core.diagnostics.checks.run_diagnostics, exposed at /diagnostics.
"""


def is_alive() -> bool:
    return True
```

- [ ] **Step 5: Write `gateway/app.py`**

```python
# gateway/app.py
from fastapi import FastAPI

from core.diagnostics.checks import run_diagnostics
from gateway.healthcheck import is_alive

app = FastAPI(title="PromptWise Agentic OS Gateway", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok" if is_alive() else "down"}


@app.get("/diagnostics")
def diagnostics() -> list[dict[str, str]]:
    return [result.model_dump() for result in run_diagnostics()]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest gateway/tests/test_app.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git add gateway/__init__.py gateway/app.py gateway/healthcheck.py gateway/tests/test_app.py
git commit -m "feat: FastAPI gateway skeleton with /healthz and /diagnostics"
```

---

### Task 6: CLI — `promptwise doctor` and `promptwise profile`

**Files:**
- Create: `scripts/__init__.py`
- Create: `scripts/promptwise.py`
- Test: `scripts/tests/test_cli.py`

**Interfaces:**
- Consumes: `run_diagnostics()` (Task 4), `detect_hardware`/`write_hardware_profile` (Task 3).
- Produces: `promptwise doctor` (prints each check, exits 1 if any FAIL, 0 otherwise — including when only WARNs are present, per `docs/MAINTENANCE.md` §2); `promptwise profile` (writes `config/hardware_profile.yaml`).

- [ ] **Step 1: Write the failing test**

```python
# scripts/tests/test_cli.py
from typer.testing import CliRunner

from scripts.promptwise import app

runner = CliRunner()


def test_doctor_exits_zero_when_no_failures():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "config.resolve" in result.stdout
    assert "PASS" in result.stdout


def test_doctor_lists_every_check():
    result = runner.invoke(app, ["doctor"])
    for name in ("hardware.ram", "config.resolve", "packs.integrity", "services.ollama"):
        assert name in result.stdout


def test_profile_writes_hardware_yaml(tmp_path, monkeypatch):
    out_path = tmp_path / "config" / "hardware_profile.yaml"
    result = runner.invoke(app, ["profile", "--out", str(out_path)])
    assert result.exit_code == 0
    assert out_path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest scripts/tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts'`

- [ ] **Step 3: Write `scripts/__init__.py`** (empty package marker)

```python
# scripts/__init__.py
```

- [ ] **Step 4: Write `scripts/promptwise.py`**

```python
# scripts/promptwise.py
from pathlib import Path

import typer

from core.diagnostics.checks import run_diagnostics
from core.diagnostics.hardware import detect_hardware, write_hardware_profile

app = typer.Typer(help="PromptWise Agentic OS — operator CLI")

DEFAULT_PROFILE_PATH = Path("config/hardware_profile.yaml")


@app.command()
def doctor() -> None:
    """Run all health checks. Exit 0 unless any check FAILs."""
    results = run_diagnostics()
    has_failure = False
    for result in results:
        typer.echo(f"[{result.status}] {result.name} — {result.message}")
        if result.status == "FAIL":
            has_failure = True
    if has_failure:
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)


@app.command()
def profile(out: Path = DEFAULT_PROFILE_PATH) -> None:
    """Detect hardware and write hardware_profile.yaml."""
    detected = detect_hardware()
    write_hardware_profile(detected, out)
    typer.echo(f"wrote {out} — {detected.total_ram_gb}GB total RAM, {detected.cpu_count} CPUs, GPU={detected.has_gpu}")


if __name__ == "__main__":
    app()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest scripts/tests/test_cli.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add scripts/__init__.py scripts/promptwise.py scripts/tests/test_cli.py
git commit -m "feat: promptwise CLI (doctor, profile commands)"
```

---

### Task 7: Docker Compose bundle

**Files:**
- Create: `compose/docker-compose.yml`
- Create: `compose/gateway.Dockerfile`
- Create: `compose/.env.example`

**Interfaces:**
- Consumes: `gateway/app.py` (Task 5) as the image entrypoint.
- Produces: `docker compose up` starts `ollama`, `qdrant`, and `gateway` services; `gateway`'s healthcheck calls `/healthz`; ports are configurable via `.env`.

- [ ] **Step 1: Write `compose/gateway.Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY core ./core
COPY gateway ./gateway
COPY scripts ./scripts

RUN pip install --no-cache-dir -e .

EXPOSE 8000
CMD ["uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Write `compose/.env.example`**

Host-side gateway port defaults to `8420`, not `8000` — `8000`/`8080` collide
with common backend dev servers (Django, PHP built-in server, many Java
stacks), `3000`/`5000` collide with common frontend/Flask defaults. `8420` is
gateway-internal only (see Dockerfile/compose below, which still use `8000`
*inside* the container — only the host-facing mapping changes), avoids all
of the above, and is still trivially overridable per-deployment via `.env`.

```
GATEWAY_PORT=8420
OLLAMA_PORT=11434
QDRANT_PORT=6333
```

- [ ] **Step 3: Write `compose/docker-compose.yml`**

```yaml
name: promptwise-agentic-os

services:
  ollama:
    image: ollama/ollama:latest
    ports:
      - "${OLLAMA_PORT:-11434}:11434"
    volumes:
      - ollama_data:/root/.ollama

  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "${QDRANT_PORT:-6333}:6333"
    volumes:
      - qdrant_data:/qdrant/storage

  gateway:
    build:
      context: ..
      dockerfile: compose/gateway.Dockerfile
    ports:
      - "${GATEWAY_PORT:-8420}:8000"
    depends_on:
      - ollama
      - qdrant
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"]
      interval: 10s
      timeout: 3s
      retries: 5

volumes:
  ollama_data:
  qdrant_data:
```

- [ ] **Step 4: Verify the bundle builds and starts**

Run (from repo root): `docker compose -f compose/docker-compose.yml up --build -d`
Expected: three containers running; `docker compose -f compose/docker-compose.yml ps` shows `gateway` as `healthy` within ~30s.

- [ ] **Step 5: Verify the gateway is reachable**

Run: `curl http://localhost:8420/healthz`
Expected: `{"status":"ok"}`

- [ ] **Step 6: Tear down**

Run: `docker compose -f compose/docker-compose.yml down`

- [ ] **Step 7: Commit**

```bash
git add compose/docker-compose.yml compose/gateway.Dockerfile compose/.env.example
git commit -m "feat: docker compose bundle (ollama, qdrant, gateway)"
```

---

## Self-Review Notes (already applied above)

- **Spec coverage:** all 3 Phase-0 acceptance criteria from `docs/ROADMAP.md` are covered — Task 7 Step 4/5 prove `docker compose up` → gateway responds; Tasks 4+6 prove `promptwise doctor` runs and exits 0 on a clean install; Task 6 Step 4 proves `hardware_profile.yaml` is written.
- **Placeholder scan:** no TBD/TODO — the 4 stubbed checks (`services.ollama`, `services.qdrant`, `policy.load`, `audit.chain`) are real, tested, intentional WARN-not-FAIL behavior with an explicit phase reference, not placeholders.
- **Type consistency:** `CheckResult` (Task 4) is the single shape used by `run_diagnostics` (Task 4), `/diagnostics` (Task 5), and `promptwise doctor` (Task 6) — verified consistent across all three.

## Next plan after this one

Phase 1 — Hybrid router + Model Manager (`docs/ROADMAP.md` row 2): `route_request`, `catalog/model_catalog.yaml`, RAM-watchdog tier fallback, `cost_report`. Write that plan only after Phase 0's acceptance criteria are green.
