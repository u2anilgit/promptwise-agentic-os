# Phase 1 — Hybrid Router + Model Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship catalog-driven model routing (`route_request`), a RAM watchdog that falls back a tier instead of OOMing, privacy-forced local-only routing, and `cost_report` with a $/completed-task metric — the Phase 1 row from `docs/ROADMAP.md`. Opens by paying down two findings parked at the end of Phase 0 that this phase would otherwise silently build on top of: config auto-discovery was unreachable in practice, and `packs.integrity`/any future catalog path was hardcoded to the current working directory instead of resolved through config.

**Architecture:** `core/routing/` is a new, self-contained package: `models.py` (typed shapes), `catalog.py` (loads `catalog/model_catalog.yaml` through config, never a raw path), `router.py` (`route_request` — pure function, no I/O beyond what `detect_hardware`/`load_catalog` already do), `cost.py` (`cost_report` — pure function over a list of records, no persistence yet; Phase 4+ is where a durable store lands). The gateway exposes both as thin stateless HTTP wrappers, exactly like Phase 0's `/diagnostics` wrapped `run_diagnostics`. Every new core function still reads config only through `core/config/resolve.py`.

**Tech Stack:** Python 3.12, Pydantic v2, PyYAML, FastAPI, pytest — no new dependencies. No database yet (Phase 1 keeps cost tracking stateless/in-request; a durable ledger is a Phase 4+ concern once the memory layer's structured store exists).

**Spec:** `docs/ROADMAP.md` (Phase 1 row), `docs/ARCHITECTURE.md` §4 (config layering — the exact filenames/precedence this plan's Task 1 makes reachable), `docs/research/aug2026-findings.md` (Part 5 row 5 — router/budgets verbs: `route_request`, `set_budget_limit`, `cost_report`; `set_budget_limit` and prompt-cache planning are explicitly out of scope for this plan, tracked for a later Phase 1 follow-up plan if usage demands it before Phase 4).

## Global Constraints

- No domain-specific logic in `core/` or `gateway/` (root `CLAUDE.md` goal 1).
- Every core function reads config only through `core/config/resolve.py` (`ARCHITECTURE.md` §4) — never `open()` a config or catalog file elsewhere.
- Every core function is covered by a failing-test-first cycle (`superpowers:test-driven-development`).
- Zero cloud calls, zero paid services in tests — the cloud tiers in the catalog are metadata only (used for tier *selection* and *cost estimation*), Phase 1 never actually calls a cloud API (that's LiteLLM wiring, a later phase).
- `local_only: true` (the shipped default) or `privacy_sensitive=True` on a request must make cloud tiers structurally unreachable in `route_request` — not just deprioritized.
- Conventional Commits, no AI-attribution trailers.

---

### Task 1: Config auto-discovery + package the defaults file for real installs

**Files:**
- Modify: `core/config/resolve.py`
- Modify: `pyproject.toml`
- Modify: `core/diagnostics/checks.py`
- Test: `core/tests/config/test_resolve.py` (append)
- Test: `core/tests/diagnostics/test_checks.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `discover_config_paths(root: Path | None = None) -> tuple[Path, Path, Path]` (org, project, local — the conventional filenames from `ARCHITECTURE.md` §4); `resolve_config_auto(root: Path | None = None, env: Mapping[str, str] | None = None) -> dict` — the entry point every later task in this plan uses instead of calling `resolve_config()` with no arguments (which, as Phase 0's final review found, silently skips the org/project/local layers). `resolve_config()` itself is unchanged and stays the low-level primitive tests call directly.

- [ ] **Step 1: Write the failing tests**

```python
# core/tests/config/test_resolve.py — append to the existing file
from core.config.resolve import discover_config_paths, resolve_config_auto


def test_discover_config_paths_returns_conventional_locations(tmp_path):
    org, project, local = discover_config_paths(tmp_path)
    assert org == tmp_path / "promptwise.config.yaml"
    assert project == tmp_path / ".promptwise" / "config.yaml"
    assert local == tmp_path / ".promptwise" / "local.yaml"


def test_resolve_config_auto_finds_org_file(tmp_path):
    (tmp_path / "promptwise.config.yaml").write_text("engine:\n  local_only: false\n")
    cfg = resolve_config_auto(root=tmp_path, env={})
    assert cfg["engine"]["local_only"] is False
    assert cfg["engine"]["name"] == "promptwise-agentic-os"


def test_resolve_config_auto_finds_project_and_local_files(tmp_path):
    (tmp_path / ".promptwise").mkdir()
    (tmp_path / ".promptwise" / "config.yaml").write_text("routing:\n  default_tier: local-large\n")
    (tmp_path / ".promptwise" / "local.yaml").write_text("routing:\n  default_tier: cloud-cheap\n")
    cfg = resolve_config_auto(root=tmp_path, env={})
    assert cfg["routing"]["default_tier"] == "cloud-cheap"  # local overrides project


def test_resolve_config_auto_with_no_files_returns_defaults(tmp_path):
    cfg = resolve_config_auto(root=tmp_path, env={})
    assert cfg["engine"]["name"] == "promptwise-agentic-os"


def test_missing_system_defaults_raises(monkeypatch, tmp_path):
    import core.config.resolve as resolve_module

    fake_defaults = tmp_path / "does-not-exist.yaml"
    monkeypatch.setattr(resolve_module, "DEFAULTS_PATH", fake_defaults)
    with pytest.raises(FileNotFoundError):
        resolve_module.resolve_config()
```

Add `import pytest` to the top of `core/tests/config/test_resolve.py` if it is not already imported.

```python
# core/tests/diagnostics/test_checks.py — append
def test_config_resolve_check_reports_which_root_it_used(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.diagnostics.checks import run_diagnostics

    results = run_diagnostics()
    config_check = next(r for r in results if r.name == "config.resolve")
    assert config_check.status == "PASS"
    assert str(tmp_path) in config_check.message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest core/tests/config/test_resolve.py core/tests/diagnostics/test_checks.py -v`
Expected: FAIL — `ImportError: cannot import name 'discover_config_paths'` and the new `config.resolve` message test fails (message doesn't currently include the root path).

- [ ] **Step 3: Modify `core/config/resolve.py`**

Replace the top-level `_load_yaml` usage for the system-defaults layer with a strict loader, and add the two new functions. The full new file:

```python
# core/config/resolve.py
"""Layered config resolution — docs/ARCHITECTURE.md §4.

Precedence, later wins: system defaults < org config < project config <
user local overrides < environment variables. System defaults are the only
layer that is not optional — a missing defaults.yaml means the package
install itself is broken, so it raises instead of silently returning {}.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Mapping

import yaml

DEFAULTS_PATH = Path(__file__).parent / "defaults.yaml"
ENV_PREFIX = "PROMPTWISE_"

# Conventional on-disk locations, ARCHITECTURE.md §4 rows 2-4.
ORG_CONFIG_FILENAME = "promptwise.config.yaml"
PROJECT_CONFIG_RELPATH = Path(".promptwise") / "config.yaml"
LOCAL_CONFIG_RELPATH = Path(".promptwise") / "local.yaml"


def _load_defaults() -> dict[str, Any]:
    if not DEFAULTS_PATH.exists():
        raise FileNotFoundError(
            f"system defaults config missing at {DEFAULTS_PATH} — package installation is broken"
        )
    with DEFAULTS_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


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
    cfg = _load_defaults()
    for path in (org_path, project_path, local_path):
        cfg = _deep_merge(cfg, _load_yaml(path))
    cfg = _deep_merge(cfg, _env_overrides(env if env is not None else os.environ))
    return cfg


def discover_config_paths(root: Path | None = None) -> tuple[Path, Path, Path]:
    """Conventional org/project/local config locations under `root` (default cwd)."""
    root = root if root is not None else Path.cwd()
    return (
        root / ORG_CONFIG_FILENAME,
        root / PROJECT_CONFIG_RELPATH,
        root / LOCAL_CONFIG_RELPATH,
    )


def resolve_config_auto(
    root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """resolve_config(), but discovering org/project/local paths at their
    conventional locations instead of requiring the caller to pass them.
    This is the entry point every other core module should use — the
    explicit-path form of resolve_config() stays for tests and for callers
    that genuinely have a non-standard layout.
    """
    org_path, project_path, local_path = discover_config_paths(root)
    return resolve_config(org_path, project_path, local_path, env)
```

- [ ] **Step 4: Modify `pyproject.toml`** — package the config data files so a non-editable install (e.g. inside the Docker image) actually ships `defaults.yaml`

Add this section (anywhere after `[tool.setuptools.packages.find]`):

```toml
[tool.setuptools.package-data]
core = ["config/*.yaml"]
```

- [ ] **Step 5: Modify `core/diagnostics/checks.py`** — use `resolve_config_auto` everywhere this file currently calls the bare `resolve_config`, and report which root `_check_config_resolve` resolved from

Change the import line from `from core.config.resolve import resolve_config` to:

```python
from core.config.resolve import resolve_config_auto
```

Change `_check_config_resolve`:

```python
def _check_config_resolve() -> CheckResult:
    root = Path.cwd()
    try:
        cfg = resolve_config_auto(root=root)
        assert cfg["engine"]["name"]
    except Exception as exc:  # noqa: BLE001 — doctor must never crash on a bad config
        return CheckResult(name="config.resolve", status="FAIL", message=f"config failed to resolve: {exc}")
    return CheckResult(
        name="config.resolve",
        status="PASS",
        message=f"all config layers merged cleanly (org/project/local discovered under {root})",
    )
```

`_check_services_gateway` also currently calls the bare `resolve_config()` for the gateway port — change that one call from `resolve_config()` to `resolve_config_auto()` too (same function, no other change to that check in this task).

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest core/tests/config/test_resolve.py core/tests/diagnostics/test_checks.py -v`
Expected: PASS (all tests, including the 5 new ones)

- [ ] **Step 7: Run the full suite to confirm nothing else broke**

Run: `pytest -v`
Expected: PASS (all tests — this touches a function every other test file's `checks.py` import depends on)

- [ ] **Step 8: Commit**

```bash
git add core/config/resolve.py pyproject.toml core/diagnostics/checks.py core/tests/config/test_resolve.py core/tests/diagnostics/test_checks.py
git commit -m "feat: config auto-discovery (org/project/local) and package defaults.yaml for real installs"
```

---

### Task 2: Config-driven packs root + doctor test hardening

**Files:**
- Modify: `core/config/defaults.yaml`
- Modify: `core/diagnostics/checks.py`
- Modify: `compose/gateway.Dockerfile`
- Create: `packs/installed/.gitkeep`
- Test: `core/tests/diagnostics/test_checks.py` (append)
- Test: `scripts/tests/test_cli.py` (append)

**Interfaces:**
- Consumes: `resolve_config_auto()` (Task 1).
- Produces: `_check_packs_integrity(config: dict | None = None)` now resolves its directory from `config["paths"]["packs_installed"]` instead of a hardcoded CWD-relative constant — this is the shape Task 3's catalog loader (next task) copies for `paths.model_catalog`.

- [ ] **Step 1: Write the failing tests**

```python
# core/tests/diagnostics/test_checks.py — append
def test_packs_integrity_uses_configured_path(tmp_path, monkeypatch):
    from core.diagnostics.checks import _check_packs_integrity

    packs_dir = tmp_path / "custom_packs"
    packs_dir.mkdir()
    (packs_dir / "example-pack").mkdir()
    config = {"paths": {"packs_installed": str(packs_dir)}}
    result = _check_packs_integrity(config)
    assert result.status == "PASS"
    assert "1 packs" in result.message
```

(The FAIL-exit-path itself — `promptwise doctor` exiting 1 when any check fails — is exercised at the CLI layer below, where the behavior that actually matters to a user lives. A `checks.py`-level test that monkeypatches `run_diagnostics` and then calls the monkeypatched function would only prove the monkeypatch worked, not real logic — skip it.)

```python
# scripts/tests/test_cli.py — append
def test_doctor_exits_one_when_a_check_fails(monkeypatch):
    import scripts.promptwise as promptwise_module
    from core.diagnostics.models import CheckResult

    def _broken_diagnostics(config=None):
        return [CheckResult(name="hardware.ram", status="FAIL", message="simulated failure for test")]

    monkeypatch.setattr(promptwise_module.diagnostics_checks, "run_diagnostics", _broken_diagnostics)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "FAIL" in result.stdout
```

(This monkeypatches the `diagnostics_checks` module attribute, not a name imported into `scripts.promptwise` — which is exactly why Step 5 below changes the import from `from core.diagnostics.checks import run_diagnostics` to `import core.diagnostics.checks as diagnostics_checks`: a bare-name import copies a reference that monkeypatching the source module can't reach through the alias this test needs.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest core/tests/diagnostics/test_checks.py scripts/tests/test_cli.py -v`
Expected: FAIL — `_check_packs_integrity` doesn't accept a `config` argument yet; the doctor exit-1 test currently can't monkeypatch `run_diagnostics` inside `scripts.promptwise` because that module imports the function by name (this is expected — Step 4 fixes the import so it's patchable at the module level, which is also just better test hygiene).

- [ ] **Step 3: Modify `core/config/defaults.yaml`**

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
  hardware_profile_path: config/hardware_profile.yaml
gateway:
  port: 8000
paths:
  packs_installed: packs/installed
  model_catalog: catalog/model_catalog.yaml
```

- [ ] **Step 4: Modify `core/diagnostics/checks.py`**

Replace the `PACKS_INSTALLED_DIR` constant and `_check_packs_integrity` function:

```python
def _check_packs_integrity(config: dict | None = None) -> CheckResult:
    config = config if config is not None else resolve_config_auto()
    packs_dir = Path(config.get("paths", {}).get("packs_installed", "packs/installed"))
    if not packs_dir.exists():
        return CheckResult(name="packs.integrity", status="PASS", message="0 packs installed")
    pack_dirs = [p for p in packs_dir.iterdir() if p.is_dir()]
    # Phase 8 adds real manifest validation here; Phase 0/1 only counts.
    return CheckResult(name="packs.integrity", status="PASS", message=f"{len(pack_dirs)} packs installed")
```

Remove the now-unused `PACKS_INSTALLED_DIR = Path("packs/installed")` module constant. `_check_services_gateway` already exists from Phase 0's final-review fix wave (and Task 1 just switched its `resolve_config()` call to `resolve_config_auto()`) — thread `config` through it the same way as `_check_packs_integrity`, changing only its signature and the line that reads the port, not its PASS/WARN logic:

```python
def _check_services_gateway(config: dict | None = None) -> CheckResult:
    config = config if config is not None else resolve_config_auto()
    port = config.get("gateway", {}).get("port", 8000)
    url = f"http://127.0.0.1:{port}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=1) as response:  # noqa: S310 — local-only, fixed scheme
            if response.status == 200:
                return CheckResult(name="services.gateway", status="PASS", message=f"gateway reachable at 127.0.0.1:{port}")
            return CheckResult(
                name="services.gateway",
                status="WARN",
                message=f"gateway at 127.0.0.1:{port} returned status {response.status}",
            )
    except Exception:  # noqa: BLE001 — doctor must never crash; unreachable is a normal, valid state
        return CheckResult(
            name="services.gateway",
            status="WARN",
            message=f"gateway not reachable at 127.0.0.1:{port} — normal if not yet started",
        )
```

Update `run_diagnostics()` to resolve config once and thread it through both — keep the existing check order (`services.gateway` stays last, matching the file's current layout):

```python
def run_diagnostics(config: dict | None = None) -> list[CheckResult]:
    config = config if config is not None else resolve_config_auto()
    return [
        _check_hardware_ram(),
        _check_config_resolve(),
        _check_packs_integrity(config),
        _not_yet_implemented("services.ollama", "Phase 1"),
        _not_yet_implemented("services.qdrant", "Phase 4"),
        _not_yet_implemented("policy.load", "Phase 3"),
        _not_yet_implemented("audit.chain", "Phase 3"),
        _check_services_gateway(config),
    ]
```

- [ ] **Step 5: Modify `scripts/promptwise.py`** — import the module, not just the function, so tests can monkeypatch it

Change:

```python
from core.diagnostics.checks import run_diagnostics
```

to:

```python
import core.diagnostics.checks as diagnostics_checks
```

And update the one call site, inside `doctor()`, from `run_diagnostics()` to `diagnostics_checks.run_diagnostics()`. This is the standard "import the module, call through it" pattern that makes `monkeypatch.setattr(module, "function", fake)` actually intercept calls — importing the bare name copies a reference that monkeypatching the source module can't reach.

- [ ] **Step 6: Modify `compose/gateway.Dockerfile`** — ship an (empty) packs directory so the containerized `packs.integrity` check reports real state, not a directory that was never copied in

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY core ./core
COPY gateway ./gateway
COPY scripts ./scripts
COPY catalog ./catalog
COPY packs/installed ./packs/installed

RUN pip install --no-cache-dir -e .

EXPOSE 8000
CMD ["uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 7: Create `packs/installed/.gitkeep`** (empty file — makes the directory exist in git so `COPY packs/installed` above doesn't fail on a fresh clone)

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest core/tests/diagnostics/test_checks.py scripts/tests/test_cli.py -v`
Expected: PASS (all tests)

- [ ] **Step 9: Run the full suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add core/config/defaults.yaml core/diagnostics/checks.py scripts/promptwise.py compose/gateway.Dockerfile packs/installed/.gitkeep core/tests/diagnostics/test_checks.py scripts/tests/test_cli.py
git commit -m "fix: resolve packs/catalog roots through config instead of hardcoded CWD paths; harden doctor tests"
```

---

### Task 3: Model catalog — `catalog/model_catalog.yaml` and the loader

**Files:**
- Create: `catalog/model_catalog.yaml`
- Create: `core/routing/__init__.py`
- Create: `core/routing/models.py`
- Create: `core/routing/catalog.py`
- Test: `core/tests/routing/__init__.py`
- Test: `core/tests/routing/test_catalog.py`

**Interfaces:**
- Consumes: `resolve_config_auto()` (Task 1), `paths.model_catalog` config key (Task 2).
- Produces: `ModelTier` (Pydantic model), `TIER_ORDER: list[str]` (ascending cost/size — the order `route_request` walks), `load_catalog(config: dict | None = None) -> dict[str, ModelTier]`. Tasks 4 and 5 import all three from `core.routing.catalog` / `core.routing.models`.

- [ ] **Step 1: Write the failing test**

```python
# core/tests/routing/__init__.py
```

```python
# core/tests/routing/test_catalog.py
from core.routing.catalog import TIER_ORDER, load_catalog
from core.routing.models import ModelTier


def test_load_catalog_returns_a_model_tier_per_entry():
    catalog = load_catalog()
    assert set(catalog.keys()) == {"local-small", "local-large", "cloud-cheap", "cloud-premium"}
    for tier in catalog.values():
        assert isinstance(tier, ModelTier)


def test_local_tiers_are_free_and_not_cloud():
    catalog = load_catalog()
    for name in ("local-small", "local-large"):
        assert catalog[name].requires_cloud is False
        assert catalog[name].cost_per_1k_input_usd == 0.0
        assert catalog[name].cost_per_1k_output_usd == 0.0


def test_cloud_tiers_require_cloud_and_cost_money():
    catalog = load_catalog()
    for name in ("cloud-cheap", "cloud-premium"):
        assert catalog[name].requires_cloud is True
        assert catalog[name].cost_per_1k_input_usd > 0.0


def test_tier_order_matches_catalog_keys():
    catalog = load_catalog()
    assert set(TIER_ORDER) == set(catalog.keys())


def test_load_catalog_respects_configured_path(tmp_path):
    custom = tmp_path / "custom_catalog.yaml"
    custom.write_text(
        "tiers:\n"
        "  only-tier:\n"
        "    provider: ollama\n"
        "    model_id: test-model\n"
        "    min_ram_gb: 1.0\n"
        "    requires_cloud: false\n"
        "    cost_per_1k_input_usd: 0.0\n"
        "    cost_per_1k_output_usd: 0.0\n"
    )
    config = {"paths": {"model_catalog": str(custom)}}
    catalog = load_catalog(config)
    assert set(catalog.keys()) == {"only-tier"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/tests/routing/test_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.routing'`

- [ ] **Step 3: Write `catalog/model_catalog.yaml`**

```yaml
# catalog/model_catalog.yaml — Aug-2026 model refresh (docs/research/aug2026-findings.md)
# Ordered smallest/cheapest to largest/most expensive within each track;
# core/routing/catalog.py's TIER_ORDER walks these names in this order.
tiers:
  local-small:
    provider: ollama
    model_id: "llama3.2:3b"
    min_ram_gb: 4.0
    requires_cloud: false
    cost_per_1k_input_usd: 0.0
    cost_per_1k_output_usd: 0.0

  local-large:
    provider: ollama
    model_id: "qwen2.5:14b"
    min_ram_gb: 12.0
    requires_cloud: false
    cost_per_1k_input_usd: 0.0
    cost_per_1k_output_usd: 0.0

  cloud-cheap:
    provider: anthropic
    model_id: "claude-haiku-4-5"
    min_ram_gb: 0.0
    requires_cloud: true
    cost_per_1k_input_usd: 0.001
    cost_per_1k_output_usd: 0.005

  cloud-premium:
    provider: anthropic
    model_id: "claude-sonnet-5"
    min_ram_gb: 0.0
    requires_cloud: true
    cost_per_1k_input_usd: 0.003
    cost_per_1k_output_usd: 0.015
```

- [ ] **Step 4: Write `core/routing/__init__.py`** (empty package marker)

```python
# core/routing/__init__.py
```

- [ ] **Step 5: Write `core/routing/models.py`**

```python
# core/routing/models.py
from pydantic import BaseModel


class ModelTier(BaseModel):
    name: str
    provider: str
    model_id: str
    min_ram_gb: float
    requires_cloud: bool
    cost_per_1k_input_usd: float
    cost_per_1k_output_usd: float
```

- [ ] **Step 6: Write `core/routing/catalog.py`**

```python
# core/routing/catalog.py
"""Model catalog loader — docs/research/aug2026-findings.md Part 5 row 5.

Reads catalog/model_catalog.yaml through config (never a raw hardcoded
path), same pattern Task 2 established for packs/installed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from core.config.resolve import resolve_config_auto
from core.routing.models import ModelTier

# Ascending cost/size within each track (local, then cloud) — route_request
# walks this order to find the cheapest tier that fits.
TIER_ORDER: list[str] = ["local-small", "local-large", "cloud-cheap", "cloud-premium"]


def _catalog_path(config: dict[str, Any] | None) -> Path:
    config = config if config is not None else resolve_config_auto()
    rel = config.get("paths", {}).get("model_catalog", "catalog/model_catalog.yaml")
    return Path(rel)


def load_catalog(config: dict[str, Any] | None = None) -> dict[str, ModelTier]:
    path = _catalog_path(config)
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    tiers = raw.get("tiers", {})
    return {name: ModelTier(name=name, **fields) for name, fields in tiers.items()}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest core/tests/routing/test_catalog.py -v`
Expected: PASS (5 tests)

- [ ] **Step 8: Run the full suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add catalog/model_catalog.yaml core/routing/__init__.py core/routing/models.py core/routing/catalog.py core/tests/routing/__init__.py core/tests/routing/test_catalog.py
git commit -m "feat: model catalog (Aug-2026 tiers) and config-driven catalog loader"
```

---

### Task 4: `route_request` — tier selection, RAM watchdog, privacy-forced local routing

**Files:**
- Create: `core/routing/router.py`
- Test: `core/tests/routing/test_router.py`

**Interfaces:**
- Consumes: `ModelTier`, `TIER_ORDER`, `load_catalog` (Task 3); `HardwareProfile`, `detect_hardware` (Phase 0 Task 3); `resolve_config_auto` (Task 1).
- Produces: `RouteRequest` (Pydantic model: `task_type: str = "general"`, `privacy_sensitive: bool = False`, `preferred_tier: str | None = None`), `RoutingDecision` (Pydantic model: `tier: str`, `provider: str`, `model_id: str`, `reason: str`, `fallback_applied: bool`), `route_request(request: RouteRequest, hardware: HardwareProfile | None = None, config: dict | None = None, catalog: dict[str, ModelTier] | None = None) -> RoutingDecision`. Task 6's gateway `/route` endpoint calls this directly.

- [ ] **Step 1: Write the failing test**

```python
# core/tests/routing/test_router.py
import pytest

from core.diagnostics.hardware import HardwareProfile
from core.routing.catalog import load_catalog
from core.routing.router import RouteRequest, route_request


@pytest.fixture
def catalog():
    return load_catalog()


def test_default_request_picks_configured_default_tier(catalog):
    hw = HardwareProfile(total_ram_gb=16.0, available_ram_gb=16.0, cpu_count=8, has_gpu=False)
    config = {"engine": {"local_only": True}, "routing": {"default_tier": "local-small"}}
    decision = route_request(RouteRequest(), hardware=hw, config=config, catalog=catalog)
    assert decision.tier == "local-small"
    assert decision.provider == "ollama"
    assert decision.fallback_applied is False


def test_preferred_tier_is_honored_when_it_fits(catalog):
    hw = HardwareProfile(total_ram_gb=16.0, available_ram_gb=16.0, cpu_count=8, has_gpu=False)
    config = {"engine": {"local_only": True}, "routing": {"default_tier": "local-small"}}
    decision = route_request(
        RouteRequest(preferred_tier="local-large"), hardware=hw, config=config, catalog=catalog
    )
    assert decision.tier == "local-large"
    assert decision.fallback_applied is False


def test_ram_watchdog_falls_back_a_tier_when_preferred_does_not_fit(catalog):
    hw = HardwareProfile(total_ram_gb=8.0, available_ram_gb=6.0, cpu_count=4, has_gpu=False)
    config = {"engine": {"local_only": True}, "routing": {"default_tier": "local-small"}}
    decision = route_request(
        RouteRequest(preferred_tier="local-large"), hardware=hw, config=config, catalog=catalog
    )
    assert decision.tier == "local-small"  # local-large needs 12GB, only 6GB available
    assert decision.fallback_applied is True
    assert "watchdog" in decision.reason.lower()


def test_ram_watchdog_never_crashes_when_nothing_fits(catalog):
    hw = HardwareProfile(total_ram_gb=2.0, available_ram_gb=1.0, cpu_count=2, has_gpu=False)
    config = {"engine": {"local_only": True}, "routing": {"default_tier": "local-small"}}
    decision = route_request(RouteRequest(), hardware=hw, config=config, catalog=catalog)
    assert decision.tier == "local-small"  # smallest eligible tier, used anyway
    assert decision.fallback_applied is True


def test_privacy_sensitive_request_never_selects_a_cloud_tier(catalog):
    hw = HardwareProfile(total_ram_gb=64.0, available_ram_gb=60.0, cpu_count=16, has_gpu=True)
    # local_only False at the config level — only the per-request flag should force local
    config = {"engine": {"local_only": False}, "routing": {"default_tier": "local-small"}}
    decision = route_request(
        RouteRequest(privacy_sensitive=True, preferred_tier="cloud-premium"),
        hardware=hw,
        config=config,
        catalog=catalog,
    )
    assert decision.tier in ("local-small", "local-large")
    assert decision.provider == "ollama"


def test_local_only_config_forces_local_even_without_privacy_flag(catalog):
    hw = HardwareProfile(total_ram_gb=64.0, available_ram_gb=60.0, cpu_count=16, has_gpu=True)
    config = {"engine": {"local_only": True}, "routing": {"default_tier": "local-small"}}
    decision = route_request(
        RouteRequest(preferred_tier="cloud-premium"), hardware=hw, config=config, catalog=catalog
    )
    assert decision.provider == "ollama"


def test_non_local_only_config_can_select_a_cloud_tier(catalog):
    hw = HardwareProfile(total_ram_gb=4.0, available_ram_gb=2.0, cpu_count=2, has_gpu=False)
    config = {"engine": {"local_only": False}, "routing": {"default_tier": "local-small"}}
    decision = route_request(
        RouteRequest(preferred_tier="cloud-cheap"), hardware=hw, config=config, catalog=catalog
    )
    assert decision.tier == "cloud-cheap"
    assert decision.provider == "anthropic"


def test_unknown_preferred_tier_falls_back_to_default_instead_of_crashing(catalog):
    hw = HardwareProfile(total_ram_gb=16.0, available_ram_gb=16.0, cpu_count=8, has_gpu=False)
    config = {"engine": {"local_only": True}, "routing": {"default_tier": "local-small"}}
    decision = route_request(
        RouteRequest(preferred_tier="does-not-exist"), hardware=hw, config=config, catalog=catalog
    )
    assert decision.tier == "local-small"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/tests/routing/test_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.routing.router'`

- [ ] **Step 3: Write `core/routing/router.py`**

```python
# core/routing/router.py
"""route_request — docs/research/aug2026-findings.md Part 5 row 5.

Pure selection logic: given a request, the machine's hardware, config, and
the model catalog, pick the cheapest/smallest tier that satisfies both the
privacy constraint and the RAM budget, falling back gracefully — never
raising — when the preferred tier doesn't fit or doesn't exist.
"""
from __future__ import annotations

from pydantic import BaseModel

from core.config.resolve import resolve_config_auto
from core.diagnostics.hardware import HardwareProfile, detect_hardware
from core.routing.catalog import TIER_ORDER, load_catalog
from core.routing.models import ModelTier


class RouteRequest(BaseModel):
    task_type: str = "general"
    privacy_sensitive: bool = False
    preferred_tier: str | None = None


class RoutingDecision(BaseModel):
    tier: str
    provider: str
    model_id: str
    reason: str
    fallback_applied: bool


def _eligible_tiers(catalog: dict[str, ModelTier], local_only: bool) -> list[str]:
    ordered = [name for name in TIER_ORDER if name in catalog]
    if local_only:
        ordered = [name for name in ordered if not catalog[name].requires_cloud]
    return ordered


def route_request(
    request: RouteRequest,
    hardware: HardwareProfile | None = None,
    config: dict | None = None,
    catalog: dict[str, ModelTier] | None = None,
) -> RoutingDecision:
    config = config if config is not None else resolve_config_auto()
    hardware = hardware if hardware is not None else detect_hardware()
    catalog = catalog if catalog is not None else load_catalog(config)

    local_only = bool(config.get("engine", {}).get("local_only", True)) or request.privacy_sensitive
    eligible = _eligible_tiers(catalog, local_only)
    if not eligible:
        raise ValueError("no eligible tiers in catalog for this request — check catalog and local_only/privacy settings")

    default_tier = config.get("routing", {}).get("default_tier")
    if request.preferred_tier and request.preferred_tier in eligible:
        target = request.preferred_tier
        reason = f"selected {target} (explicitly preferred)"
    elif default_tier and default_tier in eligible:
        target = default_tier
        reason = f"selected {target} (configured default tier)"
    else:
        target = eligible[0]
        reason = f"selected {target} (smallest eligible tier)"

    fallback_applied = False
    if catalog[target].min_ram_gb > hardware.available_ram_gb:
        fitting = [name for name in eligible if catalog[name].min_ram_gb <= hardware.available_ram_gb]
        if fitting:
            target = fitting[0]
            fallback_applied = True
            reason = (
                f"RAM watchdog: preferred/default tier needed more RAM than the "
                f"{hardware.available_ram_gb}GB available — fell back to {target}"
            )
        else:
            target = eligible[0]
            fallback_applied = True
            reason = (
                f"RAM watchdog: no eligible tier fits {hardware.available_ram_gb}GB available — "
                f"using smallest eligible tier {target} anyway, expect degraded performance"
            )

    tier_obj = catalog[target]
    return RoutingDecision(
        tier=target,
        provider=tier_obj.provider,
        model_id=tier_obj.model_id,
        reason=reason,
        fallback_applied=fallback_applied,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest core/tests/routing/test_router.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/routing/router.py core/tests/routing/test_router.py
git commit -m "feat: route_request with RAM watchdog and privacy-forced local routing"
```

---

### Task 5: `cost_report` — $/completed-task metric

**Files:**
- Create: `core/routing/cost.py`
- Test: `core/tests/routing/test_cost.py`

**Interfaces:**
- Consumes: `ModelTier` (Task 3).
- Produces: `CostRecord` (Pydantic model: `tier: str`, `tokens_in: int`, `tokens_out: int`), `record_cost(record: CostRecord, tier_obj: ModelTier) -> float`, `cost_report(records: list[CostRecord], catalog: dict[str, ModelTier]) -> dict`. Task 6's gateway `/cost-report` endpoint calls `cost_report` directly.

- [ ] **Step 1: Write the failing test**

```python
# core/tests/routing/test_cost.py
from core.routing.catalog import load_catalog
from core.routing.cost import CostRecord, cost_report, record_cost


def test_record_cost_is_zero_for_local_tiers():
    catalog = load_catalog()
    record = CostRecord(tier="local-small", tokens_in=10_000, tokens_out=5_000)
    assert record_cost(record, catalog["local-small"]) == 0.0


def test_record_cost_computes_from_per_1k_rates():
    catalog = load_catalog()
    tier = catalog["cloud-cheap"]
    record = CostRecord(tier="cloud-cheap", tokens_in=2_000, tokens_out=1_000)
    expected = (2_000 / 1000) * tier.cost_per_1k_input_usd + (1_000 / 1000) * tier.cost_per_1k_output_usd
    assert record_cost(record, tier) == expected


def test_cost_report_computes_total_and_per_task_average():
    catalog = load_catalog()
    records = [
        CostRecord(tier="local-small", tokens_in=1_000, tokens_out=500),
        CostRecord(tier="cloud-cheap", tokens_in=1_000, tokens_out=500),
    ]
    report = cost_report(records, catalog)
    expected_total = record_cost(records[0], catalog["local-small"]) + record_cost(records[1], catalog["cloud-cheap"])
    assert report["completed_tasks"] == 2
    assert report["total_cost_usd"] == round(expected_total, 6)
    assert report["cost_per_completed_task_usd"] == round(expected_total / 2, 6)


def test_cost_report_breaks_down_by_tier():
    catalog = load_catalog()
    records = [
        CostRecord(tier="local-small", tokens_in=1_000, tokens_out=500),
        CostRecord(tier="local-small", tokens_in=2_000, tokens_out=1_000),
        CostRecord(tier="cloud-cheap", tokens_in=1_000, tokens_out=500),
    ]
    report = cost_report(records, catalog)
    assert report["by_tier"]["local-small"]["tasks"] == 2
    assert report["by_tier"]["cloud-cheap"]["tasks"] == 1


def test_cost_report_handles_zero_records_without_crashing():
    catalog = load_catalog()
    report = cost_report([], catalog)
    assert report["completed_tasks"] == 0
    assert report["total_cost_usd"] == 0.0
    assert report["cost_per_completed_task_usd"] == 0.0
    assert report["by_tier"] == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/tests/routing/test_cost.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.routing.cost'`

- [ ] **Step 3: Write `core/routing/cost.py`**

```python
# core/routing/cost.py
"""cost_report — docs/research/aug2026-findings.md Part 5 row 5, the
$/completed-task metric. Stateless: takes the records to report over as an
argument. A durable ledger (persisting records across requests) is a later
phase's concern once the structured store exists — Phase 1 proves the
metric works, Phase 4+ makes it durable.
"""
from __future__ import annotations

from pydantic import BaseModel

from core.routing.models import ModelTier


class CostRecord(BaseModel):
    tier: str
    tokens_in: int
    tokens_out: int


def record_cost(record: CostRecord, tier_obj: ModelTier) -> float:
    return (record.tokens_in / 1000) * tier_obj.cost_per_1k_input_usd + (
        record.tokens_out / 1000
    ) * tier_obj.cost_per_1k_output_usd


def cost_report(records: list[CostRecord], catalog: dict[str, ModelTier]) -> dict:
    total_cost = 0.0
    by_tier: dict[str, dict] = {}
    for record in records:
        tier_obj = catalog[record.tier]
        cost = record_cost(record, tier_obj)
        total_cost += cost
        entry = by_tier.setdefault(record.tier, {"tasks": 0, "cost_usd": 0.0})
        entry["tasks"] += 1
        entry["cost_usd"] += cost

    completed_tasks = len(records)
    cost_per_task = (total_cost / completed_tasks) if completed_tasks else 0.0

    return {
        "total_cost_usd": round(total_cost, 6),
        "completed_tasks": completed_tasks,
        "cost_per_completed_task_usd": round(cost_per_task, 6),
        "by_tier": {
            name: {"tasks": entry["tasks"], "cost_usd": round(entry["cost_usd"], 6)}
            for name, entry in by_tier.items()
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest core/tests/routing/test_cost.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/routing/cost.py core/tests/routing/test_cost.py
git commit -m "feat: cost_report with dollar-per-completed-task metric"
```

---

### Task 6: Gateway wiring — `POST /route`, `POST /cost-report`

**Files:**
- Modify: `gateway/app.py`
- Test: `gateway/tests/test_app.py` (append)

**Interfaces:**
- Consumes: `RouteRequest`, `RoutingDecision`, `route_request` (Task 4); `CostRecord`, `cost_report` (Task 5); `load_catalog` (Task 3).
- Produces: `POST /route` (body: `RouteRequest` JSON, returns: `RoutingDecision` JSON); `POST /cost-report` (body: JSON list of `CostRecord`, returns: the `cost_report` dict as JSON). Both stateless — no request is persisted; the caller (dashboard in Phase 6, or a script today) accumulates records and posts the whole list each time it wants a report.

- [ ] **Step 1: Write the failing test**

```python
# gateway/tests/test_app.py — append
def test_route_endpoint_returns_a_decision():
    response = client.post("/route", json={"privacy_sensitive": True})
    assert response.status_code == 200
    body = response.json()
    assert body["tier"] in ("local-small", "local-large")
    assert "reason" in body


def test_route_endpoint_uses_default_request_body():
    response = client.post("/route", json={})
    assert response.status_code == 200
    assert response.json()["tier"] in ("local-small", "local-large", "cloud-cheap", "cloud-premium")


def test_cost_report_endpoint_computes_totals():
    response = client.post(
        "/cost-report",
        json=[
            {"tier": "local-small", "tokens_in": 1000, "tokens_out": 500},
            {"tier": "local-small", "tokens_in": 500, "tokens_out": 250},
        ],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["completed_tasks"] == 2
    assert body["total_cost_usd"] == 0.0


def test_cost_report_endpoint_with_no_records():
    response = client.post("/cost-report", json=[])
    assert response.status_code == 200
    assert response.json()["completed_tasks"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest gateway/tests/test_app.py -v`
Expected: FAIL with `404` responses for `/route` and `/cost-report` (routes don't exist yet)

- [ ] **Step 3: Modify `gateway/app.py`**

This file already has a `lifespan` hook (from Phase 0's final-review fix wave) that writes the hardware profile on boot via `resolve_config()`. Task 1 of this plan introduced `resolve_config_auto()` as the entry point every module should use instead of the bare `resolve_config()` — switch the lifespan hook to it while you're in this file, and add the two new routes. Full new file:

```python
# gateway/app.py
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from core.config.resolve import resolve_config_auto
from core.diagnostics.checks import run_diagnostics
from core.diagnostics.hardware import detect_hardware, write_hardware_profile
from core.routing.catalog import load_catalog
from core.routing.cost import CostRecord, cost_report
from core.routing.router import RouteRequest, RoutingDecision, route_request
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
    return cost_report(records, catalog)
```

This is a straight superset of the file's current content (verify against what's on disk before overwriting — only the `resolve_config` → `resolve_config_auto` swap and the two new routes/imports should differ).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest gateway/tests/test_app.py -v`
Expected: PASS (all tests, including the 4 new ones)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add gateway/app.py gateway/tests/test_app.py
git commit -m "feat: gateway /route and /cost-report endpoints"
```

---

## Self-Review Notes (already applied above)

- **Spec coverage:** ROADMAP Phase 1's four acceptance criteria are covered — Task 4 proves `route_request` picks the correct tier per catalog (Task 3) and includes a RAM-watchdog fallback test; Task 4's privacy tests prove privacy-forced local routing; Task 5 proves `cost_report` computes $/completed-task. `set_budget_limit` (mentioned alongside `route_request`/`cost_report` in the research doc's verb list) and prompt-cache planning are explicitly deferred — noted in the Spec line above, not silently dropped.
- **Placeholder scan:** no TBD/TODO. Task 6's `lifespan` note is an explicit instruction to check existing file state before writing, not a placeholder — Phase 0's final-review fix wave already added a `lifespan` hook to `gateway/app.py`, so Task 6's implementer must read that file first and merge rather than overwrite.
- **Type consistency:** `ModelTier` (Task 3) is the single shape used by `catalog.py`, `router.py`, and `cost.py`. `RouteRequest`/`RoutingDecision` (Task 4) are the shapes both the direct tests and Task 6's `/route` endpoint use, unchanged. `CostRecord` (Task 5) is what both `test_cost.py` and Task 6's `/cost-report` endpoint pass around.
- **Parked-findings coverage:** this plan's Task 1 closes Phase 0's parked findings #3 (config discovery unreachable) and (partially) #2 (defaults.yaml packaging); Task 2 closes #4 (packs.integrity CWD-relative false-PASS) and #9 (doctor's FAIL path and hardware.ram were untested/tautological). Phase 0's parked finding #10 (local dev interpreter is 3.11, `pip install -e .` never verified outside Docker) is an environment issue, not a code defect — no task here addresses it; if it blocks local iteration on this plan, install Python 3.12 or run tests inside the gateway container.

## Next plan after this one

Phase 2 — Verification Gate (`docs/ROADMAP.md` row 3): `verify_output` blocking a deliberately-broken diff, Semgrep/Gitleaks wiring, failure ledger. Write that plan only after Phase 1's acceptance criteria are green.
