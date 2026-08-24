# Pack Loader Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pack manifest schema, validator, and install/list/remove mechanism (`docs/ARCHITECTURE.md` §3) — the only piece of the repo-intelligence / methodology-packs design that has zero unbuilt core-verb dependencies today.

**Architecture:** A new `core/packs/` module (semver range parsing, Pydantic v2 manifest model, stateless loader/validator, install/list/remove operations reading/writing `packs/registry/` and `packs/installed/`) plus `promptwise pack install/list/remove` CLI commands and a real `packs.integrity` doctor check. No filesystem watcher — every call re-scans disk, which satisfies "hot-discoverable, no core restart" without extra machinery (YAGNI). Capability *enforcement* via `check_policy` is explicitly out of scope (Phase 3 doesn't exist yet); this plan only parses and stores the declared `capabilities` list.

**Tech Stack:** Python 3.12, Pydantic v2, PyYAML, Typer (matches existing `core/config`, `core/diagnostics`, `scripts/promptwise.py` conventions — no new dependencies).

**Spec:** `docs/superpowers/specs/2026-08-24-repo-intelligence-methodology-packs-design.md` (this plan implements only the pack-loader-foundation slice of that spec; repo-intelligence pack content and BMAD/DMAIC methodology packs are deferred until Phases 3–5 land, per that spec's phasing decision).

## Global Constraints

- Zero new dependencies — semver-range parsing is hand-rolled (no `semver`/`packaging` package), matching `pyproject.toml`'s current minimal dependency set.
- Pydantic v2 models for the manifest contract (`core/CLAUDE.md` convention — breaking this schema is a semver-major event).
- No verb reads a config file directly — `paths.packs_installed` resolution always goes through `core/config/resolve.py`'s `resolve_path`.
- Doctor checks must never crash — invalid input is reported as `WARN`/`FAIL`, never an unhandled exception (matches `core/diagnostics/checks.py`'s existing `noqa: BLE001` pattern).
- Pack `kind` enum: `stack | database | cloud-devops | architecture | migration | lifecycle | intelligence` — the `intelligence` value is new this plan (`docs/ARCHITECTURE.md` §3).
- Pack names must be safe filesystem slugs (`^[a-z0-9][a-z0-9-]*$`) — rejected before any path is built from them, closing a path-traversal risk (`packs/installed/../../etc` style names).
- TDD throughout: failing test in `core/tests/packs/` (or `scripts/tests/`) before implementation, per every existing module in this repo.

---

### Task 1: Semver range parsing

**Files:**
- Create: `core/packs/__init__.py` (empty)
- Create: `core/packs/semver.py`
- Test: `core/tests/packs/__init__.py` (empty)
- Test: `core/tests/packs/test_semver.py`

**Interfaces:**
- Produces: `parse_version(v: str) -> tuple[int, int, int]`, `satisfies(version: str, requires_range: str) -> bool`, `InvalidVersionError(ValueError)` — used by Task 2's loader.

- [ ] **Step 1: Write the failing tests**

```python
# core/tests/packs/test_semver.py
import pytest
from core.packs.semver import parse_version, satisfies, InvalidVersionError


def test_parse_version_valid():
    assert parse_version("0.4.2") == (0, 4, 2)


def test_parse_version_rejects_garbage():
    with pytest.raises(InvalidVersionError):
        parse_version("not-a-version")


def test_parse_version_rejects_two_part():
    with pytest.raises(InvalidVersionError):
        parse_version("1.2")


def test_satisfies_within_range():
    assert satisfies("0.4.2", ">=0.4.0,<0.5.0") is True


def test_satisfies_below_range():
    assert satisfies("0.3.9", ">=0.4.0,<0.5.0") is False


def test_satisfies_at_upper_bound_is_exclusive():
    assert satisfies("0.5.0", ">=0.4.0,<0.5.0") is False


def test_satisfies_single_clause():
    assert satisfies("1.0.0", ">=1.0.0") is True


def test_satisfies_rejects_malformed_clause():
    with pytest.raises(InvalidVersionError):
        satisfies("1.0.0", "~1.0.0")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest core/tests/packs/test_semver.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.packs'`

- [ ] **Step 3: Create the empty package init files**

```python
# core/packs/__init__.py
```

```python
# core/tests/packs/__init__.py
```

- [ ] **Step 4: Write the implementation**

```python
# core/packs/semver.py
"""Minimal semver + range parsing for pack.yaml `requires_core`
(docs/ARCHITECTURE.md §3). No external dependency — we only need to parse
plain X.Y.Z versions and comma-separated two-sided ranges like
">=0.4.0,<0.5.0", matching the exact syntax used in pack.yaml examples
throughout ARCHITECTURE.md and the pack-loader-foundation spec.
"""
from __future__ import annotations

import re

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_CLAUSE_RE = re.compile(r"^(>=|<=|>|<|==)(.+)$")


class InvalidVersionError(ValueError):
    """Raised for a malformed version string or requires_core clause."""


def parse_version(v: str) -> tuple[int, int, int]:
    match = _VERSION_RE.match(v.strip())
    if not match:
        raise InvalidVersionError(f"{v!r} is not a valid X.Y.Z version")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _compare(a: tuple[int, int, int], op: str, b: tuple[int, int, int]) -> bool:
    if op == ">=":
        return a >= b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    if op == "<":
        return a < b
    if op == "==":
        return a == b
    raise InvalidVersionError(f"unsupported operator {op!r}")  # unreachable: _CLAUSE_RE constrains op


def satisfies(version: str, requires_range: str) -> bool:
    """e.g. satisfies("0.4.2", ">=0.4.0,<0.5.0") -> True"""
    target = parse_version(version)
    for raw_clause in requires_range.split(","):
        clause = raw_clause.strip()
        match = _CLAUSE_RE.match(clause)
        if not match:
            raise InvalidVersionError(f"{clause!r} in requires_core range is not a valid clause")
        op, bound = match.group(1), match.group(2)
        if not _compare(target, op, parse_version(bound)):
            return False
    return True
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest core/tests/packs/test_semver.py -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Commit**

```bash
git add core/packs/__init__.py core/packs/semver.py core/tests/packs/__init__.py core/tests/packs/test_semver.py
git commit -m "feat(packs): add hand-rolled semver range parsing for requires_core"
```

---

### Task 2: Pack manifest model + safe-name validation

**Files:**
- Create: `core/packs/models.py`
- Test: `core/tests/packs/test_models.py`

**Interfaces:**
- Consumes: nothing (leaf module).
- Produces: `PackKind` (`Literal["stack", "database", "cloud-devops", "architecture", "migration", "lifecycle", "intelligence"]`), `PACK_NAME_RE` (compiled regex), `PackManifest(BaseModel)` with fields `name: str`, `version: str`, `kind: PackKind`, `summary: str`, `requires_core: str`, `capabilities: list[str] = []`, `permissions_rationale: str`, `dependencies: list[str] = []` — used by Task 3's loader and Task 4's registry.

- [ ] **Step 1: Write the failing tests**

```python
# core/tests/packs/test_models.py
import pytest
from pydantic import ValidationError
from core.packs.models import PackManifest


def _valid_kwargs(**overrides):
    base = dict(
        name="repo-intelligence",
        version="1.0.0",
        kind="intelligence",
        summary="Reverse-engineers an existing repo into docs",
        requires_core=">=0.4.0,<0.5.0",
        capabilities=["fs:read", "fs:write:docs/reverse-engineered/**"],
        permissions_rationale="Needs fs:write only to write generated docs under docs/reverse-engineered/.",
        dependencies=[],
    )
    base.update(overrides)
    return base


def test_valid_manifest_parses():
    manifest = PackManifest(**_valid_kwargs())
    assert manifest.kind == "intelligence"
    assert manifest.capabilities == ["fs:read", "fs:write:docs/reverse-engineered/**"]


def test_all_kind_values_accepted():
    for kind in ("stack", "database", "cloud-devops", "architecture", "migration", "lifecycle", "intelligence"):
        manifest = PackManifest(**_valid_kwargs(kind=kind))
        assert manifest.kind == kind


def test_unknown_kind_rejected():
    with pytest.raises(ValidationError):
        PackManifest(**_valid_kwargs(kind="not-a-real-kind"))


def test_name_must_be_safe_slug():
    with pytest.raises(ValidationError):
        PackManifest(**_valid_kwargs(name="../../etc/passwd"))


def test_name_rejects_uppercase_and_spaces():
    with pytest.raises(ValidationError):
        PackManifest(**_valid_kwargs(name="Repo Intelligence"))


def test_name_allows_hyphens_and_digits():
    manifest = PackManifest(**_valid_kwargs(name="stack-python3-fastapi"))
    assert manifest.name == "stack-python3-fastapi"


def test_permissions_rationale_must_not_be_blank():
    with pytest.raises(ValidationError):
        PackManifest(**_valid_kwargs(permissions_rationale="   "))


def test_capabilities_and_dependencies_default_empty():
    kwargs = _valid_kwargs()
    del kwargs["capabilities"]
    del kwargs["dependencies"]
    manifest = PackManifest(**kwargs)
    assert manifest.capabilities == []
    assert manifest.dependencies == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest core/tests/packs/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.packs.models'`

- [ ] **Step 3: Write the implementation**

```python
# core/packs/models.py
"""Pack manifest schema — docs/ARCHITECTURE.md §3 "pack.yaml (required
fields)". This is the typed contract every pack.yaml is validated against;
breaking it is a semver-major event (core/CLAUDE.md conventions).
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, field_validator

PackKind = Literal[
    "stack",
    "database",
    "cloud-devops",
    "architecture",
    "migration",
    "lifecycle",
    "intelligence",
]

# Pack names become directory names under packs/installed/<name> — must be a
# safe slug so a malicious or malformed name can never escape that directory
# (e.g. "../../etc") when registry.py builds filesystem paths from it.
PACK_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class PackManifest(BaseModel):
    name: str
    version: str
    kind: PackKind
    summary: str
    requires_core: str
    capabilities: list[str] = []
    permissions_rationale: str
    dependencies: list[str] = []

    @field_validator("name")
    @classmethod
    def _name_is_safe_slug(cls, v: str) -> str:
        if not PACK_NAME_RE.match(v):
            raise ValueError(
                f"pack name {v!r} must be a lowercase slug matching {PACK_NAME_RE.pattern} "
                "(letters, digits, hyphens only, starting with a letter or digit)"
            )
        return v

    @field_validator("permissions_rationale")
    @classmethod
    def _rationale_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("permissions_rationale must not be blank — ARCHITECTURE.md §3 requires it")
        return v
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest core/tests/packs/test_models.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add core/packs/models.py core/tests/packs/test_models.py
git commit -m "feat(packs): add PackManifest schema with safe-slug name validation"
```

---

### Task 3: Manifest loader (parse pack.yaml + validate against running core)

**Files:**
- Create: `core/packs/loader.py`
- Test: `core/tests/packs/test_loader.py`

**Interfaces:**
- Consumes: `core.packs.models.PackManifest`, `core.packs.semver.satisfies`, `core.packs.semver.InvalidVersionError`, `core.__version__`.
- Produces: `PackValidationError(ValueError)`, `load_pack_manifest(pack_dir: Path, core_version: str | None = None) -> PackManifest` — used by Task 4's registry and Task 5's doctor check.

- [ ] **Step 1: Write the failing tests**

```python
# core/tests/packs/test_loader.py
import pytest
from core.packs.loader import load_pack_manifest, PackValidationError

VALID_YAML = """\
name: repo-intelligence
version: 1.0.0
kind: intelligence
summary: Reverse-engineers an existing repo into docs
requires_core: ">=0.1.0,<0.2.0"
capabilities:
  - fs:read
permissions_rationale: Needs fs:read to scan the target repo.
dependencies: []
"""


def _write_manifest(tmp_path, contents, dirname="a-pack"):
    pack_dir = tmp_path / dirname
    pack_dir.mkdir()
    (pack_dir / "pack.yaml").write_text(contents, encoding="utf-8")
    return pack_dir


def test_load_valid_manifest(tmp_path):
    pack_dir = _write_manifest(tmp_path, VALID_YAML)
    manifest = load_pack_manifest(pack_dir, core_version="0.1.0")
    assert manifest.name == "repo-intelligence"
    assert manifest.kind == "intelligence"


def test_missing_pack_yaml_raises(tmp_path):
    pack_dir = tmp_path / "empty-pack"
    pack_dir.mkdir()
    with pytest.raises(PackValidationError, match="no pack.yaml"):
        load_pack_manifest(pack_dir, core_version="0.1.0")


def test_malformed_schema_raises(tmp_path):
    pack_dir = _write_manifest(tmp_path, "name: only-a-name\n", dirname="broken-pack")
    with pytest.raises(PackValidationError, match="failed schema validation"):
        load_pack_manifest(pack_dir, core_version="0.1.0")


def test_requires_core_out_of_range_raises(tmp_path):
    pack_dir = _write_manifest(tmp_path, VALID_YAML)
    with pytest.raises(PackValidationError, match="requires_core"):
        load_pack_manifest(pack_dir, core_version="0.9.0")


def test_invalid_requires_core_clause_raises(tmp_path):
    bad_yaml = VALID_YAML.replace('">=0.1.0,<0.2.0"', '"~0.1.0"')
    pack_dir = _write_manifest(tmp_path, bad_yaml, dirname="bad-range-pack")
    with pytest.raises(PackValidationError, match="requires_core"):
        load_pack_manifest(pack_dir, core_version="0.1.0")


def test_defaults_to_running_core_version(tmp_path, monkeypatch):
    import core
    monkeypatch.setattr(core, "__version__", "0.1.0")
    pack_dir = _write_manifest(tmp_path, VALID_YAML)
    manifest = load_pack_manifest(pack_dir)  # no core_version passed
    assert manifest.name == "repo-intelligence"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest core/tests/packs/test_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.packs.loader'`

- [ ] **Step 3: Write the implementation**

```python
# core/packs/loader.py
"""Pack manifest loading + validation — docs/ARCHITECTURE.md §3, step 2 of
the install/discovery mechanism ("validates pack.yaml against the manifest
schema, checks requires_core semver range").

Capability *enforcement* (registering with check_policy) is explicit Phase 3
scope and does NOT happen here — this module only parses and validates the
declared capabilities list. See PackManifest.capabilities.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

import core
from core.packs.models import PackManifest
from core.packs.semver import InvalidVersionError, satisfies


class PackValidationError(ValueError):
    """Raised when a pack.yaml fails schema, parsing, or semver validation."""


def load_pack_manifest(pack_dir: Path, core_version: str | None = None) -> PackManifest:
    core_version = core_version if core_version is not None else core.__version__
    manifest_path = pack_dir / "pack.yaml"
    if not manifest_path.exists():
        raise PackValidationError(f"{pack_dir} has no pack.yaml")

    with manifest_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    try:
        manifest = PackManifest.model_validate(raw)
    except ValidationError as exc:
        raise PackValidationError(f"{manifest_path} failed schema validation: {exc}") from exc

    try:
        in_range = satisfies(core_version, manifest.requires_core)
    except InvalidVersionError as exc:
        raise PackValidationError(
            f"{manifest_path} has an invalid requires_core range {manifest.requires_core!r}: {exc}"
        ) from exc

    if not in_range:
        raise PackValidationError(
            f"{manifest.name} requires_core {manifest.requires_core!r}, "
            f"but the running core is {core_version}"
        )

    return manifest
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest core/tests/packs/test_loader.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add core/packs/loader.py core/tests/packs/test_loader.py
git commit -m "feat(packs): add pack.yaml loader with schema + requires_core validation"
```

---

### Task 4: Registry — install / list / remove

**Files:**
- Create: `core/packs/registry.py`
- Test: `core/tests/packs/test_registry.py`

**Interfaces:**
- Consumes: `core.packs.loader.load_pack_manifest`, `core.packs.loader.PackValidationError`, `core.packs.models.PackManifest`, `core.packs.models.PACK_NAME_RE`, `core.config.resolve.resolve_config_auto`, `core.config.resolve.resolve_path`.
- Produces: `PackInstallError(ValueError)`, `list_installed_packs(config=None, root=None) -> list[tuple[Path, PackManifest | None, str | None]]`, `install_pack(name: str, config=None, root=None) -> PackManifest`, `remove_pack(name: str, config=None, root=None) -> bool` — used by Task 5 (CLI) and Task 6 (doctor).

- [ ] **Step 1: Write the failing tests**

```python
# core/tests/packs/test_registry.py
import pytest
from core.packs.registry import (
    install_pack,
    list_installed_packs,
    remove_pack,
    PackInstallError,
)

VALID_YAML = """\
name: sample-pack
version: 1.0.0
kind: intelligence
summary: A sample pack for tests
requires_core: ">=0.1.0,<0.2.0"
capabilities: []
permissions_rationale: No capabilities needed for this test fixture.
dependencies: []
"""


def _make_registry_pack(root, name="sample-pack", contents=VALID_YAML):
    pack_dir = root / "packs" / "registry" / name
    pack_dir.mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text(contents, encoding="utf-8")
    return pack_dir


def _config(root):
    return {"paths": {"packs_installed": "packs/installed"}}


def test_install_copies_pack_and_returns_manifest(tmp_path):
    _make_registry_pack(tmp_path)
    manifest = install_pack("sample-pack", config=_config(tmp_path), root=tmp_path)
    assert manifest.name == "sample-pack"
    assert (tmp_path / "packs" / "installed" / "sample-pack" / "pack.yaml").exists()


def test_install_unknown_pack_raises(tmp_path):
    with pytest.raises(PackInstallError, match="no pack named"):
        install_pack("does-not-exist", config=_config(tmp_path), root=tmp_path)


def test_install_rejects_name_mismatch(tmp_path):
    _make_registry_pack(tmp_path, name="dir-name", contents=VALID_YAML)  # pack.yaml says sample-pack
    with pytest.raises(PackInstallError, match="does not match"):
        install_pack("dir-name", config=_config(tmp_path), root=tmp_path)


def test_install_rejects_self_dependency(tmp_path):
    self_dep_yaml = VALID_YAML.replace("dependencies: []", "dependencies: [sample-pack]")
    _make_registry_pack(tmp_path, contents=self_dep_yaml)
    with pytest.raises(PackInstallError, match="itself as a dependency"):
        install_pack("sample-pack", config=_config(tmp_path), root=tmp_path)


def test_install_rejects_unsafe_name_before_touching_disk(tmp_path):
    with pytest.raises(PackInstallError, match="slug"):
        install_pack("../../etc", config=_config(tmp_path), root=tmp_path)


def test_list_installed_returns_valid_and_invalid(tmp_path):
    _make_registry_pack(tmp_path)
    install_pack("sample-pack", config=_config(tmp_path), root=tmp_path)
    broken_dir = tmp_path / "packs" / "installed" / "broken-pack"
    broken_dir.mkdir(parents=True)
    (broken_dir / "pack.yaml").write_text("name: only-a-name\n", encoding="utf-8")

    results = list_installed_packs(config=_config(tmp_path), root=tmp_path)
    by_dirname = {pack_dir.name: (manifest, error) for pack_dir, manifest, error in results}

    manifest, error = by_dirname["sample-pack"]
    assert manifest is not None and error is None

    manifest, error = by_dirname["broken-pack"]
    assert manifest is None and "failed schema validation" in error


def test_list_installed_empty_when_dir_missing(tmp_path):
    results = list_installed_packs(config=_config(tmp_path), root=tmp_path)
    assert results == []


def test_remove_deletes_installed_pack(tmp_path):
    _make_registry_pack(tmp_path)
    install_pack("sample-pack", config=_config(tmp_path), root=tmp_path)
    removed = remove_pack("sample-pack", config=_config(tmp_path), root=tmp_path)
    assert removed is True
    assert not (tmp_path / "packs" / "installed" / "sample-pack").exists()


def test_remove_returns_false_when_not_installed(tmp_path):
    removed = remove_pack("never-installed", config=_config(tmp_path), root=tmp_path)
    assert removed is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest core/tests/packs/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.packs.registry'`

- [ ] **Step 3: Write the implementation**

```python
# core/packs/registry.py
"""Pack install/list/remove — docs/ARCHITECTURE.md §3 install/discovery
mechanism. Deliberately stateless: every call re-scans disk, so there is no
in-memory registry cache to invalidate on change. That satisfies "packs are
hot-discoverable ... no core restart required for content-only packs"
without a filesystem watcher (YAGNI — nothing in this repo yet holds a
long-lived pack registry in memory across calls).
"""
from __future__ import annotations

import shutil
from pathlib import Path

from core.config.resolve import resolve_config_auto, resolve_path
from core.packs.loader import PackValidationError, load_pack_manifest
from core.packs.models import PACK_NAME_RE, PackManifest

REGISTRY_DIRNAME = "registry"


class PackInstallError(ValueError):
    """Raised when installing or resolving a pack fails."""


def _validate_name(name: str) -> None:
    if not PACK_NAME_RE.match(name):
        raise PackInstallError(
            f"pack name {name!r} must be a lowercase slug matching {PACK_NAME_RE.pattern}"
        )


def _installed_dir(config: dict | None, root: Path | None) -> Path:
    resolved_root = root if root is not None else Path.cwd()
    config = config if config is not None else resolve_config_auto(root=resolved_root)
    return resolve_path(config, "paths.packs_installed", "packs/installed", root=resolved_root)


def _registry_dir(root: Path | None) -> Path:
    root = root if root is not None else Path.cwd()
    return root / "packs" / REGISTRY_DIRNAME


def list_installed_packs(
    config: dict | None = None, root: Path | None = None
) -> list[tuple[Path, PackManifest | None, str | None]]:
    """One (pack_dir, manifest, error) tuple per installed pack directory.
    Invalid packs are reported via the error slot, never raised — matches
    doctor's never-crash convention (core/diagnostics/checks.py)."""
    installed_dir = _installed_dir(config, root)
    if not installed_dir.exists():
        return []
    results: list[tuple[Path, PackManifest | None, str | None]] = []
    for pack_dir in sorted(p for p in installed_dir.iterdir() if p.is_dir()):
        try:
            manifest = load_pack_manifest(pack_dir)
            results.append((pack_dir, manifest, None))
        except PackValidationError as exc:
            results.append((pack_dir, None, str(exc)))
    return results


def install_pack(name: str, config: dict | None = None, root: Path | None = None) -> PackManifest:
    _validate_name(name)  # before any path is built or touched
    resolved_root = root if root is not None else Path.cwd()
    source_dir = _registry_dir(resolved_root) / name
    if not source_dir.exists():
        raise PackInstallError(f"no pack named {name!r} in {_registry_dir(resolved_root)}")

    manifest = load_pack_manifest(source_dir)  # validate BEFORE copying anything
    if manifest.name != name:
        raise PackInstallError(
            f"pack.yaml name {manifest.name!r} does not match requested pack {name!r}"
        )
    if manifest.name in manifest.dependencies:
        raise PackInstallError(f"{name} declares itself as a dependency")

    installed_dir = _installed_dir(config, resolved_root)
    dest_dir = installed_dir / name
    # Defense in depth beyond the slug regex: the resolved dest must stay
    # inside installed_dir even after path resolution.
    installed_dir.mkdir(parents=True, exist_ok=True)
    if installed_dir.resolve() not in dest_dir.resolve().parents and dest_dir.resolve() != installed_dir.resolve():
        raise PackInstallError(f"resolved install path {dest_dir} escapes {installed_dir}")

    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(source_dir, dest_dir)
    return manifest


def remove_pack(name: str, config: dict | None = None, root: Path | None = None) -> bool:
    _validate_name(name)
    dest_dir = _installed_dir(config, root) / name
    if not dest_dir.exists():
        return False
    shutil.rmtree(dest_dir)
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest core/tests/packs/test_registry.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add core/packs/registry.py core/tests/packs/test_registry.py
git commit -m "feat(packs): add install/list/remove registry operations"
```

---

### Task 5: Wire `packs.integrity` doctor check to real validation

**Files:**
- Modify: `core/diagnostics/checks.py:51-65` (the `_check_packs_integrity` function)
- Test: `core/tests/diagnostics/test_checks.py` (existing file — read it first to match its established fixture/mocking style before adding to it)

**Interfaces:**
- Consumes: `core.packs.registry.list_installed_packs`.
- Produces: unchanged signature `_check_packs_integrity(config: dict | None = None) -> CheckResult`, but now `FAIL`s when any installed pack's manifest is invalid instead of only counting directories.

- [ ] **Step 1: Read the existing test file to match conventions**

Run: `cat core/tests/diagnostics/test_checks.py` (or open it) — confirm how existing tests construct a `tmp_path`-based config and call check functions directly, so the new tests match that pattern exactly rather than inventing a new one.

- [ ] **Step 2: Write the failing tests**

Add to `core/tests/diagnostics/test_checks.py` (append; keep existing tests untouched):

```python
def test_packs_integrity_passes_with_zero_packs(tmp_path):
    from core.diagnostics.checks import _check_packs_integrity

    config = {"paths": {"packs_installed": str(tmp_path / "packs" / "installed")}}
    result = _check_packs_integrity(config)
    assert result.status == "PASS"
    assert "0 packs" in result.message


def test_packs_integrity_passes_with_one_valid_pack(tmp_path):
    from core.diagnostics.checks import _check_packs_integrity

    pack_dir = tmp_path / "packs" / "installed" / "sample-pack"
    pack_dir.mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text(
        "name: sample-pack\n"
        "version: 1.0.0\n"
        "kind: intelligence\n"
        "summary: test\n"
        'requires_core: ">=0.0.0,<1.0.0"\n'
        "permissions_rationale: none needed\n",
        encoding="utf-8",
    )
    config = {"paths": {"packs_installed": str(tmp_path / "packs" / "installed")}}
    result = _check_packs_integrity(config)
    assert result.status == "PASS"
    assert "1 pack" in result.message


def test_packs_integrity_fails_with_invalid_manifest(tmp_path):
    from core.diagnostics.checks import _check_packs_integrity

    pack_dir = tmp_path / "packs" / "installed" / "broken-pack"
    pack_dir.mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text("name: only-a-name\n", encoding="utf-8")
    config = {"paths": {"packs_installed": str(tmp_path / "packs" / "installed")}}
    result = _check_packs_integrity(config)
    assert result.status == "FAIL"
    assert "broken-pack" in result.message
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest core/tests/diagnostics/test_checks.py -k packs_integrity -v`
Expected: FAIL — `test_packs_integrity_fails_with_invalid_manifest` fails because the current implementation only counts directories and always returns PASS.

- [ ] **Step 4: Rewrite `_check_packs_integrity`**

Replace `core/diagnostics/checks.py:51-65` with:

```python
def _check_packs_integrity(config: dict | None = None) -> CheckResult:
    from core.packs.registry import list_installed_packs  # local import: avoids a diagnostics->packs->config import cycle at module load time

    config = config if config is not None else resolve_config_auto()
    results = list_installed_packs(config=config)
    invalid = [(pack_dir, error) for pack_dir, manifest, error in results if error is not None]
    if invalid:
        details = "; ".join(f"{pack_dir.name}: {error}" for pack_dir, error in invalid)
        return CheckResult(
            name="packs.integrity",
            status="FAIL",
            message=f"{len(invalid)} of {len(results)} installed packs failed validation — {details}",
        )
    count = len(results)
    noun = "pack" if count == 1 else "packs"
    return CheckResult(name="packs.integrity", status="PASS", message=f"{count} {noun} installed, all valid")
```

Also remove the now-stale comment on the line above it (`# Phase 8 adds real manifest validation here; Phase 0/1 only counts.`) — this task is that Phase 8 work landing.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest core/tests/diagnostics/test_checks.py -v` and `pytest scripts/tests/test_cli.py -v`
Expected: PASS on all — including the pre-existing `test_doctor_lists_every_check` and `test_doctor_exits_zero_when_no_failures`, which must still pass unchanged since `packs.integrity` still PASSes with zero packs installed in this repo's default state.

- [ ] **Step 6: Commit**

```bash
git add core/diagnostics/checks.py core/tests/diagnostics/test_checks.py
git commit -m "feat(diagnostics): validate installed pack manifests in packs.integrity check"
```

---

### Task 6: CLI — `promptwise pack install / list / remove`

**Files:**
- Modify: `scripts/promptwise.py`
- Test: `scripts/tests/test_cli.py` (append)

**Interfaces:**
- Consumes: `core.packs.registry.install_pack`, `core.packs.registry.list_installed_packs`, `core.packs.registry.remove_pack`, `core.packs.registry.PackInstallError`, `core.packs.loader.PackValidationError`.
- Produces: a `pack` sub-command group on the existing Typer `app` (`promptwise pack install NAME`, `promptwise pack list`, `promptwise pack remove NAME`).

- [ ] **Step 1: Write the failing tests**

Append to `scripts/tests/test_cli.py`:

```python
def test_pack_list_reports_no_packs_when_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "packs" / "installed").mkdir(parents=True)
    result = runner.invoke(app, ["pack", "list"])
    assert result.exit_code == 0
    assert "no packs installed" in result.stdout


def test_pack_install_then_list_then_remove(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry_pack = tmp_path / "packs" / "registry" / "sample-pack"
    registry_pack.mkdir(parents=True)
    (registry_pack / "pack.yaml").write_text(
        "name: sample-pack\n"
        "version: 1.0.0\n"
        "kind: intelligence\n"
        "summary: test pack\n"
        'requires_core: ">=0.0.0,<1.0.0"\n'
        "permissions_rationale: none needed\n",
        encoding="utf-8",
    )

    install_result = runner.invoke(app, ["pack", "install", "sample-pack"])
    assert install_result.exit_code == 0
    assert "installed sample-pack@1.0.0" in install_result.stdout

    list_result = runner.invoke(app, ["pack", "list"])
    assert list_result.exit_code == 0
    assert "sample-pack@1.0.0" in list_result.stdout
    assert "intelligence" in list_result.stdout

    remove_result = runner.invoke(app, ["pack", "remove", "sample-pack"])
    assert remove_result.exit_code == 0
    assert "removed sample-pack" in remove_result.stdout

    list_after_remove = runner.invoke(app, ["pack", "list"])
    assert "no packs installed" in list_after_remove.stdout


def test_pack_install_unknown_pack_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["pack", "install", "does-not-exist"])
    assert result.exit_code == 1
    assert "install failed" in result.stdout


def test_pack_remove_unknown_pack_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["pack", "remove", "never-installed"])
    assert result.exit_code == 1
    assert "not installed" in result.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest scripts/tests/test_cli.py -k pack_ -v`
Expected: FAIL — `pack` is not a registered command group yet (`Error: No such command 'pack'`).

- [ ] **Step 3: Add the `pack` sub-app to `scripts/promptwise.py`**

Add these imports near the top (alongside the existing `core.diagnostics` imports):

```python
from core.packs.loader import PackValidationError
from core.packs.registry import PackInstallError, install_pack, list_installed_packs, remove_pack
```

Add this after the existing `profile` command, before `if __name__ == "__main__":`:

```python
pack_app = typer.Typer(help="Manage installed packs (docs/ARCHITECTURE.md §3)")
app.add_typer(pack_app, name="pack")


@pack_app.command("list")
def pack_list() -> None:
    """List installed packs; invalid manifests are flagged, not hidden."""
    results = list_installed_packs()
    if not results:
        typer.echo("no packs installed")
        return
    for pack_dir, manifest, error in results:
        if manifest is not None:
            typer.echo(f"{manifest.name}@{manifest.version} ({manifest.kind}) — {pack_dir.name}")
        else:
            typer.echo(f"[INVALID] {pack_dir.name} — {error}")


@pack_app.command("install")
def pack_install(name: str) -> None:
    """Copy packs/registry/<name> into packs/installed/<name> after validation."""
    try:
        manifest = install_pack(name)
    except (PackInstallError, PackValidationError) as exc:
        typer.echo(f"install failed: {exc}")
        raise typer.Exit(code=1)
    typer.echo(f"installed {manifest.name}@{manifest.version}")


@pack_app.command("remove")
def pack_remove(name: str) -> None:
    """Delete packs/installed/<name>."""
    removed = remove_pack(name)
    if not removed:
        typer.echo(f"{name} is not installed")
        raise typer.Exit(code=1)
    typer.echo(f"removed {name}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest scripts/tests/test_cli.py -v`
Expected: PASS on all — including every pre-existing `doctor`/`profile` test, unchanged.

- [ ] **Step 5: Commit**

```bash
git add scripts/promptwise.py scripts/tests/test_cli.py
git commit -m "feat(cli): add promptwise pack install/list/remove commands"
```

---

### Task 7: Docs — `intelligence` kind + Phase 8 roadmap update

**Files:**
- Modify: `docs/ARCHITECTURE.md` (§3 pack.yaml kind line and Pack families table)
- Modify: `docs/ROADMAP.md` (Phase 8 row)
- Modify: `packs/CLAUDE.md` (authoring checklist item 1)

No test — documentation-only, verified by inline review in Step 2.

- [ ] **Step 1: Update `docs/ARCHITECTURE.md`**

Change line 64 from:
```yaml
kind: stack            # stack | database | cloud-devops | architecture | migration | lifecycle
```
to:
```yaml
kind: stack            # stack | database | cloud-devops | architecture | migration | lifecycle | intelligence
```

Add a row to the "Pack families" table (after the Lifecycle packs row, around line 85):

```markdown
| Intelligence packs | reverse-engineers an existing repo into feature/requirements/architecture/pseudocode/design docs | `orchestrate_tasks`, `rank_context`, code index |
```

- [ ] **Step 2: Update `docs/ROADMAP.md` Phase 8 row**

In the Phase 8 row's "Acceptance criteria" cell, append (after the existing "each includes a working `troubleshooting.md`..." clause):

`; the intelligence-kind repo-intelligence pack produces feature/requirements/architecture/pseudocode/design docs on a real sample repo; bmad-methodology and dmaic-methodology packs each run one DAG end-to-end with an intact audit trail without altering spec-engine behavior for projects that don't opt in`

Cross-reference: `docs/superpowers/specs/2026-08-24-repo-intelligence-methodology-packs-design.md`.

- [ ] **Step 3: Update `packs/CLAUDE.md` authoring checklist**

In item 1, change:
```
1. `pack.yaml` — name, version, `kind`, `summary`, `requires_core` semver range, `capabilities` (least privilege — list only what's actually used), `permissions_rationale` (one sentence, human-readable, shown at install-approval time), `dependencies`.
```
to:
```
1. `pack.yaml` — name, version, `kind` (stack | database | cloud-devops | architecture | migration | lifecycle | intelligence), `summary`, `requires_core` semver range, `capabilities` (least privilege — list only what's actually used), `permissions_rationale` (one sentence, human-readable, shown at install-approval time), `dependencies`.
```

- [ ] **Step 4: Commit**

```bash
git add docs/ARCHITECTURE.md docs/ROADMAP.md packs/CLAUDE.md
git commit -m "docs: add intelligence pack kind and Phase 8 acceptance criteria"
```

---

### Task 8: End-to-end fixture pack integration test

**Files:**
- Create: `core/tests/packs/fixtures/valid-intelligence-pack/pack.yaml`
- Create: `core/tests/packs/fixtures/invalid-pack/pack.yaml`
- Test: `core/tests/packs/test_integration.py`

**Interfaces:**
- Consumes: `core.packs.registry.install_pack`, `core.packs.registry.list_installed_packs`, `core.packs.registry.remove_pack`, `core.diagnostics.checks._check_packs_integrity`.
- Produces: nothing new — this task only proves Tasks 1–6 compose correctly end to end using on-disk fixtures instead of inline YAML strings, closing out the plan.

- [ ] **Step 1: Create the fixture packs**

```yaml
# core/tests/packs/fixtures/valid-intelligence-pack/pack.yaml
name: valid-intelligence-pack
version: 1.0.0
kind: intelligence
summary: Fixture pack used by core/tests/packs/test_integration.py
requires_core: ">=0.0.0,<99.0.0"
capabilities:
  - fs:read
permissions_rationale: Fixture only — fs:read declared but never exercised in tests.
dependencies: []
```

```yaml
# core/tests/packs/fixtures/invalid-pack/pack.yaml
name: Invalid Pack Name
version: not-a-version
kind: nonsense-kind
```

- [ ] **Step 2: Write the failing test**

```python
# core/tests/packs/test_integration.py
"""End-to-end: install a fixture pack from a copied registry dir, confirm
doctor reports it, then remove it. Exercises Tasks 1-6 together instead of
each module in isolation."""
import shutil
from pathlib import Path

from core.diagnostics.checks import _check_packs_integrity
from core.packs.registry import install_pack, list_installed_packs, remove_pack

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _seed_registry(tmp_path: Path, fixture_name: str, install_as: str) -> None:
    dest = tmp_path / "packs" / "registry" / install_as
    shutil.copytree(FIXTURES_DIR / fixture_name, dest)


def _config(tmp_path: Path) -> dict:
    return {"paths": {"packs_installed": str(tmp_path / "packs" / "installed")}}


def test_valid_fixture_pack_installs_lists_and_passes_doctor(tmp_path):
    _seed_registry(tmp_path, "valid-intelligence-pack", "valid-intelligence-pack")
    config = _config(tmp_path)

    manifest = install_pack("valid-intelligence-pack", config=config, root=tmp_path)
    assert manifest.kind == "intelligence"

    results = list_installed_packs(config=config, root=tmp_path)
    assert len(results) == 1
    assert results[0][1].name == "valid-intelligence-pack"

    doctor_result = _check_packs_integrity(config)
    assert doctor_result.status == "PASS"

    removed = remove_pack("valid-intelligence-pack", config=config, root=tmp_path)
    assert removed is True
    assert list_installed_packs(config=config, root=tmp_path) == []


def test_invalid_fixture_pack_fails_doctor_after_manual_placement(tmp_path):
    # Simulate a pack that landed in packs/installed/ some other way (e.g. a
    # hand-edited manifest) rather than via install_pack, to prove doctor
    # catches it independent of the install path.
    installed_dir = tmp_path / "packs" / "installed" / "invalid-pack"
    shutil.copytree(FIXTURES_DIR / "invalid-pack", installed_dir)
    config = _config(tmp_path)

    doctor_result = _check_packs_integrity(config)
    assert doctor_result.status == "FAIL"
    assert "invalid-pack" in doctor_result.message
```

- [ ] **Step 3: Run test to verify it fails first, confirming the fixtures matter**

Run: `pytest core/tests/packs/test_integration.py -v`
Expected: at this point Tasks 1–6 are already implemented, so this should actually PASS immediately — run it to confirm, and if it fails, the failure indicates a real integration gap between the individually-tested modules (e.g. a config-shape mismatch) that must be fixed before proceeding, not skipped.

- [ ] **Step 4: Run full test suite**

Run: `pytest -v`
Expected: PASS on every test in `core/tests/`, `gateway/tests/`, `scripts/tests/` — this task's fixtures must not have broken anything else.

- [ ] **Step 5: Commit**

```bash
git add core/tests/packs/fixtures/ core/tests/packs/test_integration.py
git commit -m "test(packs): add end-to-end fixture-pack integration test"
```

---

## Self-Review Notes

- **Spec coverage**: this plan implements the pack-loader-foundation slice only (per the brainstorming session's explicit sequencing decision) — `intelligence` kind (Task 2, 7), manifest schema/validation (Task 1–3), install/list/remove mechanism (Task 4, §3 point 1/4), doctor integration (Task 5), CLI (Task 6). Repo-intelligence pack content, BMAD/DMAIC DAGs, and capability *enforcement* via `check_policy` are explicitly deferred to the spec's later phases (3–5) and are out of scope here — not gaps in this plan.
- **Placeholder scan**: no TBD/TODO; every step has runnable code.
- **Type consistency**: `PackManifest`, `PackValidationError`, `PackInstallError`, and the `(Path, PackManifest | None, str | None)` tuple shape are used identically across Tasks 3–8.
- **Safety additions beyond the spec** (per the "safer to use" requirement): `PACK_NAME_RE` slug validation rejects path-traversal-shaped names before any filesystem path is built from them (Task 2, enforced again defensively in Task 4's `install_pack`/`remove_pack`); self-dependency is rejected at install time; doctor `FAIL`s loudly on any invalid installed manifest rather than silently ignoring it.
