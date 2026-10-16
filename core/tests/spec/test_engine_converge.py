import pytest
from sqlalchemy import update

from core.db.base import session_scope
from core.spec import store
from core.spec.engine import (
    complete_task,
    converge_feature,
    plan_feature,
    specify_feature,
    tasks_feature,
    verify_feature,
)
from core.spec.models import TaskNode
from core.spec.tables import RequirementRow

from .conftest import REQS, STANDARD_CHECKS, checks, interactive_tasks

GROUNDED = 'python -c "pass"'


def _tasked(project, tasks=None):
    tmp, config = project
    config["verify"]["test_command"] = GROUNDED
    spec = specify_feature("add login", list(REQS), config=config, root=tmp)
    plan_feature(spec.spec_id, "just do it", config=config, root=tmp)
    tasks_feature(spec.spec_id, tasks or interactive_tasks(), checks(*STANDARD_CHECKS), config=config, root=tmp)
    return spec.spec_id


def _complete_all(project, spec_id, ids=("t1", "t2")):
    for task_id in ids:
        assert complete_task(spec_id, task_id, "done", config=project[1], root=project[0]).accepted


def _stage(project, spec_id):
    with session_scope(project[1], project[0]) as s:
        return store.get_stage(s, spec_id)


def test_verify_feature_marks_verified_only_when_all_done_and_covered(project):
    tmp, config = project
    spec_id = _tasked(project)
    _complete_all(project, spec_id)
    result = verify_feature(spec_id, config=config, root=tmp)
    assert result.verified and result.outstanding == [] and result.uncovered_requirements == []
    assert _stage(project, spec_id) == "verified"


def test_verify_feature_lists_outstanding_tasks_and_does_not_raise(project):
    tmp, config = project
    spec_id = _tasked(project)
    _complete_all(project, spec_id, ids=("t1",))
    result = verify_feature(spec_id, config=config, root=tmp)
    assert not result.verified and result.outstanding == ["t2"]
    assert _stage(project, spec_id) == "implementing"


def test_verify_feature_reports_requirements_no_done_task_covers(project):
    tmp, config = project
    spec_id = _tasked(project, tasks=[TaskNode(id="t1", requirement_ids=["R1"]), TaskNode(id="t2")])
    _complete_all(project, spec_id)
    result = verify_feature(spec_id, config=config, root=tmp)
    assert not result.verified and result.uncovered_requirements == ["R2"]


def test_verify_and_converge_reject_unknown_specs_and_early_stages(project):
    tmp, config = project
    for verb in (verify_feature, converge_feature):
        with pytest.raises(ValueError, match="unknown spec"):
            verb("ghost", config=config, root=tmp)
    early = specify_feature("x", [REQS[0]], config=config, root=tmp).spec_id
    for verb in (verify_feature, converge_feature):
        with pytest.raises(ValueError, match="stage"):
            verb(early, config=config, root=tmp)


def test_converge_on_a_fresh_consistent_spec_is_not_stale(project):
    spec_id = _tasked(project)
    report = converge_feature(spec_id, config=project[1], root=project[0])
    assert report.stale is False and report.reasons == []
    assert (report.planned_tasks, report.done_tasks, report.pending_tasks) == (2, 0, 2)


def test_converge_is_read_only(project):
    spec_id = _tasked(project)
    converge_feature(spec_id, config=project[1], root=project[0])
    with session_scope(project[1], project[0]) as s:
        assert {t.status for t in store.get_tasks(s, spec_id)} == {"pending"}


def test_converge_counts_done_and_pending(project):
    spec_id = _tasked(project)
    _complete_all(project, spec_id, ids=("t1",))
    report = converge_feature(spec_id, config=project[1], root=project[0])
    assert (report.done_tasks, report.pending_tasks) == (1, 1)


def test_converge_detects_requirements_changed_after_planning(project):
    tmp, config = project
    spec_id = _tasked(project)
    with session_scope(config, tmp) as s:
        s.execute(update(RequirementRow).where(RequirementRow.spec_id == spec_id, RequirementRow.req_id == "R1").values(text="The system shall do something else."))
    report = converge_feature(spec_id, config=config, root=tmp)
    assert report.stale and "requirements_changed" in report.reasons


def test_converge_detects_changed_and_missing_check_files(project):
    tmp, config = project
    spec_id = _tasked(project)
    (tmp / "check_login.py").write_text("import sys\nsys.exit(0)  # edited\n", encoding="utf-8")
    (tmp / "check_logout.py").unlink()
    report = converge_feature(spec_id, config=config, root=tmp)
    assert "check_file_changed:check_login.py" in report.reasons
    assert "check_file_missing:check_logout.py" in report.reasons
    assert report.stale


def test_converge_detects_a_requirement_no_task_covers(project):
    spec_id = _tasked(project, tasks=[TaskNode(id="t1", requirement_ids=["R1"])])
    report = converge_feature(spec_id, config=project[1], root=project[0])
    assert "requirement_uncovered:R2" in report.reasons


def test_converge_detects_missing_expected_symbols_via_the_code_index(project):
    tmp, config = project
    (tmp / "auth.py").write_text("def login_user():\n    return True\n", encoding="utf-8")
    tasks = [TaskNode(id="t1", requirement_ids=["R1", "R2"], expected_symbols=["login_user", "logout_user"])]
    spec_id = _tasked(project, tasks=tasks)
    report = converge_feature(spec_id, config=config, root=tmp)
    assert "symbol_missing:logout_user" in report.reasons
    assert "symbol_missing:login_user" not in report.reasons
