# Spec Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `core/spec/` — the `specify/plan/tasks/complete_task/verify/converge` verbs `docs/ROADMAP.md`'s Phase 5 acceptance criterion names, producing EARS-validated artifacts and gating `implement` on Phase 2's `verify_output` before a task counts as done.

**Architecture:** `core/spec/` — Pydantic v2 models, a pure EARS structural validator, a SQLite-backed artifact/task-status store (same pattern as `core/index`/`core/memory`), and an engine module wiring stage-ordering enforcement + the hybrid task-execution model together. Automatable tasks (a `run` callable supplied) execute via the existing, unmodified `orchestrate_tasks()`; interactive tasks (no callable — real code written by the calling agent across its own turns) are closed out via `complete_task`, which gates on `verify_output` before marking a task done.

**Tech Stack:** Python 3.12, Pydantic v2, `sqlite3` (stdlib, same as `core/index`/`core/memory`). No new dependency.

**Spec:** `docs/superpowers/specs/2026-08-31-spec-engine-design.md`

## Global Constraints

- Core stays language/domain-agnostic — no pack-specific branching in `core/spec/`.
- No verb reads a config file directly — always through `core/config/resolve.py`.
- Every verb call is auditable via `record_audit`.
- Out-of-order stage calls raise `ValueError` immediately (caller error, matches `orchestrate_tasks`' cycle/dangling-reference precedent) — everything past valid-order entry degrades gracefully, never raises for a runtime failure.
- TDD: failing test before implementation, every module.
- Dependency injection: tests construct real `TaskNode`s with plain functions/lambdas for automatable tasks — no mocking framework, same convention as `core/orchestrate`'s tests.
- **Implementation-level closure of a spec ambiguity (this plan's own ruling, not in the design doc):** an automatable task (`run` is not `None`) may only depend on other automatable tasks. `tasks_feature` validates this and raises `ValueError` if violated. Reason: `orchestrate_tasks()` computes its own topological order over only the automatable sub-DAG it's given — a dependency on a not-yet-done interactive task would be a dangling reference from that sub-DAG's point of view, since interactive tasks are never included in the sub-DAG passed to `orchestrate_tasks()`. An interactive task may depend on either kind freely; `complete_task` checks dependency status directly against the store, not via `orchestrate_tasks`.

## Verified interfaces this plan depends on (hand-checked against the real source, not assumed)

```python
# core/orchestrate/models.py — already merged (sub-project 1)
class DagNode(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    id: str
    run: Callable[[dict[str, Any]], Any]
    depends_on: list[str] = []
    task_type: str = "general"
    privacy_sensitive: bool = False

class Dag(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    name: str
    nodes: list[DagNode]

class NodeResult(BaseModel):
    status: Literal["done", "error", "skipped"]
    output: Any = None
    error: str | None = None

class DagResult(BaseModel):
    dag_name: str
    nodes: dict[str, NodeResult]

# core/orchestrate/graph.py
def topological_order(dag: Dag) -> list[str]: ...
# raises ValueError("... unknown node ...") on a dangling ref,
# ValueError("dag contains a cycle") on a cycle.

# core/orchestrate/runner.py
def orchestrate_tasks(dag: Dag, config: dict[str, Any] | None = None) -> DagResult: ...

# core/verify/gate.py — Phase 2, already merged
def verify_output(
    diff: str,
    spec: str | None = None,
    cwd: Path | None = None,
    config: dict[str, Any] | None = None,
    ledger_key: str | None = None,
) -> VerifyResult: ...

# core/verify/models.py
class VerifyResult(BaseModel):
    passed: bool
    results: list[ToolRunResult]
    blocked_reason: str | None = None
    retry_loop_broken: bool = False

# core/config/resolve.py
def resolve_config_auto(root: Path | None = None, env: Mapping[str, str] | None = None) -> dict[str, Any]: ...
def resolve_path(config: dict[str, Any], config_key: str, default_relpath: str, root: Path | None = None) -> Path: ...

# core/audit/log.py
def record_audit(
    config: dict[str, Any], actor: str, action: str, target: str, result: str,
    detail: dict[str, Any] | None = None,
) -> AuditRecord: ...
# AuditRecord.result is Literal["allow", "deny", "error"] — no neutral "success" value.
# This plan uses "allow" for a completed/successful call, "error" for a failed/blocked one,
# same convention orchestrate_tasks and the memory-fact-layer sub-project both already use.
```

---

### Task 1: `core/spec/models.py` — the typed contract

**Files:**
- Create: `core/spec/__init__.py` (empty)
- Create: `core/spec/models.py`
- Test: `core/tests/spec/__init__.py` (empty), `core/tests/spec/test_models.py`

**Interfaces:**
- Produces: `SpecArtifact`, `PlanArtifact`, `TaskNode`, `EarsViolation`, `ConvergeReport`, `SpecifyResult`, `TasksResult`, `CompleteTaskResult`, `VerifyFeatureResult` (all Pydantic v2) — consumed by Tasks 2-6.

- [ ] **Step 1: Write the failing tests**

`core/tests/spec/test_models.py`:
```python
from core.spec.models import (
    CompleteTaskResult,
    ConvergeReport,
    EarsViolation,
    PlanArtifact,
    SpecArtifact,
    SpecifyResult,
    TaskNode,
    TasksResult,
    VerifyFeatureResult,
)


def test_spec_artifact_defaults():
    spec = SpecArtifact(spec_id="s1", request="add a login form", created_at="2026-08-31T00:00:00+00:00")
    assert spec.complexity == "standard"
    assert spec.requirements == []


def test_spec_artifact_trivial_complexity():
    spec = SpecArtifact(
        spec_id="s1", request="fix typo", complexity="trivial", created_at="2026-08-31T00:00:00+00:00",
    )
    assert spec.complexity == "trivial"


def test_plan_artifact():
    plan = PlanArtifact(spec_id="s1", plan_id="p1", approach="use a modal", created_at="2026-08-31T00:00:00+00:00")
    assert plan.plan_id == "p1"


def test_task_node_automatable():
    node = TaskNode(id="t1", run=lambda inputs: "ok")
    assert node.run({}) == "ok"
    assert node.depends_on == []


def test_task_node_interactive_has_no_callable():
    node = TaskNode(id="t2")
    assert node.run is None


def test_ears_violation():
    v = EarsViolation(requirement="make it fast", shape_expected="Ubiquitous", reason="no 'shall'")
    assert v.requirement == "make it fast"


def test_converge_report():
    report = ConvergeReport(spec_id="s1", planned_tasks=3, done_tasks=1, pending_tasks=2, stale=True)
    assert report.stale is True


def test_specify_result():
    result = SpecifyResult(spec_id="s1", violations=[])
    assert result.violations == []


def test_tasks_result():
    result = TasksResult(dag_result=None, tasks=["t1", "t2"])
    assert result.tasks == ["t1", "t2"]


def test_complete_task_result():
    result = CompleteTaskResult(task_id="t1", passed=True, blocked_reason=None)
    assert result.passed is True


def test_verify_feature_result():
    result = VerifyFeatureResult(spec_id="s1", all_done=False, outstanding=["t2"])
    assert result.outstanding == ["t2"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest core/tests/spec/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.spec'`

- [ ] **Step 3: Implement `models.py`**

```python
# core/spec/models.py
from __future__ import annotations

from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict

from core.orchestrate.models import DagResult


class SpecArtifact(BaseModel):
    spec_id: str
    request: str
    complexity: Literal["trivial", "standard"] = "standard"
    requirements: list[str] = []
    created_at: str


class PlanArtifact(BaseModel):
    spec_id: str
    plan_id: str
    approach: str
    created_at: str


class TaskNode(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    run: Callable[[dict[str, Any]], Any] | None = None
    depends_on: list[str] = []
    task_type: str = "general"
    privacy_sensitive: bool = False


class EarsViolation(BaseModel):
    requirement: str
    shape_expected: str
    reason: str


class ConvergeReport(BaseModel):
    spec_id: str
    planned_tasks: int
    done_tasks: int
    pending_tasks: int
    stale: bool


class SpecifyResult(BaseModel):
    spec_id: str
    violations: list[EarsViolation]


class TasksResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    dag_result: DagResult | None
    tasks: list[str]


class CompleteTaskResult(BaseModel):
    task_id: str
    passed: bool
    blocked_reason: str | None = None


class VerifyFeatureResult(BaseModel):
    spec_id: str
    all_done: bool
    outstanding: list[str]
```

- [ ] **Step 4: Add `core/spec/__init__.py` and `core/tests/spec/__init__.py`** (both empty, same convention as `core/orchestrate/__init__.py`)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest core/tests/spec/test_models.py -v`
Expected: PASS (11 tests)

- [ ] **Step 6: Commit**

```bash
git add core/spec/__init__.py core/spec/models.py core/tests/spec/__init__.py core/tests/spec/test_models.py
git commit -m "feat(spec): typed contract — SpecArtifact/PlanArtifact/TaskNode/results"
```

---

### Task 2: `core/spec/ears.py` — `validate_ears`

**Files:**
- Create: `core/spec/ears.py`
- Test: `core/tests/spec/test_ears.py`

**Interfaces:**
- Consumes: `EarsViolation` (Task 1).
- Produces: `validate_ears(requirements: list[str]) -> list[EarsViolation]` — consumed by Task 4. Pure function, no I/O.

- [ ] **Step 1: Write the failing tests**

`core/tests/spec/test_ears.py`:
```python
from core.spec.ears import validate_ears


def test_ubiquitous_shape_passes():
    violations = validate_ears(["The system shall log every request."])
    assert violations == []


def test_event_driven_shape_passes():
    violations = validate_ears(["When a user logs in, the system shall record the timestamp."])
    assert violations == []


def test_state_driven_shape_passes():
    violations = validate_ears(["While the gate is locked, the system shall reject all writes."])
    assert violations == []


def test_unwanted_behavior_shape_passes():
    violations = validate_ears(["If the disk is full, then the system shall pause ingestion."])
    assert violations == []


def test_optional_feature_shape_passes():
    violations = validate_ears(["Where telemetry is enabled, the system shall emit metrics."])
    assert violations == []


def test_non_ears_sentence_is_flagged():
    violations = validate_ears(["make it fast"])
    assert len(violations) == 1
    assert violations[0].requirement == "make it fast"
    assert violations[0].reason == "does not match any EARS sentence shape"


def test_mixed_list_flags_only_the_bad_one():
    violations = validate_ears([
        "The system shall log every request.",
        "make it fast",
    ])
    assert len(violations) == 1
    assert violations[0].requirement == "make it fast"


def test_empty_list_has_no_violations():
    assert validate_ears([]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest core/tests/spec/test_ears.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.spec.ears'`

- [ ] **Step 3: Implement `ears.py`**

```python
# core/spec/ears.py
"""Structural EARS (Easy Approach to Requirements Syntax) validator — a
linter, not a generator or semantic scorer (design spec Ruling 4). Core
has no LLM client anywhere (docs/research/2026-08-31-findings-refresh.md
§0); this checks a caller-authored requirement string against the 5
canonical EARS sentence shapes via regex, nothing more.
"""
from __future__ import annotations

import re

from core.spec.models import EarsViolation

_SHAPES: dict[str, re.Pattern[str]] = {
    "Ubiquitous": re.compile(r"^The \S.* shall .+", re.IGNORECASE),
    "Event-driven": re.compile(r"^When .+, the \S.* shall .+", re.IGNORECASE),
    "State-driven": re.compile(r"^While .+, the \S.* shall .+", re.IGNORECASE),
    "Unwanted behavior": re.compile(r"^If .+, then the \S.* shall .+", re.IGNORECASE),
    "Optional feature": re.compile(r"^Where .+, the \S.* shall .+", re.IGNORECASE),
}


def validate_ears(requirements: list[str]) -> list[EarsViolation]:
    violations: list[EarsViolation] = []
    for requirement in requirements:
        if not any(pattern.match(requirement) for pattern in _SHAPES.values()):
            violations.append(
                EarsViolation(
                    requirement=requirement,
                    shape_expected="one of: " + ", ".join(_SHAPES),
                    reason="does not match any EARS sentence shape",
                )
            )
    return violations
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests/spec/test_ears.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add core/spec/ears.py core/tests/spec/test_ears.py
git commit -m "feat(spec): validate_ears — structural EARS shape linter"
```

---

### Task 3: `core/spec/store.py` — SQLite-backed artifact/task-status store

**Files:**
- Create: `core/spec/store.py`
- Test: `core/tests/spec/test_store.py`

**Interfaces:**
- Consumes: `SpecArtifact`, `PlanArtifact`, `TaskNode` (Task 1), `resolve_path` (`core/config/resolve.py`, verified above).
- Produces: `open_store(config, root=None) -> sqlite3.Connection`, `save_spec`, `get_spec`, `get_stage`, `set_stage`, `save_plan`, `get_plan`, `save_tasks`, `get_tasks`, `update_task_status` — consumed by Task 4-6.

- [ ] **Step 1: Write the failing tests**

`core/tests/spec/test_store.py`:
```python
import json

from core.spec.models import PlanArtifact, SpecArtifact, TaskNode
from core.spec.store import (
    get_plan,
    get_spec,
    get_stage,
    get_tasks,
    open_store,
    save_plan,
    save_spec,
    save_tasks,
    set_stage,
    update_task_status,
)


def _config(tmp_path):
    return {"spec": {"db_path": str(tmp_path / "spec_engine.sqlite3")}}


def test_save_and_get_spec(tmp_path):
    conn = open_store(_config(tmp_path))
    spec = SpecArtifact(spec_id="s1", request="add login", created_at="2026-08-31T00:00:00+00:00")
    save_spec(conn, spec)
    set_stage(conn, "s1", "specified")
    fetched = get_spec(conn, "s1")
    assert fetched is not None
    assert fetched.request == "add login"
    assert get_stage(conn, "s1") == "specified"


def test_get_spec_missing_returns_none(tmp_path):
    conn = open_store(_config(tmp_path))
    assert get_spec(conn, "does-not-exist") is None
    assert get_stage(conn, "does-not-exist") is None


def test_set_stage_updates_existing_spec(tmp_path):
    conn = open_store(_config(tmp_path))
    save_spec(conn, SpecArtifact(spec_id="s1", request="x", created_at="2026-08-31T00:00:00+00:00"))
    set_stage(conn, "s1", "specified")
    set_stage(conn, "s1", "planned")
    assert get_stage(conn, "s1") == "planned"


def test_save_and_get_plan(tmp_path):
    conn = open_store(_config(tmp_path))
    save_plan(conn, PlanArtifact(spec_id="s1", plan_id="p1", approach="use a modal", created_at="2026-08-31T00:00:00+00:00"))
    plan = get_plan(conn, "s1")
    assert plan is not None
    assert plan.plan_id == "p1"


def test_get_plan_missing_returns_none(tmp_path):
    conn = open_store(_config(tmp_path))
    assert get_plan(conn, "does-not-exist") is None


def test_save_and_get_tasks(tmp_path):
    conn = open_store(_config(tmp_path))
    tasks = [
        TaskNode(id="t1", run=lambda inputs: "ok"),
        TaskNode(id="t2", depends_on=["t1"]),
    ]
    save_tasks(conn, "s1", tasks)
    rows = get_tasks(conn, "s1")
    by_id = {row["task_id"]: row for row in rows}
    assert by_id["t1"]["is_automatable"] is True
    assert by_id["t1"]["status"] == "pending"
    assert by_id["t2"]["is_automatable"] is False
    assert by_id["t2"]["depends_on"] == ["t1"]


def test_update_task_status(tmp_path):
    conn = open_store(_config(tmp_path))
    save_tasks(conn, "s1", [TaskNode(id="t1")])
    update_task_status(conn, "s1", "t1", "done")
    rows = get_tasks(conn, "s1")
    assert rows[0]["status"] == "done"
    assert rows[0]["error"] is None


def test_update_task_status_with_error(tmp_path):
    conn = open_store(_config(tmp_path))
    save_tasks(conn, "s1", [TaskNode(id="t1")])
    update_task_status(conn, "s1", "t1", "error", error="boom")
    rows = get_tasks(conn, "s1")
    assert rows[0]["status"] == "error"
    assert rows[0]["error"] == "boom"


def test_get_tasks_for_unknown_spec_returns_empty_list(tmp_path):
    conn = open_store(_config(tmp_path))
    assert get_tasks(conn, "does-not-exist") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest core/tests/spec/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.spec.store'`

- [ ] **Step 3: Implement `store.py`**

```python
# core/spec/store.py
"""SQLite-backed store for spec/plan/task artifacts and per-task status.
Same pattern as core/index/store.py and core/memory/store.py — a
config-resolved db_path, WAL mode for concurrent readers, no ORM.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from core.config.resolve import resolve_path
from core.spec.models import PlanArtifact, SpecArtifact, TaskNode

_SCHEMA = """
CREATE TABLE IF NOT EXISTS specs (
    spec_id TEXT PRIMARY KEY,
    request TEXT NOT NULL,
    complexity TEXT NOT NULL,
    requirements_json TEXT NOT NULL,
    stage TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
    spec_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    approach TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    spec_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    depends_on_json TEXT NOT NULL,
    is_automatable INTEGER NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    PRIMARY KEY (spec_id, task_id)
);
"""


def open_store(config: dict[str, Any], root: Path | None = None) -> sqlite3.Connection:
    db_path = resolve_path(config, "spec.db_path", ".promptwise/spec_engine.sqlite3", root=root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def save_spec(conn: sqlite3.Connection, spec: SpecArtifact) -> None:
    with conn:
        conn.execute(
            "INSERT INTO specs (spec_id, request, complexity, requirements_json, stage, created_at) "
            "VALUES (?, ?, ?, ?, NULL, ?) "
            "ON CONFLICT(spec_id) DO UPDATE SET request=excluded.request, complexity=excluded.complexity, "
            "requirements_json=excluded.requirements_json",
            (spec.spec_id, spec.request, spec.complexity, json.dumps(spec.requirements), spec.created_at),
        )


def get_spec(conn: sqlite3.Connection, spec_id: str) -> SpecArtifact | None:
    row = conn.execute(
        "SELECT spec_id, request, complexity, requirements_json, created_at FROM specs WHERE spec_id = ?",
        (spec_id,),
    ).fetchone()
    if row is None:
        return None
    return SpecArtifact(
        spec_id=row[0], request=row[1], complexity=row[2], requirements=json.loads(row[3]), created_at=row[4],
    )


def get_stage(conn: sqlite3.Connection, spec_id: str) -> str | None:
    row = conn.execute("SELECT stage FROM specs WHERE spec_id = ?", (spec_id,)).fetchone()
    return row[0] if row is not None else None


def set_stage(conn: sqlite3.Connection, spec_id: str, stage: str) -> None:
    with conn:
        conn.execute("UPDATE specs SET stage = ? WHERE spec_id = ?", (stage, spec_id))


def save_plan(conn: sqlite3.Connection, plan: PlanArtifact) -> None:
    with conn:
        conn.execute(
            "INSERT INTO plans (spec_id, plan_id, approach, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(spec_id) DO UPDATE SET plan_id=excluded.plan_id, approach=excluded.approach",
            (plan.spec_id, plan.plan_id, plan.approach, plan.created_at),
        )


def get_plan(conn: sqlite3.Connection, spec_id: str) -> PlanArtifact | None:
    row = conn.execute(
        "SELECT spec_id, plan_id, approach, created_at FROM plans WHERE spec_id = ?", (spec_id,)
    ).fetchone()
    if row is None:
        return None
    return PlanArtifact(spec_id=row[0], plan_id=row[1], approach=row[2], created_at=row[3])


def save_tasks(conn: sqlite3.Connection, spec_id: str, tasks: list[TaskNode]) -> None:
    with conn:
        for task in tasks:
            conn.execute(
                "INSERT INTO tasks (spec_id, task_id, depends_on_json, is_automatable, status, error) "
                "VALUES (?, ?, ?, ?, 'pending', NULL) "
                "ON CONFLICT(spec_id, task_id) DO UPDATE SET depends_on_json=excluded.depends_on_json, "
                "is_automatable=excluded.is_automatable",
                (spec_id, task.id, json.dumps(task.depends_on), int(task.run is not None)),
            )


def get_tasks(conn: sqlite3.Connection, spec_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT task_id, depends_on_json, is_automatable, status, error FROM tasks WHERE spec_id = ?",
        (spec_id,),
    ).fetchall()
    return [
        {
            "task_id": row[0],
            "depends_on": json.loads(row[1]),
            "is_automatable": bool(row[2]),
            "status": row[3],
            "error": row[4],
        }
        for row in rows
    ]


def update_task_status(
    conn: sqlite3.Connection, spec_id: str, task_id: str, status: str, error: str | None = None
) -> None:
    with conn:
        conn.execute(
            "UPDATE tasks SET status = ?, error = ? WHERE spec_id = ? AND task_id = ?",
            (status, error, spec_id, task_id),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests/spec/test_store.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add core/spec/store.py core/tests/spec/test_store.py
git commit -m "feat(spec): SQLite-backed spec/plan/task store"
```

---

### Task 4: `core/spec/engine.py` — `specify_feature`, `plan_feature`

**Files:**
- Create: `core/spec/engine.py`
- Test: `core/tests/spec/test_engine_specify_plan.py`

**Interfaces:**
- Consumes: everything from Tasks 1-3, plus `resolve_config_auto` and `record_audit` (verified above).
- Produces: `specify_feature(request, requirements, complexity="standard", config=None, root=None) -> SpecifyResult`, `plan_feature(spec_id, approach, config=None, root=None) -> str` — consumed by Task 5.

- [ ] **Step 1: Write the failing tests**

`core/tests/spec/test_engine_specify_plan.py`:
```python
import pytest

from core.spec.engine import plan_feature, specify_feature
from core.spec.store import get_stage, get_tasks, open_store


def _config(tmp_path):
    return {
        "spec": {"db_path": str(tmp_path / "spec_engine.sqlite3")},
        "audit": {"log_path": str(tmp_path / "audit.jsonl")},
    }


def test_specify_feature_standard_complexity_stores_spec_and_flags_bad_requirement(tmp_path):
    config = _config(tmp_path)
    result = specify_feature(
        request="add a login form",
        requirements=["The system shall render a login form.", "make it pretty"],
        config=config,
    )
    assert len(result.violations) == 1
    assert result.violations[0].requirement == "make it pretty"
    conn = open_store(config)
    assert get_stage(conn, result.spec_id) == "specified"


def test_specify_feature_trivial_complexity_skips_straight_to_implementing(tmp_path):
    config = _config(tmp_path)
    result = specify_feature(request="fix typo", requirements=[], complexity="trivial", config=config)
    conn = open_store(config)
    assert get_stage(conn, result.spec_id) == "implementing"
    tasks = get_tasks(conn, result.spec_id)
    assert len(tasks) == 1
    assert tasks[0]["is_automatable"] is False


def test_plan_feature_requires_specified_stage(tmp_path):
    config = _config(tmp_path)
    with pytest.raises(ValueError, match="specified"):
        plan_feature("does-not-exist", "use a modal", config=config)


def test_plan_feature_advances_stage_to_planned(tmp_path):
    config = _config(tmp_path)
    spec = specify_feature(request="add a login form", requirements=[], config=config)
    plan_id = plan_feature(spec.spec_id, "use a modal dialog", config=config)
    assert plan_id
    conn = open_store(config)
    assert get_stage(conn, spec.spec_id) == "planned"


def test_plan_feature_twice_still_requires_specified_stage(tmp_path):
    config = _config(tmp_path)
    spec = specify_feature(request="add a login form", requirements=[], config=config)
    plan_feature(spec.spec_id, "first approach", config=config)
    with pytest.raises(ValueError, match="specified"):
        plan_feature(spec.spec_id, "second approach", config=config)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest core/tests/spec/test_engine_specify_plan.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.spec.engine'`

- [ ] **Step 3: Implement `engine.py` (specify_feature and plan_feature only — tasks_feature/complete_task/verify_feature/converge_feature added in Tasks 5-6)**

```python
# core/spec/engine.py
"""The spec engine's public verbs. Content (requirements, approach, task
implementation) is always caller-authored — core has no LLM client
(docs/research/2026-08-31-findings-refresh.md §0). This module enforces
stage ordering, EARS structure, and the implement->verify gate; it never
generates spec/plan/task content itself.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.audit.log import record_audit
from core.config.resolve import resolve_config_auto
from core.spec.ears import validate_ears
from core.spec.models import PlanArtifact, SpecArtifact, SpecifyResult, TaskNode
from core.spec.store import get_stage, open_store, save_plan, save_spec, save_tasks, set_stage


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def specify_feature(
    request: str,
    requirements: list[str],
    complexity: str = "standard",
    config: dict[str, Any] | None = None,
    root: Path | None = None,
) -> SpecifyResult:
    config = config if config is not None else resolve_config_auto(root=root)
    conn = open_store(config, root=root)

    violations = validate_ears(requirements)
    spec_id = uuid.uuid4().hex
    save_spec(
        conn,
        SpecArtifact(
            spec_id=spec_id, request=request, complexity=complexity, requirements=requirements,
            created_at=_now(),
        ),
    )

    if complexity == "trivial":
        save_tasks(conn, spec_id, [TaskNode(id="implement")])
        stage = "implementing"
    else:
        stage = "specified"
    set_stage(conn, spec_id, stage)

    record_audit(
        config, actor="spec_engine", action="specify", target=spec_id,
        result="allow", detail={"violations": len(violations), "complexity": complexity},
    )
    return SpecifyResult(spec_id=spec_id, violations=violations)


def plan_feature(
    spec_id: str, approach: str, config: dict[str, Any] | None = None, root: Path | None = None,
) -> str:
    config = config if config is not None else resolve_config_auto(root=root)
    conn = open_store(config, root=root)

    stage = get_stage(conn, spec_id)
    if stage != "specified":
        raise ValueError(f"cannot plan spec {spec_id!r} in stage {stage!r}; expected 'specified'")

    plan_id = uuid.uuid4().hex
    save_plan(conn, PlanArtifact(spec_id=spec_id, plan_id=plan_id, approach=approach, created_at=_now()))
    set_stage(conn, spec_id, "planned")

    record_audit(config, actor="spec_engine", action="plan", target=spec_id, result="allow", detail={})
    return plan_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests/spec/test_engine_specify_plan.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add core/spec/engine.py core/tests/spec/test_engine_specify_plan.py
git commit -m "feat(spec): specify_feature/plan_feature — stage-ordering, EARS validation, ceremony scaling"
```

---

### Task 5: `core/spec/engine.py` — `tasks_feature`

**Files:**
- Modify: `core/spec/engine.py`
- Test: `core/tests/spec/test_engine_tasks.py`

**Interfaces:**
- Consumes: `Dag`, `orchestrate_tasks` (`core/orchestrate/`, verified above), `topological_order`, plus Task 4's `specify_feature`/`plan_feature`.
- Produces: `tasks_feature(spec_id, tasks, config=None, root=None) -> TasksResult` — consumed by Task 6.

- [ ] **Step 1: Write the failing tests**

`core/tests/spec/test_engine_tasks.py`:
```python
import pytest

from core.spec.engine import plan_feature, specify_feature, tasks_feature
from core.spec.models import TaskNode
from core.spec.store import get_stage, get_tasks, open_store


def _config(tmp_path):
    return {
        "spec": {"db_path": str(tmp_path / "spec_engine.sqlite3")},
        "audit": {"log_path": str(tmp_path / "audit.jsonl")},
        "engine": {"local_only": True},
        "routing": {"default_tier": "local-small"},
    }


def _planned_spec(tmp_path, config):
    spec = specify_feature(request="add a login form", requirements=[], config=config)
    plan_feature(spec.spec_id, "use a modal dialog", config=config)
    return spec.spec_id


def test_tasks_feature_requires_planned_stage(tmp_path):
    config = _config(tmp_path)
    with pytest.raises(ValueError, match="planned"):
        tasks_feature("does-not-exist", [TaskNode(id="t1")], config=config)


def test_tasks_feature_runs_automatable_tasks_via_orchestrate_tasks(tmp_path):
    config = _config(tmp_path)
    spec_id = _planned_spec(tmp_path, config)
    result = tasks_feature(spec_id, [TaskNode(id="scaffold", run=lambda inputs: "scaffolded")], config=config)
    assert result.dag_result is not None
    assert result.dag_result.nodes["scaffold"].status == "done"
    assert result.dag_result.nodes["scaffold"].output == "scaffolded"
    conn = open_store(config)
    rows = {row["task_id"]: row for row in get_tasks(conn, spec_id)}
    assert rows["scaffold"]["status"] == "done"
    assert get_stage(conn, spec_id) == "implementing"


def test_tasks_feature_leaves_interactive_tasks_pending(tmp_path):
    config = _config(tmp_path)
    spec_id = _planned_spec(tmp_path, config)
    result = tasks_feature(spec_id, [TaskNode(id="write-handler")], config=config)
    assert result.dag_result is None
    conn = open_store(config)
    rows = {row["task_id"]: row for row in get_tasks(conn, spec_id)}
    assert rows["write-handler"]["status"] == "pending"
    assert rows["write-handler"]["is_automatable"] is False


def test_tasks_feature_mixed_automatable_and_interactive(tmp_path):
    config = _config(tmp_path)
    spec_id = _planned_spec(tmp_path, config)
    tasks = [
        TaskNode(id="scaffold", run=lambda inputs: "scaffolded"),
        TaskNode(id="write-handler", depends_on=["scaffold"]),
    ]
    result = tasks_feature(spec_id, tasks, config=config)
    assert result.dag_result.nodes["scaffold"].status == "done"
    conn = open_store(config)
    rows = {row["task_id"]: row for row in get_tasks(conn, spec_id)}
    assert rows["scaffold"]["status"] == "done"
    assert rows["write-handler"]["status"] == "pending"


def test_tasks_feature_rejects_automatable_task_depending_on_interactive_task(tmp_path):
    config = _config(tmp_path)
    spec_id = _planned_spec(tmp_path, config)
    tasks = [
        TaskNode(id="write-handler"),
        TaskNode(id="run-tests", run=lambda inputs: "tested", depends_on=["write-handler"]),
    ]
    with pytest.raises(ValueError, match="automatable task .* depends on interactive task"):
        tasks_feature(spec_id, tasks, config=config)


def test_tasks_feature_validates_dag_structure_up_front(tmp_path):
    config = _config(tmp_path)
    spec_id = _planned_spec(tmp_path, config)
    with pytest.raises(ValueError, match="unknown node"):
        tasks_feature(spec_id, [TaskNode(id="t1", depends_on=["does-not-exist"])], config=config)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest core/tests/spec/test_engine_tasks.py -v`
Expected: FAIL — `ImportError: cannot import name 'tasks_feature' from 'core.spec.engine'`

- [ ] **Step 3: Add `tasks_feature` to `engine.py`**

Add these imports to the top of `core/spec/engine.py` (alongside the existing ones from Task 4):
```python
from core.orchestrate.graph import topological_order
from core.orchestrate.models import Dag
from core.orchestrate.runner import orchestrate_tasks
from core.spec.models import TasksResult
from core.spec.store import get_tasks, save_tasks, update_task_status
```

Append to `core/spec/engine.py`:
```python
def tasks_feature(
    spec_id: str, tasks: list[TaskNode], config: dict[str, Any] | None = None, root: Path | None = None,
) -> TasksResult:
    config = config if config is not None else resolve_config_auto(root=root)
    conn = open_store(config, root=root)

    stage = get_stage(conn, spec_id)
    if stage != "planned":
        raise ValueError(f"cannot set tasks for spec {spec_id!r} in stage {stage!r}; expected 'planned'")

    dag = Dag(name=spec_id, nodes=tasks)
    order = topological_order(dag)  # raises ValueError on cycle/dangling ref before anything else runs

    by_id = {task.id: task for task in tasks}
    for task in tasks:
        if task.run is not None:
            for dep_id in task.depends_on:
                if by_id[dep_id].run is None:
                    raise ValueError(
                        f"automatable task {task.id!r} depends on interactive task {dep_id!r} "
                        "— an automatable task may only depend on other automatable tasks"
                    )

    save_tasks(conn, spec_id, tasks)

    automatable = [task for task in tasks if task.run is not None]
    dag_result = None
    if automatable:
        auto_dag = Dag(name=spec_id, nodes=automatable)
        dag_result = orchestrate_tasks(auto_dag, config=config)
        for task_id, node_result in dag_result.nodes.items():
            update_task_status(conn, spec_id, task_id, node_result.status, node_result.error)

    set_stage(conn, spec_id, "implementing")
    record_audit(
        config, actor="spec_engine", action="tasks", target=spec_id,
        result="allow", detail={"automatable": len(automatable), "interactive": len(tasks) - len(automatable)},
    )
    return TasksResult(dag_result=dag_result, tasks=order)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests/spec/test_engine_tasks.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add core/spec/engine.py core/tests/spec/test_engine_tasks.py
git commit -m "feat(spec): tasks_feature — hybrid automatable/interactive task execution"
```

---

### Task 6: `core/spec/engine.py` — `complete_task`, `verify_feature`, `converge_feature`

**Files:**
- Modify: `core/spec/engine.py`
- Test: `core/tests/spec/test_engine_complete_verify_converge.py`

**Interfaces:**
- Consumes: `verify_output`, `VerifyResult` (`core/verify/`, verified above), plus Task 5's `tasks_feature`.
- Produces: `complete_task(spec_id, task_id, diff, cwd=None, config=None, root=None) -> CompleteTaskResult`, `verify_feature(spec_id, config=None, root=None) -> VerifyFeatureResult`, `converge_feature(spec_id, config=None, root=None) -> ConvergeReport` — this task's verbs are the plan's final public surface.

- [ ] **Step 1: Write the failing tests**

`core/tests/spec/test_engine_complete_verify_converge.py`:
```python
import pytest

from core.spec.engine import complete_task, converge_feature, plan_feature, specify_feature, tasks_feature, verify_feature
from core.spec.models import TaskNode
from core.spec.store import get_stage, open_store


def _config(tmp_path):
    return {
        "spec": {"db_path": str(tmp_path / "spec_engine.sqlite3")},
        "audit": {"log_path": str(tmp_path / "audit.jsonl")},
        "engine": {"local_only": True},
        "routing": {"default_tier": "local-small"},
        "verify": {},  # no test_command/lint_command configured -> no-op pass (core/verify/runners.py);
                       # semgrep/gitleaks fail-open when not on PATH (core/verify/security.py) — same
                       # config shape core/tests/verify/test_gate.py's own
                       # test_verify_output_no_test_command_configured_still_passes already relies on.
    }


def _tasked_spec(tmp_path, config, task_ids):
    spec = specify_feature(request="add a login form", requirements=[], config=config)
    plan_feature(spec.spec_id, "use a modal dialog", config=config)
    tasks_feature(spec.spec_id, [TaskNode(id=tid) for tid in task_ids], config=config)
    return spec.spec_id


def test_complete_task_rejects_unknown_task(tmp_path):
    config = _config(tmp_path)
    spec_id = _tasked_spec(tmp_path, config, ["write-handler"])
    with pytest.raises(ValueError, match="no task"):
        complete_task(spec_id, "does-not-exist", diff="", config=config)


def test_complete_task_rejects_automatable_task(tmp_path):
    config = _config(tmp_path)
    spec = specify_feature(request="x", requirements=[], config=config)
    plan_feature(spec.spec_id, "y", config=config)
    tasks_feature(spec.spec_id, [TaskNode(id="scaffold", run=lambda inputs: "ok")], config=config)
    with pytest.raises(ValueError, match="automatable"):
        complete_task(spec.spec_id, "scaffold", diff="", config=config)


def test_complete_task_blocked_by_unmet_dependency(tmp_path):
    config = _config(tmp_path)
    spec = specify_feature(request="x", requirements=[], config=config)
    plan_feature(spec.spec_id, "y", config=config)
    tasks_feature(
        spec.spec_id,
        [TaskNode(id="write-handler"), TaskNode(id="write-tests", depends_on=["write-handler"])],
        config=config,
    )
    result = complete_task(spec.spec_id, "write-tests", diff="", config=config)
    assert result.passed is False
    assert "write-handler" in result.blocked_reason


def test_complete_task_passes_marks_done_and_unblocks_dependent(tmp_path):
    config = _config(tmp_path)
    spec = specify_feature(request="x", requirements=[], config=config)
    plan_feature(spec.spec_id, "y", config=config)
    tasks_feature(
        spec.spec_id,
        [TaskNode(id="write-handler"), TaskNode(id="write-tests", depends_on=["write-handler"])],
        config=config,
    )
    result = complete_task(spec.spec_id, "write-handler", diff="d", cwd=tmp_path, config=config)
    assert result.passed is True
    assert result.blocked_reason is None
    # dependent is now unblocked (its only dependency is done) - complete_task on it should
    # proceed to the verify_output call rather than being blocked
    result2 = complete_task(spec.spec_id, "write-tests", diff="d2", cwd=tmp_path, config=config)
    assert result2.passed is True
    verify_result = verify_feature(spec.spec_id, config=config)
    assert verify_result.all_done is True
    assert verify_result.outstanding == []
    assert get_stage(open_store(config), spec.spec_id) == "verified"


def test_verify_feature_reports_outstanding_tasks(tmp_path):
    config = _config(tmp_path)
    spec_id = _tasked_spec(tmp_path, config, ["write-handler"])
    result = verify_feature(spec_id, config=config)
    assert result.all_done is False
    assert result.outstanding == ["write-handler"]
    assert get_stage(open_store(config), spec_id) == "implementing"


def test_converge_feature_reports_drift(tmp_path):
    config = _config(tmp_path)
    spec_id = _tasked_spec(tmp_path, config, ["write-handler", "write-tests"])
    report = converge_feature(spec_id, config=config)
    assert report.planned_tasks == 2
    assert report.done_tasks == 0
    assert report.pending_tasks == 2
    assert report.stale is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest core/tests/spec/test_engine_complete_verify_converge.py -v`
Expected: FAIL — `ImportError: cannot import name 'complete_task' from 'core.spec.engine'`

- [ ] **Step 3: Add `complete_task`, `verify_feature`, `converge_feature` to `engine.py`**

Add this import to the top of `core/spec/engine.py`:
```python
from core.verify.gate import verify_output
```

Append to `core/spec/engine.py`:
```python
def complete_task(
    spec_id: str, task_id: str, diff: str, cwd: Path | None = None,
    config: dict[str, Any] | None = None, root: Path | None = None,
) -> CompleteTaskResult:
    config = config if config is not None else resolve_config_auto(root=root)
    conn = open_store(config, root=root)

    rows = {row["task_id"]: row for row in get_tasks(conn, spec_id)}
    task = rows.get(task_id)
    if task is None:
        raise ValueError(f"no task {task_id!r} for spec {spec_id!r}")
    if task["is_automatable"]:
        raise ValueError(
            f"task {task_id!r} is automatable; it is completed via tasks_feature, not complete_task"
        )

    unmet = [dep for dep in task["depends_on"] if rows.get(dep, {}).get("status") != "done"]
    if unmet:
        return CompleteTaskResult(task_id=task_id, passed=False, blocked_reason=f"dependencies not done: {unmet}")

    result = verify_output(diff=diff, cwd=cwd, config=config)
    if result.passed:
        update_task_status(conn, spec_id, task_id, "done")
        record_audit(config, actor="spec_engine", action=f"complete_task:{task_id}", target=spec_id, result="allow", detail={})
    else:
        update_task_status(conn, spec_id, task_id, "pending", error=result.blocked_reason)
        record_audit(
            config, actor="spec_engine", action=f"complete_task:{task_id}", target=spec_id,
            result="error", detail={"blocked_reason": result.blocked_reason},
        )
    return CompleteTaskResult(task_id=task_id, passed=result.passed, blocked_reason=result.blocked_reason)


def verify_feature(
    spec_id: str, config: dict[str, Any] | None = None, root: Path | None = None,
) -> VerifyFeatureResult:
    config = config if config is not None else resolve_config_auto(root=root)
    conn = open_store(config, root=root)

    tasks = get_tasks(conn, spec_id)
    outstanding = [task["task_id"] for task in tasks if task["status"] != "done"]
    all_done = not outstanding
    if all_done:
        set_stage(conn, spec_id, "verified")

    record_audit(
        config, actor="spec_engine", action="verify", target=spec_id,
        result="allow" if all_done else "error", detail={"outstanding": outstanding},
    )
    return VerifyFeatureResult(spec_id=spec_id, all_done=all_done, outstanding=outstanding)


def converge_feature(
    spec_id: str, config: dict[str, Any] | None = None, root: Path | None = None,
) -> ConvergeReport:
    config = config if config is not None else resolve_config_auto(root=root)
    conn = open_store(config, root=root)

    tasks = get_tasks(conn, spec_id)
    planned = len(tasks)
    done = sum(1 for task in tasks if task["status"] == "done")
    pending = planned - done

    record_audit(config, actor="spec_engine", action="converge", target=spec_id, result="allow", detail={"pending": pending})
    return ConvergeReport(spec_id=spec_id, planned_tasks=planned, done_tasks=done, pending_tasks=pending, stale=pending > 0)
```

Also add `CompleteTaskResult`, `ConvergeReport`, `VerifyFeatureResult` to the `from core.spec.models import ...` line already present from Task 4 (extend the existing import, don't duplicate it).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests/spec/test_engine_complete_verify_converge.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full spec test suite together**

Run: `python -m pytest core/tests/spec -v`
Expected: PASS (all tests across test_models.py, test_ears.py, test_store.py, test_engine_specify_plan.py, test_engine_tasks.py, test_engine_complete_verify_converge.py — 45 total)

- [ ] **Step 6: Run the full project test suite to confirm no regressions**

Run: `python -m pytest core/tests gateway/tests scripts/tests -q`
Expected: PASS, count increased by this plan's new tests, no prior test broken. (Baseline before this plan: 292 passed, 4 skipped, per `CLAUDE.md`'s "Current status" section as of `9fe587d`.)

- [ ] **Step 7: Commit**

```bash
git add core/spec/engine.py core/tests/spec/test_engine_complete_verify_converge.py
git commit -m "feat(spec): complete_task/verify_feature/converge_feature — implement->verify gate, drift report"
```

---

## Post-plan follow-ups (not part of this plan, log to `docs/BACKLOG.md` if not picked up immediately)

- MCP tool exposure for all six `core/spec/` verbs (design doc's own deferred scope).
- Declarative task templates from a pack's future `dags/` or `specs/` folder.
- Revisit `orchestrate_tasks`' open BACKLOG item (`route_request` call outside per-node `try`) — `tasks_feature` calls `orchestrate_tasks` directly for the automatable subset, so a bad `route_request` call there can still abort that sub-DAG early; not fixed by this plan.
- SQLAlchemy/Alembic persistence gap (`2026-08-31-findings-refresh.md` §0) — `core/spec/store.py` is now the third module on the ad-hoc SQLite pattern; worth resolving before a fourth.
- If a real task turns out to need a callable that itself depends on an interactive task's output, this plan's automatable-cannot-depend-on-interactive constraint (Global Constraints) will need revisiting — flagged here rather than solved speculatively now.
