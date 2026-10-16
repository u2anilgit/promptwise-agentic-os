# core/spec/engine.py
"""Spec engine verbs — docs/superpowers/specs/2026-10-16-spec-engine-v2-design.md.

specify -> plan -> tasks (freeze acceptance checks) -> complete_task ->
verify_feature, with converge_feature as a read-only drift report. Core
never calls an LLM: the calling agent authors content, the engine
validates structure, enforces stage order and gates completion on
frozen, grounded, objectively-run checks. Out-of-order calls and
structurally invalid input raise ValueError; runtime failures (a check
fails, a check file changed) are returned results, never exceptions.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from core.audit.log import record_audit
from core.config.resolve import resolve_config_auto
from core.db.base import session_scope
from core.db.migrate import migrate_to_head
from core.orchestrate.graph import topological_order
from core.orchestrate.models import Dag, DagNode, DagResult
from core.orchestrate.runner import orchestrate_tasks
from core.spec import store
from core.spec.ears import validate_ears
from core.spec.models import (
    AcceptanceCheck,
    Complexity,
    EarsViolation,
    FrozenCheck,
    PlanArtifact,
    Requirement,
    SpecArtifact,
    TaskNode,
)


class SpecResult(BaseModel):
    spec_id: str
    requirements: list[Requirement]
    violations: list[EarsViolation]


class TasksResult(BaseModel):
    spec_id: str
    frozen: list[FrozenCheck]
    automated: DagResult | None = None


def _sha(obj: Any) -> str:
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def requirements_hash(requirements: list[Requirement]) -> str:
    return _sha([(r.id, r.text) for r in requirements])


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare(config: dict[str, Any] | None, root: Path | None) -> dict[str, Any]:
    config = config if config is not None else resolve_config_auto(root=root)
    migrate_to_head(config, root)
    return config


def _spec_setting(config: dict[str, Any], key: str, default: Any) -> Any:
    return config.get("spec", {}).get(key, default)


def _audit(config: dict[str, Any], action: str, spec_id: str, detail: dict[str, Any], result: str = "allow") -> None:
    record_audit(config, actor="spec_engine", action=action, target=spec_id, result=result, detail=detail)  # type: ignore[arg-type]


def _require_stage(session, spec_id: str, allowed: tuple[str, ...], verb: str) -> SpecArtifact:
    spec = store.get_spec(session, spec_id)
    if spec is None:
        raise ValueError(f"unknown spec '{spec_id}'")
    stage = store.get_stage(session, spec_id)
    if stage not in allowed:
        raise ValueError(f"spec '{spec_id}' is at stage '{stage}'; {verb} requires stage {' or '.join(allowed)}")
    return spec


def specify_feature(
    request: str,
    requirements: list[str],
    complexity: Complexity = "standard",
    config: dict[str, Any] | None = None,
    root: Path | None = None,
) -> SpecResult:
    config = _prepare(config, root)
    if not requirements:
        raise ValueError("specify_feature needs at least one requirement")
    limit = int(_spec_setting(config, "trivial_max_requirements", 1))
    if complexity == "trivial" and len(requirements) > limit:
        raise ValueError(f"trivial complexity allows at most {limit} requirement(s), got {len(requirements)}")

    reqs = [Requirement(id=f"R{i}", text=text.strip()) for i, text in enumerate(requirements, start=1)]
    artifact = SpecArtifact(spec_id=uuid.uuid4().hex[:12], request=request, complexity=complexity, requirements=reqs, created_at=time.time())
    with session_scope(config, root) as session:
        store.save_spec(session, artifact)
        store.set_stage(session, artifact.spec_id, "specified")

    violations = validate_ears(reqs)
    digest = _sha(artifact.model_dump())
    if complexity == "trivial":
        _audit(config, "complexity_declared", artifact.spec_id, {"complexity": "trivial", "requirement_count": len(reqs)})
    _audit(config, "specify", artifact.spec_id, {"artifact_sha256": digest, "ears_violations": len(violations)})
    return SpecResult(spec_id=artifact.spec_id, requirements=reqs, violations=violations)


def plan_feature(spec_id: str, approach: str, config: dict[str, Any] | None = None, root: Path | None = None) -> PlanArtifact:
    config = _prepare(config, root)
    with session_scope(config, root) as session:
        spec = _require_stage(session, spec_id, ("specified",), "plan_feature")
        plan = PlanArtifact(spec_id=spec_id, approach=approach, created_at=time.time(), requirements_sha256=requirements_hash(spec.requirements))
        store.save_plan(session, plan)
        store.set_stage(session, spec_id, "planned")
    _audit(config, "plan", spec_id, {"artifact_sha256": _sha(plan.model_dump())})
    return plan


def _validate_tasks(spec: SpecArtifact, tasks: list[TaskNode]) -> None:
    ids = [t.id for t in tasks]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate task id in tasks")
    req_ids = {r.id for r in spec.requirements}
    for t in tasks:
        for rid in t.requirement_ids:
            if rid not in req_ids:
                raise ValueError(f"task '{t.id}' references unknown requirement '{rid}'")
    by_id = {t.id: t for t in tasks}
    for t in tasks:
        if t.run is None:
            continue
        for dep in t.depends_on:
            dep_task = by_id.get(dep)
            if dep_task is not None and dep_task.run is None:
                raise ValueError(f"callable task '{t.id}' may not depend on interactive task '{dep}'")
    # Structural validation (cycle / dangling ref) via the reused orchestrator graph.
    noop = lambda inputs: None  # noqa: E731
    topological_order(Dag(name=spec.spec_id, nodes=[DagNode(id=t.id, run=t.run or noop, depends_on=t.depends_on) for t in tasks]))


def _freeze_checks(spec: SpecArtifact, checks: list[AcceptanceCheck], base: Path) -> list[FrozenCheck]:
    seen: set[str] = set()
    for c in checks:
        if c.requirement_id in seen:
            raise ValueError(f"more than one acceptance check for requirement '{c.requirement_id}'")
        seen.add(c.requirement_id)
    known = {r.id for r in spec.requirements}
    for rid in seen - known:
        raise ValueError(f"acceptance check references unknown requirement '{rid}'")
    for rid in sorted(known - seen):
        raise ValueError(f"requirement '{rid}' has no acceptance check")

    frozen: list[FrozenCheck] = []
    for c in checks:
        hashes: dict[str, str] = {}
        for f in c.files:
            path = base / f
            if not path.is_file():
                raise ValueError(f"acceptance check file '{f}' for requirement '{c.requirement_id}' does not exist")
            hashes[f] = file_sha256(path)
        frozen.append(FrozenCheck(requirement_id=c.requirement_id, command=c.command, files=list(c.files), file_hashes=hashes))
    return frozen


def tasks_feature(
    spec_id: str,
    tasks: list[TaskNode],
    checks: list[AcceptanceCheck],
    config: dict[str, Any] | None = None,
    root: Path | None = None,
) -> TasksResult:
    config = _prepare(config, root)
    base = Path(root) if root else Path.cwd()

    with session_scope(config, root) as session:
        spec = _require_stage(session, spec_id, ("planned", "specified"), "tasks_feature")
        stage = store.get_stage(session, spec_id)
        trivial = spec.complexity == "trivial"
        if stage == "specified" and not trivial:
            raise ValueError(f"spec '{spec_id}' is at stage 'specified'; tasks_feature requires stage planned (standard complexity)")

        if not tasks:
            if not trivial:
                raise ValueError("tasks_feature needs at least one task")
            tasks = [TaskNode(id="T1", requirement_ids=[r.id for r in spec.requirements])]

        _validate_tasks(spec, tasks)
        frozen = _freeze_checks(spec, checks, base)

        if stage == "specified":  # trivial path: auto-plan
            store.save_plan(session, PlanArtifact(spec_id=spec_id, approach="(trivial: auto-planned)", created_at=time.time(), requirements_sha256=requirements_hash(spec.requirements)))
        store.save_tasks(session, spec_id, tasks)
        store.save_frozen_checks(session, spec_id, frozen)
        store.set_stage(session, spec_id, "tasked")

    automated: DagResult | None = None
    callable_nodes = [DagNode(id=t.id, run=t.run, depends_on=t.depends_on, task_type=t.task_type) for t in tasks if t.run is not None]  # type: ignore[arg-type]
    if callable_nodes:
        automated = orchestrate_tasks(Dag(name=spec_id, nodes=callable_nodes), config=config)
        with session_scope(config, root) as session:
            for node_id, result in automated.nodes.items():
                if result.status == "error":
                    store.set_task_status(session, spec_id, node_id, "error", error=result.error)
                elif result.status == "skipped":
                    store.set_task_status(session, spec_id, node_id, "error", error=result.error or "a dependency did not complete")
                # status "done": work executed, but completion is decided by complete_task's gate.

    _audit(config, "tasks", spec_id, {
        "artifact_sha256": _sha({"tasks": [t.id for t in tasks], "checks": [c.model_dump() for c in frozen]}),
        "task_count": len(tasks),
    })
    return TasksResult(spec_id=spec_id, frozen=frozen, automated=automated)
