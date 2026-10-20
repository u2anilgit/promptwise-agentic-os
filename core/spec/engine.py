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
import os
import shlex
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from core.audit.log import record_audit
from core.config.resolve import resolve_config_auto
from core.db.base import session_scope
from core.db.migrate import migrate_to_head
from core.actions.shell import command_action as _command_action, shell_exec
from core.policy.engine import check_policy
from core.policy.jit import check_jit_grant, revoke_jit_grant
from core.orchestrate.graph import topological_order
from core.orchestrate.models import Dag, DagNode, DagResult
from core.orchestrate.runner import orchestrate_tasks
from core.spec import store
from core.spec.ears import validate_ears
from core.verify.gate import verify_output
from core.verify.models import VerifyResult
from core.verify.reviewer import run_reviewer
from core.spec.models import (
    AcceptanceCheck,
    Complexity,
    ConvergeReport,
    EarsViolation,
    FrozenCheck,
    PlanArtifact,
    Requirement,
    SpecArtifact,
    SpecSummary,
    TaskNode,
    TaskRecord,
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
        if not t.requirement_ids:
            raise ValueError(f"task '{t.id}' must reference at least one requirement (it would have no acceptance check)")
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


def _validate_check_command(check: AcceptanceCheck, config: dict[str, Any]) -> None:
    rid = check.requirement_id
    if not check.command.strip():
        raise ValueError(f"acceptance check for requirement '{rid}' has an empty command")
    try:
        shlex.split(check.command)
    except ValueError as exc:
        raise ValueError(f"acceptance check for requirement '{rid}': could not parse command - {exc}") from exc
    if not check.files and not _spec_setting(config, "allow_fileless_checks", False):
        raise ValueError(
            f"acceptance check for requirement '{rid}' must name at least one file "
            "(otherwise it can be edited unnoticed); set spec.allow_fileless_checks to override"
        )


def _unreferenced_check_files(checks: list[AcceptanceCheck]) -> list[str]:
    def norm(text: str) -> str:
        return text.replace(chr(92), "/")

    return [c.requirement_id for c in checks if c.files and not any(norm(f) in norm(c.command) for f in c.files)]


def _check_file(base: Path, relative: str, requirement_id: str) -> Path:
    path = (base / relative).resolve()
    root = base.resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"acceptance check file '{relative}' for requirement '{requirement_id}' is outside the project root")
    if not path.is_file():
        raise ValueError(f"acceptance check file '{relative}' for requirement '{requirement_id}' does not exist")
    return path


_TREE_IGNORED = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".promptwise"}
_TREE_MAX_FILES = 50_000


def _tree_state(base: Path) -> dict[str, tuple[int, int]] | None:
    """(size, mtime_ns) of every project file outside well-known cache/VCS dirs; None if the tree is too big to watch."""
    state: dict[str, tuple[int, int]] = {}
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in _TREE_IGNORED]
        for name in filenames:
            path = Path(dirpath) / name
            try:
                stat = path.stat()
            except OSError:
                continue
            state[path.relative_to(base).as_posix()] = (stat.st_size, stat.st_mtime_ns)
            if len(state) > _TREE_MAX_FILES:
                return None
    return state


def _refuse_baseline(config: dict[str, Any], spec_id: str, rid: str, reason: str) -> None:
    _audit(config, "baseline_rejected", spec_id, {"requirement_id": rid, "reason": reason}, result="deny")
    raise ValueError(reason)


def _observe_baseline(check: FrozenCheck, base: Path, config: dict[str, Any], spec_id: str) -> FrozenCheck:
    """Run the check before the work exists. A check that cannot fail proves nothing.

    'baseline_red' therefore means: the command ran properly (not missing, not timed out), FAILED on two
    consecutive runs, and wrote nothing to the project tree. It cannot rule out a check that keeps its state
    somewhere core cannot see; the reviewer hook and mutation gate exist for that residual risk."""
    rid = check.requirement_id
    timeout = int(_spec_setting(config, "check_timeout_seconds", 300))
    if check.expect_baseline == "pass" and not _spec_setting(config, "allow_regression_guards", True):
        _refuse_baseline(config, spec_id, rid, f"acceptance check for requirement '{rid}': regression guards are not allowed by the operator (spec.allow_regression_guards is false); write a check that fails before the work exists")
    if _spec_setting(config, "enforce_command_policy", True):
        action = _command_action(check.command, base)
        if not check_policy(action, config).allowed:
            _refuse_baseline(config, spec_id, rid, f"baseline run of the check for requirement '{rid}' was denied by policy ({action})")

    def run_once() -> str:
        outcome = shell_exec(f"baseline:{rid}", check.command, base, config, actor="spec_engine",
                             enforce_policy=bool(_spec_setting(config, "enforce_command_policy", True)), timeout=timeout)
        if outcome.error_kind == "timeout":
            _refuse_baseline(config, spec_id, rid, f"baseline run of the check for requirement '{rid}' timed out after {timeout}s; a check must finish on its own and may not wait for something the work will provide later")
        if outcome.error_kind:
            _refuse_baseline(config, spec_id, rid, f"baseline run of the check for requirement '{rid}' could not be executed ({outcome.error_kind}): fix the command; a missing program is not a failing test")
        return "passed" if outcome.passed else "failed"

    if check.expect_baseline == "fail":
        before = _tree_state(base)
        first, second = run_once(), run_once()
        after = _tree_state(base)
        if before is not None and after is not None and before != after:
            touched = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))[:3]
            _refuse_baseline(config, spec_id, rid, f"acceptance check for requirement '{rid}' wrote to the project tree during its baseline run ({', '.join(touched)}); a check must be read-only")
        if first != second:
            _refuse_baseline(config, spec_id, rid, f"acceptance check for requirement '{rid}' is unstable: it gave different results on two consecutive runs before any work was done")
        observed = first
    else:
        observed = run_once()

    if check.expect_baseline == "fail" and observed == "passed":
        _refuse_baseline(
            config, spec_id, rid,
            f"acceptance check for requirement '{rid}' already passes before implementation (it is vacuous or the "
            "requirement is already satisfied); fix the check, or set expect_baseline='pass' if it guards behaviour that must keep working",
        )
    if check.expect_baseline == "pass" and observed == "failed":
        _refuse_baseline(config, spec_id, rid, f"acceptance check for requirement '{rid}' is declared a regression guard (expect_baseline='pass') but already fails; fix the check or the code first")
    return check.model_copy(update={"baseline": observed})


def _freeze_checks(spec: SpecArtifact, checks: list[AcceptanceCheck], base: Path, config: dict[str, Any]) -> list[FrozenCheck]:
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
        _validate_check_command(c, config)
        hashes: dict[str, str] = {}
        for f in c.files:
            hashes[f] = file_sha256(_check_file(base, f, c.requirement_id))
        frozen.append(FrozenCheck(requirement_id=c.requirement_id, command=c.command, files=list(c.files), file_hashes=hashes, expect_baseline=c.expect_baseline))
    return frozen


def _task_shape(task: TaskNode) -> dict[str, Any]:
    return {"id": task.id, "depends_on": task.depends_on, "requirement_ids": task.requirement_ids,
            "expected_symbols": task.expected_symbols, "task_type": task.task_type}


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
        frozen = [_observe_baseline(f, base, config, spec_id) for f in _freeze_checks(spec, checks, base, config)]

        if stage == "specified":  # trivial path: auto-plan
            store.save_plan(session, PlanArtifact(spec_id=spec_id, approach="(trivial: auto-planned)", created_at=time.time(), requirements_sha256=requirements_hash(spec.requirements)))
        store.save_tasks(session, spec_id, tasks)
        store.save_frozen_checks(session, spec_id, frozen)
        store.set_stage(session, spec_id, "tasked")
        # Audited inside the transaction: if the record cannot be written, nothing commits.
        _audit(config, "tasks", spec_id, {
            "artifact_sha256": _sha({"tasks": [_task_shape(t) for t in tasks], "checks": [c.model_dump() for c in frozen]}),
            "task_count": len(tasks),
            "unreferenced_check_files": _unreferenced_check_files(checks),
            "baselines": {f.requirement_id: f.baseline for f in frozen},
            "expect_baselines": {f.requirement_id: f.expect_baseline for f in frozen},
        })

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

    return TasksResult(spec_id=spec_id, frozen=frozen, automated=automated)


class CompletionResult(BaseModel):
    task_id: str
    accepted: bool
    status: str
    reasons: list[str] = []
    verify: VerifyResult | None = None
    independence: dict[str, bool] = {}
    notes: list[str] = []  # reviewer reasons (operator-supplied text; treat as data)


def _unchanged(base: Path, check: FrozenCheck) -> list[str]:
    changed = []
    for f, frozen_hash in check.file_hashes.items():
        path = base / f
        if not path.is_file() or file_sha256(path) != frozen_hash:
            changed.append(f)
    return changed


def _reviewer_file(base: Path, relative: str) -> dict[str, str]:
    path = base / relative
    data = path.read_bytes() if path.is_file() else b""
    return {"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "content": data[:20000].decode("utf-8", errors="replace")}


def complete_task(
    spec_id: str,
    task_id: str,
    evidence: str,
    cwd: Path | None = None,
    config: dict[str, Any] | None = None,
    root: Path | None = None,
) -> CompletionResult:
    config = _prepare(config, root)
    base = Path(root) if root else Path.cwd()
    work = Path(cwd) if cwd else base

    with session_scope(config, root) as session:
        spec = _require_stage(session, spec_id, ("tasked", "implementing"), "complete_task")
        records = {t.task_id: t for t in store.get_tasks(session, spec_id)}
        if task_id not in records:
            raise ValueError(f"unknown task '{task_id}' for spec '{spec_id}'")
        task = records[task_id]
        frozen = {c.requirement_id: c for c in store.get_frozen_checks(session, spec_id)}

    def reject(reasons: list[str], verify: VerifyResult | None = None, extra: dict[str, Any] | None = None, notes: list[str] | None = None) -> CompletionResult:
        _audit(config, "complete_task", spec_id, {"task_id": task_id, "reasons": reasons, **(extra or {})}, result="deny")
        return CompletionResult(task_id=task_id, accepted=False, status=task.status, reasons=reasons, verify=verify, notes=notes or [])

    task_checks = [frozen[rid] for rid in task.requirement_ids if rid in frozen]
    modified = [f"acceptance_check_modified:{f}" for c in task_checks for f in _unchanged(base, c)]

    if task.status == "done":  # idempotent, but only while the checks that accepted it are intact
        if modified:
            return reject(modified, extra={"already_done": True})
        _audit(config, "complete_task", spec_id, {"task_id": task_id, "already_done": True})
        return CompletionResult(task_id=task_id, accepted=True, status="done")

    if any(records[d].status != "done" for d in task.depends_on if d in records):
        return reject(["dependency_not_done"])

    if not task_checks:
        return reject(["no_acceptance_check"])

    if modified:
        return reject(modified)

    unproven = [f"baseline_not_proven:{c.requirement_id}" for c in task_checks if c.baseline == "unverified"]
    if unproven:
        return reject(unproven)

    if _spec_setting(config, "enforce_command_policy", True):
        denied: dict[str, str] = {}
        for c in task_checks:
            action = _command_action(c.command, base)
            if not check_policy(action, config).allowed:
                denied[c.requirement_id] = action
        if denied:
            return reject([f"policy_denied:{rid}" for rid in denied], extra={"denied_actions": sorted(set(denied.values()))})

    timeout = int(_spec_setting(config, "check_timeout_seconds", 300))
    failed = []
    for c in task_checks:
        outcome = shell_exec(f"acceptance_check:{c.requirement_id}", c.command, base, config, actor="spec_engine",
                             enforce_policy=bool(_spec_setting(config, "enforce_command_policy", True)), timeout=timeout)
        if not (outcome.ran and outcome.passed):  # ran=False is a vacuous pass, never a pass
            failed.append(f"acceptance_check_failed:{c.requirement_id}")
    if failed:
        return reject(failed)

    verify = verify_output(diff=evidence, spec=None, cwd=work, config=config, ledger_key=f"{spec_id}:{task_id}", independent_cwd=base)
    if not verify.passed:
        return reject(["verify_gate_failed"], verify)
    if not verify.grounded and not _spec_setting(config, "allow_ungrounded", False):
        return reject(["ungrounded_verification"], verify)

    if _spec_setting(config, "require_mutation", False) and not verify.mutation_passed:
        return reject(["mutation_not_run"], verify)

    reviewer_approved = False
    if _spec_setting(config, "require_reviewer", False) and not (config.get("verify", {}).get("reviewer_command") or "").strip():
        return reject(["reviewer_not_configured"], verify)
    payload = {
        "spec_id": spec_id, "task_id": task_id, "evidence": evidence[:20000], "evidence_untrusted": True,
        "evidence_sha256": hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
        "requirements": [{"id": r.id, "text": r.text} for r in spec.requirements if r.id in task.requirement_ids],
        "checks": [
            {"requirement_id": c.requirement_id, "command": c.command, "baseline": c.baseline, "passed": True,
             "files": [_reviewer_file(base, f) for f in c.files]}
            for c in task_checks
        ],
    }
    verdict = run_reviewer(config, base, payload)  # the project root, never an agent-chosen directory
    if verdict.ran:
        if verdict.error:
            return reject(["reviewer_failed"], verify, extra={"reviewer_error": verdict.error}, notes=[verdict.error])
        if not verdict.approved:
            return reject(["reviewer_rejected"], verify, extra={"reviewer_reasons": verdict.reasons}, notes=verdict.reasons)
        reviewer_approved = True

    independence = {"baseline_red": all(c.baseline == "failed" for c in task_checks), "mutation": verify.mutation_passed, "reviewer": reviewer_approved}
    artifact = _sha({"task_id": task_id, "evidence_sha256": payload["evidence_sha256"], "checks": [c.model_dump() for c in task_checks]})
    with session_scope(config, root) as session:
        store.set_task_status(session, spec_id, task_id, "done")
        store.set_stage(session, spec_id, "implementing")
        # Audited inside the transaction: if the record cannot be written, the completion does not commit.
        _audit(config, "complete_task", spec_id, {"task_id": task_id, "artifact_sha256": artifact, "grounded": verify.grounded,
                                              "checks": [c.requirement_id for c in task_checks], "independence": independence,
                                              "reviewer_reasons": verdict.reasons if reviewer_approved else []})
    return CompletionResult(task_id=task_id, accepted=True, status="done", verify=verify, independence=independence)


def amend_grant_scope(spec_id: str) -> str:
    return f"spec:amend:{spec_id}"


def amend_check(
    spec_id: str,
    requirement_id: str,
    new_check: AcceptanceCheck,
    reason: str,
    config: dict[str, Any] | None = None,
    root: Path | None = None,
    require_grant: bool = True,
) -> FrozenCheck:
    """Replace a frozen check. Unless the operator is acting directly (require_grant=False, the CLI) or has
    switched spec.amend_requires_grant off, this needs a one-shot JIT grant for the spec, so an agent cannot
    rewrite the checks that judge its own work unattended. The grant is used up only by a successful amend."""
    config = _prepare(config, root)
    base = Path(root) if root else Path.cwd()
    if not reason.strip():
        raise ValueError("amend_check requires a non-empty reason")
    scope = amend_grant_scope(spec_id)
    needs_grant = require_grant and _spec_setting(config, "amend_requires_grant", True)
    if needs_grant and not check_jit_grant(config, scope):
        _audit(config, "amend_check", spec_id, {"requirement_id": requirement_id, "reason": "amend_requires_grant"}, result="deny")
        raise ValueError(
            f"amending a check of spec '{spec_id}' needs an operator grant: run "
            f"`promptwise spec allow-amend {spec_id}` (one amend, time-boxed), then retry"
        )
    if new_check.requirement_id != requirement_id:
        raise ValueError(f"new_check.requirement_id '{new_check.requirement_id}' does not match requirement '{requirement_id}'")
    _validate_check_command(new_check, config)

    hashes: dict[str, str] = {}
    for f in new_check.files:
        hashes[f] = file_sha256(_check_file(base, f, requirement_id))
    with session_scope(config, root) as session:  # validate BEFORE executing the agent's command
        _require_stage(session, spec_id, ("tasked", "implementing", "verified"), "amend_check")
        if not any(c.requirement_id == requirement_id for c in store.get_frozen_checks(session, spec_id)):
            raise ValueError(f"no frozen check for requirement '{requirement_id}' of spec '{spec_id}'")
    new = _observe_baseline(
        FrozenCheck(requirement_id=requirement_id, command=new_check.command, files=list(new_check.files), file_hashes=hashes, expect_baseline=new_check.expect_baseline),
        base, config, spec_id,
    )

    with session_scope(config, root) as session:
        _require_stage(session, spec_id, ("tasked", "implementing", "verified"), "amend_check")
        old = store.replace_frozen_check(session, spec_id, requirement_id, new)
        # Work that relied on the old check is no longer proven: reopen it.
        reset = [t.task_id for t in store.get_tasks(session, spec_id) if t.status == "done" and requirement_id in t.requirement_ids]
        for reopened in reset:
            store.set_task_status(session, spec_id, reopened, "pending")
        if store.get_stage(session, spec_id) == "verified":
            store.set_stage(session, spec_id, "implementing")
        # Inside the transaction, in this order: the grant is re-checked (the baseline run may have outlasted
        # it), the change is audited, and only then is the grant used up. Any failure commits nothing; a
        # failure before the revoke leaves the grant usable.
        if needs_grant and not check_jit_grant(config, scope):
            raise ValueError(f"the amend grant for spec '{spec_id}' expired or was used while this amend ran; retry with a new grant")
        _audit(config, "amend_check", spec_id, {
            "granted": needs_grant,
            "operator_direct": not require_grant,  # the CLI's own `spec amend`; anyone with that shell access counts as the operator
            "tasks_reset": reset,
            "requirement_id": requirement_id, "reason": reason,
            "old_command": old.command, "new_command": new.command,
            "old_hashes": old.file_hashes, "new_hashes": new.file_hashes,
            "old_expect_baseline": old.expect_baseline, "new_expect_baseline": new.expect_baseline,
            "old_baseline": old.baseline, "new_baseline": new.baseline,
        })
        if needs_grant and not revoke_jit_grant(config, scope):
            raise ValueError(f"the amend grant for spec '{spec_id}' expired or was used while this amend ran; retry with a new grant")
    return new


class VerifyFeatureResult(BaseModel):
    spec_id: str
    verified: bool
    outstanding: list[str]
    uncovered_requirements: list[str]


def verify_feature(spec_id: str, config: dict[str, Any] | None = None, root: Path | None = None) -> VerifyFeatureResult:
    config = _prepare(config, root)
    with session_scope(config, root) as session:
        spec = _require_stage(session, spec_id, ("tasked", "implementing", "verified"), "verify_feature")
        tasks = store.get_tasks(session, spec_id)
        outstanding = [t.task_id for t in tasks if t.status != "done"]
        covered = {rid for t in tasks if t.status == "done" for rid in t.requirement_ids}
        uncovered = [r.id for r in spec.requirements if r.id not in covered]
        verified = not outstanding and not uncovered
        if verified:
            store.set_stage(session, spec_id, "verified")
        artifact = _sha({"tasks": sorted((t.task_id, t.status) for t in tasks), "checks": [c.model_dump() for c in store.get_frozen_checks(session, spec_id)]})
        _audit(
            config, "verify_feature", spec_id,
            {"verified": verified, "artifact_sha256": artifact, "outstanding": outstanding, "uncovered_requirements": uncovered},
            result="allow" if verified else "deny",
        )
    return VerifyFeatureResult(spec_id=spec_id, verified=verified, outstanding=outstanding, uncovered_requirements=uncovered)


def _missing_symbols(symbols: list[str], root: Path, config: dict[str, Any]) -> list[str]:
    from core.index.query import query_code_index

    missing = []
    for name in symbols:
        # query_code_index matches by substring; the engine needs an exact definition.
        if not any(loc.symbol == name for loc in query_code_index(name, root=root, config=config)):
            missing.append(name)
    return missing


def converge_feature(spec_id: str, config: dict[str, Any] | None = None, root: Path | None = None) -> ConvergeReport:
    """Read-only drift report: compares hashes and symbols, never re-runs checks."""
    config = _prepare(config, root)
    base = Path(root) if root else Path.cwd()
    with session_scope(config, root) as session:
        spec = _require_stage(session, spec_id, ("tasked", "implementing", "verified"), "converge_feature")
        plan = store.get_plan(session, spec_id)
        tasks = store.get_tasks(session, spec_id)
        frozen = store.get_frozen_checks(session, spec_id)

    reasons: list[str] = []
    if plan is not None and plan.requirements_sha256 != requirements_hash(spec.requirements):
        reasons.append("requirements_changed")
    for check in frozen:
        for f, frozen_hash in check.file_hashes.items():
            path = base / f
            if not path.is_file():
                reasons.append(f"check_file_missing:{f}")
            elif file_sha256(path) != frozen_hash:
                reasons.append(f"check_file_changed:{f}")
    task_covered = {rid for t in tasks for rid in t.requirement_ids}
    reasons += [f"requirement_uncovered:{r.id}" for r in spec.requirements if r.id not in task_covered]
    symbols = sorted({s for t in tasks for s in t.expected_symbols})
    if symbols:
        reasons += [f"symbol_missing:{s}" for s in _missing_symbols(symbols, base, config)]

    done = sum(1 for t in tasks if t.status == "done")
    _audit(config, "converge", spec_id, {"stale": bool(reasons), "reasons": reasons, "done_tasks": done, "planned_tasks": len(tasks)},
           result="deny" if reasons else "allow")
    return ConvergeReport(
        spec_id=spec_id, planned_tasks=len(tasks), done_tasks=done, pending_tasks=len(tasks) - done,
        stale=bool(reasons), reasons=reasons,
    )


class SpecStatus(BaseModel):
    spec_id: str
    request: str
    complexity: str
    stage: str
    requirements: list[Requirement]
    tasks: list[TaskRecord]
    checks: list[FrozenCheck] = []


def spec_status(spec_id: str, config: dict[str, Any] | None = None, root: Path | None = None) -> SpecStatus:
    """Read-only snapshot: stage, requirements and per-task status."""
    config = _prepare(config, root)
    with session_scope(config, root) as session:
        spec = store.get_spec(session, spec_id)
        if spec is None:
            raise ValueError(f"unknown spec '{spec_id}'")
        return SpecStatus(
            spec_id=spec_id, request=spec.request, complexity=spec.complexity,
            stage=store.get_stage(session, spec_id) or "specified",
            requirements=spec.requirements, tasks=store.get_tasks(session, spec_id),
            checks=store.get_frozen_checks(session, spec_id),
        )


def list_specs(config: dict[str, Any] | None = None, root: Path | None = None) -> list[SpecSummary]:
    """Read-only overview of every spec, newest first."""
    config = _prepare(config, root)
    with session_scope(config, root) as session:
        return store.list_specs(session)
