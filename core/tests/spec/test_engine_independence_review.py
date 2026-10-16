"""Findings from the adversarial review of feat/independent-verification (each reproduced RED first)."""
import json

import pytest
from sqlalchemy import text

from core.db.base import make_engine
from core.spec.engine import amend_check, complete_task, plan_feature, specify_feature, tasks_feature
from core.spec.models import AcceptanceCheck, TaskNode

from .conftest import audit_records

PASS = 'python -c "pass"'
RED = "import sys, pathlib\nsys.exit(0 if pathlib.Path('a.done').exists() else 1)\n"
APPROVE = "import json, sys\nsys.stdin.read()\nprint(json.dumps({'approved': True, 'reasons': ['ok']}))\n"
REJECT = "import json, sys\nsys.stdin.read()\nprint(json.dumps({'approved': False, 'reasons': ['no']}))\n"


def _setup(project, check_body=RED, **verify):
    tmp, config = project
    config["verify"].update({"test_command": PASS, **verify})
    (tmp / "check_a.py").write_text(check_body, encoding="utf-8")
    spec = specify_feature("do A", ["The system shall do A."], config=config, root=tmp)
    plan_feature(spec.spec_id, "x", config=config, root=tmp)
    return spec.spec_id


def _chk(**kw):
    return AcceptanceCheck(requirement_id="R1", command="python check_a.py", files=["check_a.py"], **kw)


def _freeze(project, spec_id, **kw):
    tmp, config = project
    return tasks_feature(spec_id, [TaskNode(id="t1", requirement_ids=["R1"])], [_chk(**kw)], config=config, root=tmp)


# ---- C1: a check that behaves differently the second time is not a proven red ----
def test_a_check_that_arms_itself_inside_the_project_is_rejected(project):
    armed = "import sys, pathlib\np = pathlib.Path('.armed')\nif p.exists():\n    sys.exit(0)\np.write_text('x')\nsys.exit(1)\n"
    spec_id = _setup(project, armed)
    with pytest.raises(ValueError, match="wrote to the project tree"):
        _freeze(project, spec_id)


def test_a_check_that_arms_itself_outside_the_project_is_rejected_as_unstable(project):
    tmp, _ = project
    marker = (tmp.parent / f"{tmp.name}-armed").as_posix()
    armed = f"import sys, pathlib\np = pathlib.Path({marker!r})\nif p.exists():\n    sys.exit(0)\np.write_text('x')\nsys.exit(1)\n"
    spec_id = _setup(project, armed)
    with pytest.raises(ValueError, match="unstable"):
        _freeze(project, spec_id)


# ---- I1: infrastructure failures are not "red" ----
def test_a_missing_program_is_not_accepted_as_a_red_baseline(project):
    tmp, config = project
    spec_id = _setup(project)
    bad = AcceptanceCheck(requirement_id="R1", command="definitely-not-a-program check_a.py", files=["check_a.py"])
    (tmp / "policies" / "allow.yaml").write_text("rules:\n  - action: 'shell:run:*'\n    effect: allow\n", encoding="utf-8")
    with pytest.raises(ValueError, match="could not be executed"):
        tasks_feature(spec_id, [TaskNode(id="t1", requirement_ids=["R1"])], [bad], config=config, root=tmp)


def test_a_timeout_is_not_accepted_as_a_red_baseline(project):
    tmp, config = project
    config["spec"]["check_timeout_seconds"] = 1
    spec_id = _setup(project, "import time\ntime.sleep(60)\n")
    with pytest.raises(ValueError, match="timed out"):
        _freeze(project, spec_id)


# ---- I2: the operator can forbid regression guards ----
def test_operator_can_forbid_regression_guards_at_freeze_and_amend(project):
    tmp, config = project
    config["spec"]["allow_regression_guards"] = False
    (tmp / "a.done").write_text("x", encoding="utf-8")
    spec_id = _setup(project)
    with pytest.raises(ValueError, match="regression guards are not allowed"):
        _freeze(project, spec_id, expect_baseline="pass")
    (tmp / "a.done").unlink()
    _freeze(project, spec_id)  # a genuine red check is still fine
    (tmp / "check_b.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    guard = AcceptanceCheck(requirement_id="R1", command="python check_b.py", files=["check_b.py"], expect_baseline="pass")
    with pytest.raises(ValueError, match="regression guards are not allowed"):
        amend_check(spec_id, "R1", guard, reason="turn it into a guard", config=config, root=tmp)


# ---- I3: the baseline decisions are audited, including refusals ----
def test_amend_and_tasks_audit_record_the_baseline_decision(project):
    tmp, config = project
    spec_id = _setup(project)
    _freeze(project, spec_id)
    (tmp / "check_b.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    guard = AcceptanceCheck(requirement_id="R1", command="python check_b.py", files=["check_b.py"], expect_baseline="pass")
    amend_check(spec_id, "R1", guard, reason="now a guard", config=config, root=tmp)
    records = audit_records(tmp)
    tasks_entry = next(r for r in records if r["action"] == "tasks")
    amend_entry = next(r for r in records if r["action"] == "amend_check")
    assert tasks_entry["detail"]["expect_baselines"] == {"R1": "fail"}
    assert amend_entry["detail"]["old_expect_baseline"] == "fail" and amend_entry["detail"]["new_expect_baseline"] == "pass"
    assert amend_entry["detail"]["old_baseline"] == "failed" and amend_entry["detail"]["new_baseline"] == "passed"


def test_a_refused_baseline_is_audited(project):
    tmp, config = project
    spec_id = _setup(project, "import sys\nsys.exit(0)\n")
    with pytest.raises(ValueError):
        _freeze(project, spec_id)
    refusal = next(r for r in audit_records(tmp) if r["action"] == "baseline_rejected")
    assert refusal["result"] == "deny" and refusal["detail"]["requirement_id"] == "R1" and "already passes" in refusal["detail"]["reason"]


# ---- M1: amend validates before it executes anything ----
def test_amend_does_not_run_the_command_for_an_unknown_spec(project):
    tmp, config = project
    spy = "import pathlib\npathlib.Path('ran.txt').write_text('x')\nimport sys\nsys.exit(1)\n"
    (tmp / "spy.py").write_text(spy, encoding="utf-8")
    check = AcceptanceCheck(requirement_id="R1", command="python spy.py", files=["spy.py"])
    with pytest.raises(ValueError, match="unknown spec"):
        amend_check("ghost", "R1", check, reason="x", config=config, root=tmp)
    assert not (tmp / "ran.txt").exists()


# ---- C2: the agent-chosen cwd cannot replace the operator's reviewer or mutation program ----
def test_agent_chosen_cwd_cannot_swap_the_reviewer(project):
    tmp, config = project
    spec_id = _setup(project, reviewer_command="python reviewer.py")
    (tmp / "reviewer.py").write_text(REJECT, encoding="utf-8")
    (tmp / "evil").mkdir()
    (tmp / "evil" / "reviewer.py").write_text(APPROVE, encoding="utf-8")
    _freeze(project, spec_id)
    (tmp / "a.done").write_text("x", encoding="utf-8")
    result = complete_task(spec_id, "t1", "e", cwd=tmp / "evil", config=config, root=tmp)
    assert not result.accepted and result.reasons == ["reviewer_rejected"]


def test_agent_chosen_cwd_cannot_swap_the_mutation_program(project):
    tmp, config = project
    spec_id = _setup(project, mutation_command="python mut.py")
    (tmp / "mut.py").write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
    (tmp / "evil").mkdir()
    (tmp / "evil" / "mut.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    _freeze(project, spec_id)
    (tmp / "a.done").write_text("x", encoding="utf-8")
    result = complete_task(spec_id, "t1", "e", cwd=tmp / "evil", config=config, root=tmp)
    assert not result.accepted and "verify_gate_failed" in result.reasons


# ---- I4: the reviewer sees the check sources and a hash of the evidence; evidence is flagged untrusted ----
def test_reviewer_payload_includes_check_sources_hashes_and_untrusted_evidence(project):
    tmp, config = project
    spy = "import json, sys\nd = json.load(sys.stdin)\nopen('payload.json', 'w').write(json.dumps(d))\nprint(json.dumps({'approved': True}))\n"
    (tmp / "spy.py").write_text(spy, encoding="utf-8")
    spec_id = _setup(project, reviewer_command="python spy.py")
    _freeze(project, spec_id)
    (tmp / "a.done").write_text("x", encoding="utf-8")
    complete_task(spec_id, "t1", "trust me", config=config, root=tmp)
    payload = json.loads((tmp / "payload.json").read_text(encoding="utf-8"))
    import hashlib

    assert payload["evidence_untrusted"] is True
    assert payload["evidence_sha256"] == hashlib.sha256(b"trust me").hexdigest()
    (check,) = payload["checks"]
    assert check["files"][0]["path"] == "check_a.py" and "a.done" in check["files"][0]["content"]
    assert check["files"][0]["sha256"] == hashlib.sha256((tmp / "check_a.py").read_bytes()).hexdigest()


# ---- M7: ordering and precedence ----
def test_reviewer_is_not_invoked_when_an_earlier_gate_rejects(project):
    tmp, config = project
    spy = "import pathlib, sys, json\nsys.stdin.read()\npathlib.Path('reviewer_ran.txt').write_text('x')\nprint(json.dumps({'approved': True}))\n"
    (tmp / "spy.py").write_text(spy, encoding="utf-8")
    spec_id = _setup(project, reviewer_command="python spy.py")
    _freeze(project, spec_id)  # check is still red (a.done missing)
    result = complete_task(spec_id, "t1", "e", config=config, root=tmp)
    assert not result.accepted and not (tmp / "reviewer_ran.txt").exists()


def test_reviewer_approval_logs_its_reasons(project):
    tmp, config = project
    (tmp / "approve.py").write_text(APPROVE, encoding="utf-8")
    spec_id = _setup(project, reviewer_command="python approve.py")
    _freeze(project, spec_id)
    (tmp / "a.done").write_text("x", encoding="utf-8")
    assert complete_task(spec_id, "t1", "e", config=config, root=tmp).accepted
    entry = [r for r in audit_records(tmp) if r["action"] == "complete_task"][-1]
    assert entry["result"] == "allow" and entry["detail"]["reviewer_reasons"] == ["ok"]


# ---- M9: migration 0003 upgrades legacy rows and downgrades cleanly ----
def test_migration_0003_gives_legacy_rows_unverified_baselines_and_downgrades(tmp_path):
    from alembic import command

    from core.db.migrate import _alembic_config

    cfg = {"database": {"url": f"sqlite:///{(tmp_path / 'm.db').as_posix()}"}}
    engine = make_engine(cfg)
    alembic_cfg = _alembic_config(engine)
    command.upgrade(alembic_cfg, "0002")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO spec VALUES ('s','r','standard',1.0)"))
        conn.execute(text("INSERT INTO acceptance_check (spec_id, requirement_id, command, files, file_hashes, frozen_at) VALUES ('s','R1','c','[]','{}',1.0)"))
    command.upgrade(alembic_cfg, "0003")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT expect_baseline, baseline FROM acceptance_check")).one() == ("fail", "unverified")
    command.downgrade(alembic_cfg, "0002")
    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(acceptance_check)"))}
        assert "baseline" not in columns and conn.execute(text("SELECT count(*) FROM acceptance_check")).scalar() == 1
