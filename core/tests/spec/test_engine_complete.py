import time

import pytest

from core.db.base import session_scope
from core.spec import store
from core.spec.engine import amend_check, complete_task, plan_feature, specify_feature, tasks_feature
from core.spec.models import AcceptanceCheck

from .conftest import REQS, STANDARD_CHECKS, audit_records, checks, interactive_tasks

GROUNDED = 'python -c "pass"'


def _tasked(project, test_command=GROUNDED, tasks=None, pre=None, check_list=None):
    tmp, config = project
    config["verify"]["test_command"] = test_command
    if pre:
        pre(tmp)
    spec = specify_feature("add login", list(REQS), config=config, root=tmp)
    plan_feature(spec.spec_id, "just do it", config=config, root=tmp)
    tasks_feature(spec.spec_id, tasks or interactive_tasks(), check_list or checks(*STANDARD_CHECKS), config=config, root=tmp)
    return spec.spec_id


def _complete(project, spec_id, task_id):
    tmp, config = project
    return complete_task(spec_id, task_id, "implemented it", config=config, root=tmp)


def _status(project, spec_id, task_id):
    tmp, config = project
    with session_scope(config, tmp) as s:
        return next(t.status for t in store.get_tasks(s, spec_id) if t.task_id == task_id)


def test_task_is_accepted_when_checks_pass_and_the_gate_is_grounded(project):
    spec_id = _tasked(project)
    result = _complete(project, spec_id, "t1")
    assert result.accepted and result.reasons == []
    assert _status(project, spec_id, "t1") == "done"
    with session_scope(project[1], project[0]) as s:
        assert store.get_stage(s, spec_id) == "implementing"


def test_completing_an_already_done_task_is_idempotent(project):
    spec_id = _tasked(project)
    _complete(project, spec_id, "t1")
    assert _complete(project, spec_id, "t1").accepted


def test_ungrounded_verification_is_rejected_unless_explicitly_allowed(project):
    spec_id = _tasked(project, test_command="")
    result = _complete(project, spec_id, "t1")
    assert not result.accepted
    assert "ungrounded_verification" in result.reasons
    assert _status(project, spec_id, "t1") == "pending"

    project[1]["spec"]["allow_ungrounded"] = True
    assert _complete(project, spec_id, "t1").accepted


def test_editing_a_frozen_check_file_rejects_the_task(project):
    spec_id = _tasked(project)
    (project[0] / "check_login.py").write_text("import sys\nsys.exit(0)  # weakened\n", encoding="utf-8")
    result = _complete(project, spec_id, "t1")
    assert not result.accepted
    assert any(r.startswith("acceptance_check_modified") for r in result.reasons)
    assert _status(project, spec_id, "t1") == "pending"


def test_deleting_a_frozen_check_file_rejects_the_task(project):
    spec_id = _tasked(project)
    (project[0] / "check_login.py").unlink()
    result = _complete(project, spec_id, "t1")
    assert any(r.startswith("acceptance_check_modified") for r in result.reasons)


def test_amend_check_is_audited_and_unblocks_the_task(project):
    tmp, config = project
    spec_id = _tasked(project)
    (tmp / "check_login.py").write_text("import sys\nsys.exit(0)  # legitimately updated\n", encoding="utf-8")
    new = amend_check(
        spec_id, "R1", AcceptanceCheck(requirement_id="R1", command="python check_login.py", files=["check_login.py"], expect_baseline="pass"),
        reason="login flow changed after review", config=config, root=tmp,
    )
    assert new.file_hashes["check_login.py"]
    entry = next(r for r in audit_records(tmp) if r["action"] == "amend_check")
    assert entry["detail"]["reason"] == "login flow changed after review"
    assert entry["detail"]["old_hashes"] != entry["detail"]["new_hashes"]
    assert _complete(project, spec_id, "t1").accepted


def test_amend_check_validates_its_input(project):
    tmp, config = project
    spec_id = _tasked(project)
    good = AcceptanceCheck(requirement_id="R1", command="python check_login.py", files=["check_login.py"], expect_baseline="pass")
    with pytest.raises(ValueError, match="reason"):
        amend_check(spec_id, "R1", good, reason="  ", config=config, root=tmp)
    with pytest.raises(ValueError, match="requirement"):
        amend_check(spec_id, "R2", good, reason="x", config=config, root=tmp)
    with pytest.raises(ValueError, match="no frozen check"):
        amend_check(spec_id, "R9", good.model_copy(update={"requirement_id": "R9"}), reason="x", config=config, root=tmp)
    with pytest.raises(ValueError, match="nope.py"):
        amend_check(spec_id, "R1", good.model_copy(update={"files": ["nope.py"]}), reason="x", config=config, root=tmp)


def test_a_failing_acceptance_check_rejects_the_task(project):
    spec_id = _tasked(project, pre=lambda tmp: (tmp / "check_login.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8"),
                      check_list=checks(("R1", "check_login.py", "fail"), ("R2", "check_logout.py")))
    result = _complete(project, spec_id, "t1")
    assert not result.accepted
    assert "acceptance_check_failed:R1" in result.reasons
    assert _status(project, spec_id, "t1") == "pending"


def test_a_failing_verify_gate_rejects_the_task(project):
    spec_id = _tasked(project, test_command='python -c "import sys; sys.exit(1)"')
    result = _complete(project, spec_id, "t1")
    assert "verify_gate_failed" in result.reasons
    assert result.verify is not None and result.verify.passed is False


def test_a_hanging_check_times_out_without_raising(project):
    project[1]["spec"]["check_timeout_seconds"] = 1
    spec_id = _tasked(project, pre=lambda tmp: (tmp / "check_login.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8"),
                      check_list=checks(("R1", "check_login.py", "fail"), ("R2", "check_logout.py")))
    started = time.monotonic()
    result = _complete(project, spec_id, "t1")
    assert time.monotonic() - started < 20
    assert "acceptance_check_failed:R1" in result.reasons


def test_task_is_rejected_while_a_dependency_is_not_done(project):
    spec_id = _tasked(project)
    result = _complete(project, spec_id, "t2")
    assert result.reasons == ["dependency_not_done"]
    _complete(project, spec_id, "t1")
    assert _complete(project, spec_id, "t2").accepted


def test_rejections_and_acceptances_are_audited(project):
    spec_id = _tasked(project, test_command="")
    _complete(project, spec_id, "t1")
    entry = [r for r in audit_records(project[0]) if r["action"] == "complete_task"][-1]
    assert entry["result"] == "deny" and "ungrounded_verification" in entry["detail"]["reasons"]
    project[1]["spec"]["allow_ungrounded"] = True
    _complete(project, spec_id, "t1")
    assert [r for r in audit_records(project[0]) if r["action"] == "complete_task"][-1]["result"] == "allow"


def test_unknown_spec_unknown_task_and_early_stage_raise_value_error(project):
    tmp, config = project
    with pytest.raises(ValueError, match="unknown spec"):
        complete_task("ghost", "t1", "e", config=config, root=tmp)
    spec_id = _tasked(project)
    with pytest.raises(ValueError, match="unknown task"):
        _complete(project, spec_id, "ghost")
    early = specify_feature("x", [REQS[0]], config=config, root=tmp).spec_id
    with pytest.raises(ValueError, match="stage"):
        complete_task(early, "t1", "e", config=config, root=tmp)
