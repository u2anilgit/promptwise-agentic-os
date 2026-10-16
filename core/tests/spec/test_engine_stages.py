import hashlib

import pytest

from core.db.base import session_scope
from core.spec import store
from core.spec.engine import plan_feature, specify_feature, tasks_feature
from core.spec.models import AcceptanceCheck, TaskNode

from .conftest import REQS, STANDARD_CHECKS, audit_records, checks, interactive_tasks


def _specified(project, complexity="standard", reqs=REQS):
    tmp, config = project
    return specify_feature("add login", list(reqs), complexity=complexity, config=config, root=tmp)


def _planned(project):
    tmp, config = project
    spec = _specified(project)
    plan_feature(spec.spec_id, "just do it", config=config, root=tmp)
    return spec


def test_specify_assigns_sequential_requirement_ids(project):
    spec = _specified(project)
    assert [r.id for r in spec.requirements] == ["R1", "R2"]


def test_specify_reports_ears_violations_without_raising(project):
    spec = _specified(project, reqs=["The system shall log in users.", "make it fast"])
    assert [v.requirement_id for v in spec.violations] == ["R2"]


def test_specify_requires_at_least_one_requirement(project):
    tmp, config = project
    with pytest.raises(ValueError, match="at least one requirement"):
        specify_feature("x", [], config=config, root=tmp)


def test_trivial_with_more_requirements_than_the_limit_is_rejected(project):
    with pytest.raises(ValueError, match="trivial"):
        _specified(project, complexity="trivial")


def test_trivial_declaration_is_audited(project):
    _specified(project, complexity="trivial", reqs=[REQS[0]])
    assert any(r["action"] == "complexity_declared" for r in audit_records(project[0]))


def test_plan_out_of_order_and_unknown_spec_raise_value_error(project):
    tmp, config = project
    with pytest.raises(ValueError, match="unknown spec"):
        plan_feature("ghost", "a", config=config, root=tmp)
    spec = _planned(project)
    with pytest.raises(ValueError, match="stage"):
        plan_feature(spec.spec_id, "again", config=config, root=tmp)


def test_stage_audit_entries_carry_an_artifact_hash(project):
    _planned(project)
    entries = [r for r in audit_records(project[0]) if r["actor"] == "spec_engine"]
    assert {e["action"] for e in entries} >= {"specify", "plan"}
    assert all(len(e["detail"]["artifact_sha256"]) == 64 for e in entries)


def test_tasks_before_plan_raises(project):
    tmp, config = project
    spec = _specified(project)
    with pytest.raises(ValueError, match="stage"):
        tasks_feature(spec.spec_id, interactive_tasks(), checks(*STANDARD_CHECKS), config=config, root=tmp)


def test_tasks_freezes_file_hashes_of_every_check(project):
    tmp, config = project
    spec = _planned(project)
    result = tasks_feature(spec.spec_id, interactive_tasks(), checks(*STANDARD_CHECKS), config=config, root=tmp)
    expected = hashlib.sha256((tmp / "check_login.py").read_bytes()).hexdigest()
    login = next(c for c in result.frozen if c.requirement_id == "R1")
    assert login.file_hashes == {"check_login.py": expected}


def test_requirement_without_a_check_is_rejected(project):
    tmp, config = project
    spec = _planned(project)
    with pytest.raises(ValueError, match="R2"):
        tasks_feature(spec.spec_id, interactive_tasks(), checks(("R1", "check_login.py")), config=config, root=tmp)


def test_two_checks_for_one_requirement_are_rejected(project):
    tmp, config = project
    spec = _planned(project)
    dup = checks(*STANDARD_CHECKS) + checks(("R1", "check_logout.py"))
    with pytest.raises(ValueError, match="more than one"):
        tasks_feature(spec.spec_id, interactive_tasks(), dup, config=config, root=tmp)


def test_check_with_a_missing_file_is_rejected(project):
    tmp, config = project
    spec = _planned(project)
    bad = [AcceptanceCheck(requirement_id="R1", command="python nope.py", files=["nope.py"]), *checks(("R2", "check_logout.py"))]
    with pytest.raises(ValueError, match="nope.py"):
        tasks_feature(spec.spec_id, interactive_tasks(), bad, config=config, root=tmp)


def test_task_referencing_an_unknown_requirement_is_rejected(project):
    tmp, config = project
    spec = _planned(project)
    with pytest.raises(ValueError, match="R9"):
        tasks_feature(spec.spec_id, [TaskNode(id="t1", requirement_ids=["R9"])], checks(*STANDARD_CHECKS), config=config, root=tmp)


def test_cycle_is_rejected_before_anything_runs(project):
    tmp, config = project
    spec = _planned(project)
    ran = []
    tasks = [
        TaskNode(id="a", requirement_ids=["R1", "R2"], depends_on=["b"], run=lambda i: ran.append("a")),
        TaskNode(id="b", requirement_ids=["R1"], depends_on=["a"], run=lambda i: ran.append("b")),
    ]
    with pytest.raises(ValueError, match="cycle"):
        tasks_feature(spec.spec_id, tasks, checks(*STANDARD_CHECKS), config=config, root=tmp)
    assert ran == []


def test_callable_task_may_not_depend_on_an_interactive_task(project):
    tmp, config = project
    spec = _planned(project)
    tasks = [TaskNode(id="t1", requirement_ids=["R1"]), TaskNode(id="t2", requirement_ids=["R2"], depends_on=["t1"], run=lambda i: 1)]
    with pytest.raises(ValueError, match="interactive"):
        tasks_feature(spec.spec_id, tasks, checks(*STANDARD_CHECKS), config=config, root=tmp)


def test_callable_task_runs_but_stays_pending_until_verified(project):
    tmp, config = project
    spec = _planned(project)
    ran = []
    tasks = [TaskNode(id="t1", requirement_ids=["R1", "R2"], run=lambda i: ran.append("t1") or "out")]
    result = tasks_feature(spec.spec_id, tasks, checks(*STANDARD_CHECKS), config=config, root=tmp)
    assert ran == ["t1"]
    assert result.automated.nodes["t1"].status == "done"
    with session_scope(config, tmp) as s:
        assert store.get_tasks(s, spec.spec_id)[0].status == "pending"


def test_failing_callable_task_is_recorded_as_error(project):
    tmp, config = project
    spec = _planned(project)

    def boom(inputs):
        raise RuntimeError("kaput")

    tasks = [TaskNode(id="t1", requirement_ids=["R1", "R2"], run=boom)]
    tasks_feature(spec.spec_id, tasks, checks(*STANDARD_CHECKS), config=config, root=tmp)
    with session_scope(config, tmp) as s:
        record = store.get_tasks(s, spec.spec_id)[0]
    assert record.status == "error" and "kaput" in record.error


def test_trivial_path_auto_plans_and_creates_one_implicit_task(project):
    tmp, config = project
    spec = _specified(project, complexity="trivial", reqs=[REQS[0]])
    tasks_feature(spec.spec_id, [], checks(("R1", "check_login.py")), config=config, root=tmp)
    with session_scope(config, tmp) as s:
        assert store.get_stage(s, spec.spec_id) == "tasked"
        assert [t.task_id for t in store.get_tasks(s, spec.spec_id)] == ["T1"]


def test_trivial_still_requires_a_check(project):
    tmp, config = project
    spec = _specified(project, complexity="trivial", reqs=[REQS[0]])
    with pytest.raises(ValueError, match="R1"):
        tasks_feature(spec.spec_id, [], [], config=config, root=tmp)


def test_standard_with_no_tasks_is_rejected(project):
    tmp, config = project
    spec = _planned(project)
    with pytest.raises(ValueError, match="at least one task"):
        tasks_feature(spec.spec_id, [], checks(*STANDARD_CHECKS), config=config, root=tmp)
