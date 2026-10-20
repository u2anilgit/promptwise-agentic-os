"""amend_check needs a one-shot operator grant (spec.amend_requires_grant, default on) unless the caller
is the operator acting directly (CLI: require_grant=False). An agent cannot rewrite its own checks unattended."""
import pytest

from core.policy.jit import check_jit_grant, grant_jit_permission
from core.spec.engine import amend_check, amend_grant_scope, complete_task, plan_feature, specify_feature, tasks_feature
from core.spec.models import AcceptanceCheck

from .conftest import REQS, STANDARD_CHECKS, audit_records, checks, interactive_tasks


def _tasked(project):
    tmp, config = project
    config["verify"]["test_command"] = 'python -c "pass"'
    config["spec"]["amend_requires_grant"] = True
    config.setdefault("policy", {})["jit_grants_path"] = str(tmp / "grants.json")
    spec = specify_feature("add login", list(REQS), config=config, root=tmp)
    plan_feature(spec.spec_id, "x", config=config, root=tmp)
    tasks_feature(spec.spec_id, interactive_tasks(), checks(*STANDARD_CHECKS), config=config, root=tmp)
    return spec.spec_id


def _amend(project, spec_id, **kwargs):
    tmp, config = project
    return amend_check(spec_id, "R1", AcceptanceCheck(requirement_id="R1", command="python check_login.py", files=["check_login.py"], expect_baseline="pass"),
                       reason="revised", config=config, root=tmp, **kwargs)


def test_amend_without_a_grant_is_refused_and_audited(project):
    spec_id = _tasked(project)
    with pytest.raises(ValueError, match="grant"):
        _amend(project, spec_id)
    denied = [r for r in audit_records(project[0]) if r["action"] == "amend_check" and r["result"] == "deny"]
    assert denied and denied[-1]["detail"]["reason"] == "amend_requires_grant"


def test_a_grant_allows_exactly_one_amend(project):
    spec_id = _tasked(project)
    grant_jit_permission(project[1], amend_grant_scope(spec_id), 300)
    _amend(project, spec_id)
    assert not check_jit_grant(project[1], amend_grant_scope(spec_id))
    with pytest.raises(ValueError, match="grant"):
        _amend(project, spec_id)


def test_a_grant_for_another_spec_does_not_count(project):
    spec_id = _tasked(project)
    grant_jit_permission(project[1], amend_grant_scope("other"), 300)
    with pytest.raises(ValueError, match="grant"):
        _amend(project, spec_id)


def test_operator_acting_directly_needs_no_grant(project):
    spec_id = _tasked(project)
    assert _amend(project, spec_id, require_grant=False).requirement_id == "R1"


def test_operator_can_switch_the_requirement_off(project):
    spec_id = _tasked(project)
    project[1]["spec"]["amend_requires_grant"] = False
    assert _amend(project, spec_id).requirement_id == "R1"


def test_a_failed_amend_keeps_the_grant(project):
    spec_id = _tasked(project)
    grant_jit_permission(project[1], amend_grant_scope(spec_id), 300)
    tmp, config = project
    with pytest.raises(ValueError):
        amend_check(spec_id, "R1", AcceptanceCheck(requirement_id="R1", command="python missing.py", files=["missing.py"]),
                    reason="x", config=config, root=tmp)
    assert check_jit_grant(config, amend_grant_scope(spec_id))
    assert complete_task(spec_id, "t1", "e", config=config, root=tmp).accepted


def test_grant_survives_when_the_amend_audit_cannot_be_written(project, monkeypatch):
    from core.spec import engine

    spec_id = _tasked(project)
    grant_jit_permission(project[1], amend_grant_scope(spec_id), 300)
    real = engine._audit

    def audit(config, action, *args, **kwargs):
        if action == "amend_check" and kwargs.get("result", "allow") == "allow":
            raise OSError("audit log unwritable")
        return real(config, action, *args, **kwargs)

    monkeypatch.setattr(engine, "_audit", audit)
    with pytest.raises(OSError):
        _amend(project, spec_id)
    assert check_jit_grant(project[1], amend_grant_scope(spec_id))


def test_operator_direct_amend_is_marked_in_the_audit(project):
    spec_id = _tasked(project)
    _amend(project, spec_id, require_grant=False)
    entry = [r for r in audit_records(project[0]) if r["action"] == "amend_check" and r["result"] == "allow"][-1]
    assert entry["detail"]["operator_direct"] is True and entry["detail"]["granted"] is False
