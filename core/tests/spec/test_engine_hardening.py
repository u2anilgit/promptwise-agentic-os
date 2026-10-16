"""Findings from the whole-branch review of spec-engine v2 (each reproduced RED first)."""
import pytest
from sqlalchemy import text

from core.db.base import make_engine, session_scope
from core.spec import store
from core.spec.engine import (
    amend_check,
    complete_task,
    plan_feature,
    specify_feature,
    tasks_feature,
    verify_feature,
)
from core.spec.models import AcceptanceCheck, TaskNode

from .conftest import REQS, STANDARD_CHECKS, audit_records, checks, interactive_tasks

GROUNDED = 'python -c "pass"'


def _planned(project, test_command=GROUNDED):
    tmp, config = project
    config["verify"]["test_command"] = test_command
    spec = specify_feature("add login", list(REQS), config=config, root=tmp)
    plan_feature(spec.spec_id, "just do it", config=config, root=tmp)
    return spec.spec_id


def _tasked(project, check_list=None, tasks=None):
    tmp, config = project
    spec_id = _planned(project)
    tasks_feature(spec_id, tasks or interactive_tasks(), check_list or checks(*STANDARD_CHECKS), config=config, root=tmp)
    return spec_id


def _all_checks_with(**override):
    first = checks(*STANDARD_CHECKS)[0].model_copy(update=override)
    return [first, checks(*STANDARD_CHECKS)[1]]


# C1 — a blank command must never count as a passed check
def test_blank_check_command_is_rejected_at_freeze(project):
    tmp, config = project
    spec_id = _planned(project)
    with pytest.raises(ValueError, match="empty command"):
        tasks_feature(spec_id, interactive_tasks(), _all_checks_with(command="  "), config=config, root=tmp)


def test_blank_command_is_rejected_by_amend_check(project):
    tmp, config = project
    spec_id = _tasked(project)
    bad = AcceptanceCheck(requirement_id="R1", command="", files=["check_login.py"])
    with pytest.raises(ValueError, match="empty command"):
        amend_check(spec_id, "R1", bad, reason="x", config=config, root=tmp)


# C2 — every task must be tied to at least one requirement (and so to a check)
def test_task_without_requirement_ids_is_rejected(project):
    tmp, config = project
    spec_id = _planned(project)
    tasks = [TaskNode(id="t1", requirement_ids=["R1", "R2"]), TaskNode(id="t0")]
    with pytest.raises(ValueError, match="t0"):
        tasks_feature(spec_id, tasks, checks(*STANDARD_CHECKS), config=config, root=tmp)


# I1 — amending a check invalidates work that relied on the old one
def test_amend_check_resets_done_tasks_and_the_verified_stage(project):
    tmp, config = project
    spec_id = _tasked(project)
    for task_id in ("t1", "t2"):
        assert complete_task(spec_id, task_id, "e", config=config, root=tmp).accepted
    assert verify_feature(spec_id, config=config, root=tmp).verified

    (tmp / "check_login.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    amend_check(spec_id, "R1", AcceptanceCheck(requirement_id="R1", command="python check_login.py", files=["check_login.py"]),
                reason="tightened", config=config, root=tmp)

    with session_scope(config, tmp) as s:
        statuses = {t.task_id: t.status for t in store.get_tasks(s, spec_id)}
        assert store.get_stage(s, spec_id) == "implementing"
    assert statuses == {"t1": "pending", "t2": "done"}
    assert not verify_feature(spec_id, config=config, root=tmp).verified
    entry = next(r for r in audit_records(tmp) if r["action"] == "amend_check")
    assert entry["detail"]["tasks_reset"] == ["t1"]


# I4 — an unparsable command is rejected up front and never raises later
def test_unparsable_check_command_is_rejected_at_freeze(project):
    tmp, config = project
    spec_id = _planned(project)
    with pytest.raises(ValueError, match="parse"):
        tasks_feature(spec_id, interactive_tasks(), _all_checks_with(command='python -c "pass'), config=config, root=tmp)


def test_run_command_returns_a_failed_result_for_an_unparsable_command(tmp_path):
    from core.verify.runners import run_command

    result = run_command("t", 'python -c "pass', tmp_path)
    assert result.passed is False and result.ran is True


# I5 — a check must name at least one file, or it can be silently edited
def test_check_without_files_is_rejected_unless_explicitly_allowed(project):
    tmp, config = project
    spec_id = _planned(project)
    fileless = _all_checks_with(files=[])
    with pytest.raises(ValueError, match="at least one file"):
        tasks_feature(spec_id, interactive_tasks(), fileless, config=config, root=tmp)
    config["spec"]["allow_fileless_checks"] = True
    tasks_feature(spec_id, interactive_tasks(), fileless, config=config, root=tmp)


def test_unreferenced_check_files_are_flagged_in_the_audit(project):
    tmp, config = project
    spec_id = _planned(project)
    tasks_feature(spec_id, interactive_tasks(), _all_checks_with(command='python -c "pass"'), config=config, root=tmp)
    entry = next(r for r in audit_records(tmp) if r["action"] == "tasks")
    assert entry["detail"]["unreferenced_check_files"] == ["R1"]


# I2 — agent-supplied commands are policy-gated (goal 4)
def test_check_command_denied_by_policy_rejects_the_task_and_audits_it(project):
    tmp, config = project
    spec_id = _tasked(project)
    (tmp / "policies" / "allow.yaml").write_text("rules: []\n", encoding="utf-8")
    result = complete_task(spec_id, "t1", "e", config=config, root=tmp)
    assert not result.accepted
    assert result.reasons == ["policy_denied:R1"]
    entry = [r for r in audit_records(tmp) if r["action"] == "complete_task"][-1]
    assert entry["result"] == "deny"
    assert entry["detail"]["denied_actions"] == ["shell:run:python"]


def test_policy_enforcement_can_be_disabled_explicitly(project):
    tmp, config = project
    spec_id = _tasked(project)
    (tmp / "policies" / "allow.yaml").write_text("rules: []\n", encoding="utf-8")
    config["spec"]["enforce_command_policy"] = False
    assert complete_task(spec_id, "t1", "e", config=config, root=tmp).accepted


# Review M1 (mcp-exposure) — check files must stay inside the project root
def test_check_files_outside_the_project_root_are_rejected(project):
    tmp, config = project
    outside = tmp.parent / f"{tmp.name}-outside.py"
    outside.write_text("print('x')\n", encoding="utf-8")
    spec_id = _planned(project)
    for bad in (f"../{outside.name}", str(outside)):
        with pytest.raises(ValueError, match="outside the project root"):
            tasks_feature(spec_id, interactive_tasks(), _all_checks_with(command=f"python {bad}", files=[bad]), config=config, root=tmp)


def test_amend_check_rejects_files_outside_the_project_root(project):
    tmp, config = project
    spec_id = _tasked(project)
    outside = tmp.parent / f"{tmp.name}-outside2.py"
    outside.write_text("print('x')\n", encoding="utf-8")
    bad = AcceptanceCheck(requirement_id="R1", command=f"python ../{outside.name}", files=[f"../{outside.name}"])
    with pytest.raises(ValueError, match="outside the project root"):
        amend_check(spec_id, "R1", bad, reason="x", config=config, root=tmp)


# M1 (promoted) — database newer than the code is a clear ValueError, not an Alembic traceback
def test_database_newer_than_code_raises_a_clear_value_error(project):
    tmp, config = project
    specify_feature("x", [REQS[0]], config=config, root=tmp)  # creates + migrates the DB
    with make_engine(config, tmp).begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num = 'zz_future'"))
    with pytest.raises(ValueError, match="newer than this code"):
        specify_feature("y", [REQS[0]], config=config, root=tmp)
