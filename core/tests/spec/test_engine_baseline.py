"""Ruling 1 (docs/superpowers/specs/2026-10-17-independent-verification-design.md):
every acceptance check must be seen to fail before the work exists (or be an explicit regression guard)."""
import pytest
from sqlalchemy import text

from core.db.base import make_engine, session_scope
from core.spec import store
from core.spec.engine import amend_check, complete_task, plan_feature, specify_feature, tasks_feature
from core.spec.models import AcceptanceCheck, TaskNode

from .conftest import audit_records

GROUNDED = 'python -c "pass"'
MARKER_CHECK = "import sys, pathlib\nsys.exit(0 if pathlib.Path('{marker}').exists() else 1)\n"


def _red_project(project):
    """A check script that fails until its marker file exists: genuine red -> green."""
    tmp, config = project
    config["verify"]["test_command"] = GROUNDED
    (tmp / "check_a.py").write_text(MARKER_CHECK.format(marker="a.done"), encoding="utf-8")
    return tmp, config


def _planned(tmp, config, reqs=("The system shall do A.",)):
    spec = specify_feature("do A", list(reqs), config=config, root=tmp)
    plan_feature(spec.spec_id, "just do it", config=config, root=tmp)
    return spec.spec_id


def _chk(**kw):
    return AcceptanceCheck(requirement_id="R1", command="python check_a.py", files=["check_a.py"], **kw)


def _tasks():
    return [TaskNode(id="t1", requirement_ids=["R1"])]


def test_a_check_that_already_passes_is_rejected_as_vacuous_by_default(project):
    tmp, config = _red_project(project)
    (tmp / "a.done").write_text("x", encoding="utf-8")  # feature "already exists" -> check passes now
    spec_id = _planned(tmp, config)
    with pytest.raises(ValueError, match="already passes before implementation"):
        tasks_feature(spec_id, _tasks(), [_chk()], config=config, root=tmp)


def test_red_then_green_is_accepted_and_reported_as_independent(project):
    tmp, config = _red_project(project)
    spec_id = _planned(tmp, config)
    result = tasks_feature(spec_id, _tasks(), [_chk()], config=config, root=tmp)
    assert [c.baseline for c in result.frozen] == ["failed"]
    assert complete_task(spec_id, "t1", "e", config=config, root=tmp).accepted is False  # still red
    (tmp / "a.done").write_text("x", encoding="utf-8")  # "implement" the feature
    done = complete_task(spec_id, "t1", "e", config=config, root=tmp)
    assert done.accepted and done.independence["baseline_red"] is True


def test_a_regression_guard_may_pass_before_the_work_when_declared(project):
    tmp, config = _red_project(project)
    (tmp / "a.done").write_text("x", encoding="utf-8")
    spec_id = _planned(tmp, config)
    result = tasks_feature(spec_id, _tasks(), [_chk(expect_baseline="pass")], config=config, root=tmp)
    assert [c.baseline for c in result.frozen] == ["passed"]
    done = complete_task(spec_id, "t1", "e", config=config, root=tmp)
    assert done.accepted and done.independence["baseline_red"] is False


def test_a_declared_regression_guard_that_already_fails_is_rejected(project):
    tmp, config = _red_project(project)
    spec_id = _planned(tmp, config)
    with pytest.raises(ValueError, match="already fails"):
        tasks_feature(spec_id, _tasks(), [_chk(expect_baseline="pass")], config=config, root=tmp)


def test_a_hanging_check_counts_as_a_failed_baseline(project):
    tmp, config = _red_project(project)
    config["spec"]["check_timeout_seconds"] = 1
    (tmp / "check_a.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    spec_id = _planned(tmp, config)
    result = tasks_feature(spec_id, _tasks(), [_chk()], config=config, root=tmp)
    assert [c.baseline for c in result.frozen] == ["failed"]


def test_baseline_commands_are_policy_gated(project):
    tmp, config = _red_project(project)
    (tmp / "policies" / "allow.yaml").write_text("rules: []\n", encoding="utf-8")
    spec_id = _planned(tmp, config)
    with pytest.raises(ValueError, match="policy"):
        tasks_feature(spec_id, _tasks(), [_chk()], config=config, root=tmp)


def test_tasks_audit_records_each_observed_baseline(project):
    tmp, config = _red_project(project)
    spec_id = _planned(tmp, config)
    tasks_feature(spec_id, _tasks(), [_chk()], config=config, root=tmp)
    entry = next(r for r in audit_records(tmp) if r["action"] == "tasks")
    assert entry["detail"]["baselines"] == {"R1": "failed"}


def test_amend_check_applies_the_same_red_before_green_rule(project):
    tmp, config = _red_project(project)
    spec_id = _planned(tmp, config)
    tasks_feature(spec_id, _tasks(), [_chk()], config=config, root=tmp)
    (tmp / "check_b.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")  # passes right now
    vacuous = AcceptanceCheck(requirement_id="R1", command="python check_b.py", files=["check_b.py"])
    with pytest.raises(ValueError, match="already passes before implementation"):
        amend_check(spec_id, "R1", vacuous, reason="swap", config=config, root=tmp)
    guard = vacuous.model_copy(update={"expect_baseline": "pass"})
    amended = amend_check(spec_id, "R1", guard, reason="now a guard", config=config, root=tmp)
    assert amended.baseline == "passed" and amended.expect_baseline == "pass"


def test_a_check_with_no_recorded_baseline_cannot_complete_a_task(project):
    tmp, config = _red_project(project)
    spec_id = _planned(tmp, config)
    tasks_feature(spec_id, _tasks(), [_chk()], config=config, root=tmp)
    (tmp / "a.done").write_text("x", encoding="utf-8")
    with make_engine(config, tmp).begin() as conn:  # simulate a pre-baseline (legacy) row
        conn.execute(text("UPDATE acceptance_check SET baseline = 'unverified'"))
    result = complete_task(spec_id, "t1", "e", config=config, root=tmp)
    assert not result.accepted and result.reasons == ["baseline_not_proven:R1"]


def test_status_shows_each_checks_baseline(project):
    from core.spec.engine import spec_status

    tmp, config = _red_project(project)
    spec_id = _planned(tmp, config)
    tasks_feature(spec_id, _tasks(), [_chk()], config=config, root=tmp)
    checks = spec_status(spec_id, config=config, root=tmp).checks
    assert [(c.requirement_id, c.baseline, c.expect_baseline) for c in checks] == [("R1", "failed", "fail")]
