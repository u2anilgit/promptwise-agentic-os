# `orchestrate_tasks` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `orchestrate_tasks(dag, config=None) -> DagResult` — the DAG-runner core verb `docs/ARCHITECTURE.md` names, executing caller-supplied node callables in topological order with per-node tier resolution, audit, and fail-soft error isolation.

**Architecture:** `core/orchestrate/` — models (`DagNode`/`Dag`/`NodeResult`/`DagResult`), a pure topological-sort function, and the runner that ties sorting + `route_request` + node execution + `record_audit` together. Sequential execution only (no threads); a node's `run` is a plain Python callable — this verb never invokes an LLM/agent itself.

**Tech Stack:** Python 3.12 (repo's declared floor), Pydantic v2 (`arbitrary_types_allowed=True` for the callable field, hand-verified against the real installed Pydantic 2.13.4 before writing this plan). No new dependency.

**Spec:** `docs/superpowers/specs/2026-08-24-orchestrate-tasks-design.md`

## Global Constraints

- Core stays language/domain-agnostic — no pack-specific branching in `core/orchestrate/`.
- No verb reads a config file directly — always through `core/config/resolve.py`.
- Pydantic v2 models for the typed contract (`DagNode`, `Dag`, `NodeResult`, `DagResult`).
- Every verb call is auditable via `record_audit`, once per node (not once per whole DAG).
- Never crash on malformed input at the per-node level: a node's `run` raising, or a dependency
  having failed, are both handled states (`status="error"`/`"skipped"`), never exceptions that
  abort the whole `orchestrate_tasks` call. The one exception: a structurally invalid DAG (a
  cycle, or a node depending on an id that doesn't exist) raises `ValueError` immediately, before
  any node runs — a caller programming error, not a runtime failure to degrade through.
- TDD: failing test before implementation, every module.
- Dependency injection: `DagNode.run` IS the injection point — no mocking framework needed, tests
  construct DAGs with plain functions/lambdas.

## Verified interfaces this plan depends on (hand-checked against the real source, not assumed)

```python
# core/routing/router.py — already merged, already reviewed (Phase 1)
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
    privacy_forced: bool = False

def route_request(request: RouteRequest, hardware=None, config=None, catalog=None) -> RoutingDecision: ...
# hardware=None and catalog=None both auto-resolve internally — confirmed live during this
# plan's authoring: route_request(RouteRequest(task_type="general"),
# config={"engine": {"local_only": True}, "routing": {"default_tier": "local-small"}})
# returns a real RoutingDecision(tier='local-small', provider='ollama', ...) with no catalog/
# hardware argument needed.

# core/config/resolve.py
def resolve_config_auto(root: Path | None = None, env: Mapping[str, str] | None = None) -> dict[str, Any]: ...

# core/audit/log.py
def record_audit(
    config: dict[str, Any], actor: str, action: str, target: str, result: str,
    detail: dict[str, Any] | None = None,
) -> AuditRecord: ...
# AuditRecord.result is Literal["allow", "deny", "error"] (core/audit/models.py:6) — no neutral
# "success" value exists. This plan uses "allow" for a completed node, "error" for a failed or
# skipped one, per the memory-fact-layer sub-project's own already-resolved identical ruling.

# Pydantic 2.13.4 (installed, verified live during this plan's authoring)
from pydantic import BaseModel, ConfigDict
from typing import Callable, Any

class Node(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    run: Callable[[dict], Any]
# Constructing Node(run=some_function) and calling n.run({...}) works exactly as a plain
# attribute — confirmed live, not assumed from documentation.
```

---

### Task 1: `core/orchestrate/models.py` — `DagNode`, `Dag`, `NodeResult`, `DagResult`

**Files:**
- Create: `core/orchestrate/__init__.py` (empty)
- Create: `core/orchestrate/models.py`
- Test: `core/tests/orchestrate/__init__.py` (empty), `core/tests/orchestrate/test_models.py`

**Interfaces:**
- Produces: `DagNode`, `Dag`, `NodeResult`, `DagResult` (all Pydantic v2) — consumed by Tasks 2 and 3.

- [ ] **Step 1: Write the failing tests**

`core/tests/orchestrate/test_models.py`:
```python
from core.orchestrate.models import Dag, DagNode, DagResult, NodeResult


def test_dag_node_defaults():
    node = DagNode(id="a", run=lambda inputs: "output")
    assert node.id == "a"
    assert node.depends_on == []
    assert node.task_type == "general"
    assert node.privacy_sensitive is False
    assert node.run({}) == "output"


def test_dag_node_with_dependencies():
    node = DagNode(id="b", run=lambda inputs: inputs, depends_on=["a"], task_type="code_review")
    assert node.depends_on == ["a"]
    assert node.task_type == "code_review"


def test_dag_holds_nodes():
    nodes = [DagNode(id="a", run=lambda inputs: 1), DagNode(id="b", run=lambda inputs: 2, depends_on=["a"])]
    dag = Dag(name="example", nodes=nodes)
    assert dag.name == "example"
    assert len(dag.nodes) == 2


def test_node_result_defaults():
    result = NodeResult(status="done")
    assert result.status == "done"
    assert result.output is None
    assert result.error is None


def test_node_result_with_error():
    result = NodeResult(status="error", error="boom")
    assert result.status == "error"
    assert result.error == "boom"


def test_dag_result_holds_node_results():
    result = DagResult(dag_name="example", nodes={"a": NodeResult(status="done", output=1)})
    assert result.dag_name == "example"
    assert result.nodes["a"].output == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest core/tests/orchestrate/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.orchestrate'`

- [ ] **Step 3: Implement `models.py`**

```python
# core/orchestrate/models.py
from __future__ import annotations

from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict


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
```

- [ ] **Step 4: Add `core/orchestrate/__init__.py` and `core/tests/orchestrate/__init__.py`** (both empty, same convention as `core/memory/__init__.py`)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest core/tests/orchestrate/test_models.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add core/orchestrate/__init__.py core/orchestrate/models.py core/tests/orchestrate/__init__.py core/tests/orchestrate/test_models.py
git commit -m "feat(orchestrate): DagNode/Dag/NodeResult/DagResult models"
```

---

### Task 2: `core/orchestrate/graph.py` — `topological_order`

**Files:**
- Create: `core/orchestrate/graph.py`
- Test: `core/tests/orchestrate/test_graph.py`

**Interfaces:**
- Consumes: `Dag`, `DagNode` (Task 1).
- Produces: `topological_order(dag: Dag) -> list[str]` — consumed by Task 3. Pure function, no I/O. Raises `ValueError` on a cycle or a dependency referencing an unknown node id.

- [ ] **Step 1: Write the failing tests**

`core/tests/orchestrate/test_graph.py`:
```python
import pytest

from core.orchestrate.graph import topological_order
from core.orchestrate.models import Dag, DagNode


def _node(node_id, depends_on=None):
    return DagNode(id=node_id, run=lambda inputs: None, depends_on=depends_on or [])


def test_topological_order_orders_a_simple_chain():
    dag = Dag(name="chain", nodes=[_node("c", ["b"]), _node("a"), _node("b", ["a"])])
    order = topological_order(dag)
    assert order.index("a") < order.index("b") < order.index("c")


def test_topological_order_includes_every_node_exactly_once():
    dag = Dag(name="diamond", nodes=[_node("a"), _node("b", ["a"]), _node("c", ["a"]), _node("d", ["b", "c"])])
    order = topological_order(dag)
    assert sorted(order) == ["a", "b", "c", "d"]
    assert order.index("a") < order.index("b")
    assert order.index("a") < order.index("c")
    assert order.index("b") < order.index("d")
    assert order.index("c") < order.index("d")


def test_topological_order_handles_independent_nodes():
    dag = Dag(name="independent", nodes=[_node("a"), _node("b")])
    order = topological_order(dag)
    assert set(order) == {"a", "b"}


def test_topological_order_raises_on_a_dangling_dependency():
    dag = Dag(name="dangling", nodes=[_node("a", ["does-not-exist"])])
    with pytest.raises(ValueError, match="unknown node"):
        topological_order(dag)


def test_topological_order_raises_on_a_cycle():
    dag = Dag(name="cycle", nodes=[_node("a", ["b"]), _node("b", ["a"])])
    with pytest.raises(ValueError, match="cycle"):
        topological_order(dag)


def test_topological_order_on_an_empty_dag_returns_empty_list():
    dag = Dag(name="empty", nodes=[])
    assert topological_order(dag) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest core/tests/orchestrate/test_graph.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.orchestrate.graph'`

- [ ] **Step 3: Implement `graph.py`**

```python
# core/orchestrate/graph.py
"""Kahn's algorithm — pure function, no I/O. Raises ValueError immediately
on a structurally invalid DAG (a cycle, or a node depending on an id
that doesn't exist) rather than silently skipping or partially ordering
it — this is a caller programming error, not a runtime failure to
degrade through (design spec Ruling 4).
"""
from __future__ import annotations

from core.orchestrate.models import Dag


def topological_order(dag: Dag) -> list[str]:
    node_ids = {node.id for node in dag.nodes}
    for node in dag.nodes:
        for dep in node.depends_on:
            if dep not in node_ids:
                raise ValueError(f"node {node.id!r} depends on unknown node {dep!r}")

    in_degree = {node.id: len(node.depends_on) for node in dag.nodes}
    dependents: dict[str, list[str]] = {node.id: [] for node in dag.nodes}
    for node in dag.nodes:
        for dep in node.depends_on:
            dependents[dep].append(node.id)

    queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
    order: list[str] = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        for dependent in dependents[current]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(order) != len(dag.nodes):
        raise ValueError("dag contains a cycle")

    return order
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests/orchestrate/test_graph.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add core/orchestrate/graph.py core/tests/orchestrate/test_graph.py
git commit -m "feat(orchestrate): topological_order — Kahn's algorithm, cycle/dangling-ref detection"
```

---

### Task 3: `core/orchestrate/runner.py` — `orchestrate_tasks`

**Files:**
- Create: `core/orchestrate/runner.py`
- Test: `core/tests/orchestrate/test_runner.py`

**Interfaces:**
- Consumes: `Dag`, `DagResult`, `NodeResult` (Task 1), `topological_order` (Task 2), `RouteRequest`/`route_request` (`core/routing/router.py`, verified above), `record_audit` (`core/audit/log.py`, verified above), `resolve_config_auto` (`core/config/resolve.py`).
- Produces: `orchestrate_tasks(dag: Dag, config: dict[str, Any] | None = None) -> DagResult` — the sub-project's one public verb.

- [ ] **Step 1: Write the failing tests**

`core/tests/orchestrate/test_runner.py`:
```python
import pytest

from core.orchestrate.models import Dag, DagNode
from core.orchestrate.runner import orchestrate_tasks


def _config(tmp_path):
    return {
        "engine": {"local_only": True},
        "routing": {"default_tier": "local-small"},
        "audit": {"log_path": str(tmp_path / "audit.jsonl")},
    }


def test_orchestrate_tasks_runs_a_chain_and_threads_outputs(tmp_path):
    dag = Dag(
        name="chain",
        nodes=[
            DagNode(id="a", run=lambda inputs: 10),
            DagNode(id="b", run=lambda inputs: inputs["a"] + 5, depends_on=["a"]),
        ],
    )
    result = orchestrate_tasks(dag, config=_config(tmp_path))
    assert result.nodes["a"].status == "done"
    assert result.nodes["a"].output == 10
    assert result.nodes["b"].status == "done"
    assert result.nodes["b"].output == 15


def test_orchestrate_tasks_skips_dependents_of_a_failed_node(tmp_path):
    def failing(inputs):
        raise RuntimeError("boom")

    dag = Dag(
        name="fail-chain",
        nodes=[
            DagNode(id="a", run=failing),
            DagNode(id="b", run=lambda inputs: "should not run", depends_on=["a"]),
        ],
    )
    result = orchestrate_tasks(dag, config=_config(tmp_path))
    assert result.nodes["a"].status == "error"
    assert "boom" in result.nodes["a"].error
    assert result.nodes["b"].status == "skipped"


def test_orchestrate_tasks_runs_independent_branches_even_if_one_fails(tmp_path):
    def failing(inputs):
        raise RuntimeError("boom")

    dag = Dag(
        name="independent",
        nodes=[
            DagNode(id="a", run=failing),
            DagNode(id="b", run=lambda inputs: "ok"),
        ],
    )
    result = orchestrate_tasks(dag, config=_config(tmp_path))
    assert result.nodes["a"].status == "error"
    assert result.nodes["b"].status == "done"
    assert result.nodes["b"].output == "ok"


def test_orchestrate_tasks_raises_immediately_on_a_cyclic_dag_and_runs_nothing(tmp_path):
    ran = []
    dag = Dag(
        name="cycle",
        nodes=[
            DagNode(id="a", run=lambda inputs: ran.append("a"), depends_on=["b"]),
            DagNode(id="b", run=lambda inputs: ran.append("b"), depends_on=["a"]),
        ],
    )
    with pytest.raises(ValueError, match="cycle"):
        orchestrate_tasks(dag, config=_config(tmp_path))
    assert ran == []


def test_orchestrate_tasks_attaches_a_routing_decision_to_node_inputs(tmp_path):
    captured = {}

    def capture(inputs):
        captured["decision"] = inputs["routing_decision"]
        return "ok"

    dag = Dag(name="routed", nodes=[DagNode(id="a", run=capture, task_type="code_review")])
    orchestrate_tasks(dag, config=_config(tmp_path))
    assert captured["decision"].tier == "local-small"
    assert captured["decision"].provider == "ollama"


def test_orchestrate_tasks_on_an_empty_dag_returns_empty_results(tmp_path):
    dag = Dag(name="empty", nodes=[])
    result = orchestrate_tasks(dag, config=_config(tmp_path))
    assert result.dag_name == "empty"
    assert result.nodes == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest core/tests/orchestrate/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.orchestrate.runner'`

- [ ] **Step 3: Implement `runner.py`**

```python
# core/orchestrate/runner.py
"""orchestrate_tasks — the public verb. Topological execution of a Dag's
nodes: each node's `run` callable is invoked with its dependencies'
outputs plus a `routing_decision` hint from route_request. One node
failing marks it (and everything downstream of it) as not done, but
never aborts the whole call — independent branches still run (design
spec Ruling 4). The one exception: a structurally invalid DAG (cycle,
dangling reference) raises ValueError before any node runs.
"""
from __future__ import annotations

from typing import Any

from core.audit.log import record_audit
from core.config.resolve import resolve_config_auto
from core.orchestrate.graph import topological_order
from core.orchestrate.models import Dag, DagResult, NodeResult
from core.routing.router import RouteRequest, route_request


def orchestrate_tasks(dag: Dag, config: dict[str, Any] | None = None) -> DagResult:
    order = topological_order(dag)  # raises ValueError on cycle/dangling ref before anything runs
    config = config if config is not None else resolve_config_auto()
    nodes_by_id = {node.id: node for node in dag.nodes}

    results: dict[str, NodeResult] = {}
    for node_id in order:
        node = nodes_by_id[node_id]
        dep_failed = any(results[dep].status != "done" for dep in node.depends_on)

        if dep_failed:
            results[node_id] = NodeResult(status="skipped", error="a dependency did not complete")
            record_audit(
                config, actor="orchestrate_tasks", action=node_id, target=dag.name,
                result="error", detail={"reason": "dependency failed or skipped"},
            )
            continue

        decision = route_request(
            RouteRequest(task_type=node.task_type, privacy_sensitive=node.privacy_sensitive),
            config=config,
        )
        inputs: dict[str, Any] = {dep: results[dep].output for dep in node.depends_on}
        inputs["routing_decision"] = decision

        try:
            output = node.run(inputs)
            results[node_id] = NodeResult(status="done", output=output)
            record_audit(
                config, actor="orchestrate_tasks", action=node_id, target=dag.name,
                result="allow", detail={"tier": decision.tier},
            )
        except Exception as exc:  # noqa: BLE001 — one node's failure must not abort the DAG
            results[node_id] = NodeResult(status="error", error=str(exc))
            record_audit(
                config, actor="orchestrate_tasks", action=node_id, target=dag.name,
                result="error", detail={"error": str(exc)},
            )

    return DagResult(dag_name=dag.name, nodes=results)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests/orchestrate/test_runner.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full orchestrate test suite together**

Run: `python -m pytest core/tests/orchestrate -v`
Expected: PASS (all tests across test_models.py, test_graph.py, test_runner.py — 18 total)

- [ ] **Step 6: Run the full project test suite to confirm no regressions**

Run: `python -m pytest core/tests gateway/tests scripts/tests -q`
Expected: PASS, count increased by this plan's new tests (Tasks 1-3), no prior test broken. (Baseline before this plan: 274 passed, 4 skipped, per `docs/BACKLOG.md`'s ingestion-sweep entry.)

- [ ] **Step 7: Commit**

```bash
git add core/orchestrate/runner.py core/tests/orchestrate/test_runner.py
git commit -m "feat(orchestrate): orchestrate_tasks — the public verb, topological execution + audit"
```

---

## Post-plan follow-ups (not part of this plan, log to `docs/BACKLOG.md` if not picked up immediately)

- Sub-project 2: spec engine (`specify/plan/tasks/implement/verify`, EARS artifacts) — needs its own brainstorm once this verb ships; will consume `orchestrate_tasks` directly.
- Declarative DAG loading for pack-provided `dags/*.yaml` templates (`ARCHITECTURE.md` §3).
- Parallel execution strategy, if profiling on a real wide DAG ever shows sequential execution is a bottleneck (design spec Ruling 1's deferred cost).
- MCP tool exposure for `orchestrate_tasks`, mirroring the other core verbs' eventual MCP wrappers.
