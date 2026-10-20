"""Review minors M3-M6 (spec-engine v2): every state change is audited before it commits, completions and
verifications carry an artifact hash, the already-done shortcut is audited and re-checks frozen files, and
converge is audited."""
import pytest

from core.db.base import session_scope
from core.spec import engine, store
from core.spec.engine import complete_task, converge_feature, plan_feature, specify_feature, tasks_feature, verify_feature
from core.spec.models import TaskNode

from .conftest import REQS, STANDARD_CHECKS, audit_records, checks, interactive_tasks

GROUNDED = 'python -c "pass"'


def _tasked(project, tasks=None):
    tmp, config = project
    config["verify"]["test_command"] = GROUNDED
    spec = specify_feature("add login", list(REQS), config=config, root=tmp)
    plan_feature(spec.spec_id, "just do it", config=config, root=tmp)
    tasks_feature(spec.spec_id, tasks or interactive_tasks(), checks(*STANDARD_CHECKS), config=config, root=tmp)
    return spec.spec_id


def _entries(project, action):
    return [r for r in audit_records(project[0]) if r["actor"] == "spec_engine" and r["action"] == action]


def _status(project, spec_id, task_id):
    with session_scope(project[1], project[0]) as s:
        return next(t.status for t in store.get_tasks(s, spec_id) if t.task_id == task_id)


def _failing_audit(monkeypatch, action):
    real = engine._audit

    def audit(config, act, *args, **kwargs):
        if act == action and kwargs.get("result", "allow") == "allow":
            raise OSError("audit log unwritable")
        return real(config, act, *args, **kwargs)

    monkeypatch.setattr(engine, "_audit", audit)


def test_completion_is_not_committed_when_its_audit_cannot_be_written(project, monkeypatch):
    spec_id = _tasked(project)
    _failing_audit(monkeypatch, "complete_task")
    with pytest.raises(OSError):
        complete_task(spec_id, "t1", "did it", config=project[1], root=project[0])
    assert _status(project, spec_id, "t1") == "pending"


def test_tasks_are_not_committed_when_their_audit_cannot_be_written(project, monkeypatch):
    tmp, config = project
    spec = specify_feature("add login", list(REQS), config=config, root=tmp)
    plan_feature(spec.spec_id, "x", config=config, root=tmp)
    _failing_audit(monkeypatch, "tasks")
    with pytest.raises(OSError):
        tasks_feature(spec.spec_id, interactive_tasks(), checks(*STANDARD_CHECKS), config=config, root=tmp)
    with session_scope(config, tmp) as s:
        assert store.get_stage(s, spec.spec_id) == "planned"


def test_already_done_shortcut_is_audited(project):
    spec_id = _tasked(project)
    complete_task(spec_id, "t1", "did it", config=project[1], root=project[0])
    again = complete_task(spec_id, "t1", "did it", config=project[1], root=project[0])
    assert again.accepted
    assert _entries(project, "complete_task")[-1]["detail"].get("already_done") is True


def test_already_done_task_with_a_modified_check_file_is_not_reported_accepted(project):
    spec_id = _tasked(project)
    complete_task(spec_id, "t1", "did it", config=project[1], root=project[0])
    (project[0] / "check_login.py").write_text("import sys\nsys.exit(0)  # weakened\n", encoding="utf-8")
    again = complete_task(spec_id, "t1", "did it", config=project[1], root=project[0])
    assert not again.accepted
    assert any(r.startswith("acceptance_check_modified") for r in again.reasons)
    assert _entries(project, "complete_task")[-1]["result"] == "deny"


def test_completion_and_verification_audits_carry_an_artifact_hash(project):
    spec_id = _tasked(project)
    complete_task(spec_id, "t1", "did it", config=project[1], root=project[0])
    complete_task(spec_id, "t2", "did it", config=project[1], root=project[0])
    verify_feature(spec_id, config=project[1], root=project[0])
    accepted = [e for e in _entries(project, "complete_task") if e["result"] == "allow"]
    assert accepted and all(len(e["detail"]["artifact_sha256"]) == 64 for e in accepted)
    assert len(_entries(project, "verify_feature")[-1]["detail"]["artifact_sha256"]) == 64


def _tasks_hash(project, tasks):
    tmp, config = project
    spec = specify_feature("add login", list(REQS), config=config, root=tmp)
    plan_feature(spec.spec_id, "x", config=config, root=tmp)
    tasks_feature(spec.spec_id, tasks, checks(*STANDARD_CHECKS), config=config, root=tmp)
    return _entries(project, "tasks")[-1]["detail"]["artifact_sha256"]


def test_tasks_hash_covers_dependencies_and_requirement_links(project):
    a = _tasks_hash(project, [TaskNode(id="t1", requirement_ids=["R1"]), TaskNode(id="t2", requirement_ids=["R2"], depends_on=["t1"])])
    b = _tasks_hash(project, [TaskNode(id="t1", requirement_ids=["R1"]), TaskNode(id="t2", requirement_ids=["R2"])])
    c = _tasks_hash(project, [TaskNode(id="t1", requirement_ids=["R1", "R2"]), TaskNode(id="t2", requirement_ids=["R2"])])
    assert len({a, b, c}) == 3


def test_converge_is_audited(project):
    spec_id = _tasked(project)
    report = converge_feature(spec_id, config=project[1], root=project[0])
    entry = _entries(project, "converge")[-1]
    assert entry["detail"]["stale"] == report.stale
    assert entry["detail"]["reasons"] == report.reasons
