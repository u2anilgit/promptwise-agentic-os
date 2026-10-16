"""Rulings 2 and 3 in the spec engine: operator-required mutation / reviewer layers."""
import json

from core.spec.engine import complete_task, plan_feature, specify_feature, tasks_feature
from core.spec.models import AcceptanceCheck, TaskNode

PASS = 'python -c "pass"'
FAIL = 'python -c "import sys; sys.exit(3)"'


def _red_to_green(project, **verify):
    """One requirement with a genuinely red check, then 'implemented' (marker present)."""
    tmp, config = project
    config["verify"].update({"test_command": PASS, **verify})
    (tmp / "check_a.py").write_text("import sys, pathlib\nsys.exit(0 if pathlib.Path('a.done').exists() else 1)\n", encoding="utf-8")
    spec = specify_feature("do A", ["The system shall do A."], config=config, root=tmp)
    plan_feature(spec.spec_id, "just do it", config=config, root=tmp)
    check = AcceptanceCheck(requirement_id="R1", command="python check_a.py", files=["check_a.py"])
    tasks_feature(spec.spec_id, [TaskNode(id="t1", requirement_ids=["R1"])], [check], config=config, root=tmp)
    (tmp / "a.done").write_text("x", encoding="utf-8")
    return spec.spec_id


def test_require_mutation_rejects_a_task_when_no_mutation_command_ran(project):
    tmp, config = project
    config["spec"]["require_mutation"] = True
    spec_id = _red_to_green(project)
    result = complete_task(spec_id, "t1", "e", config=config, root=tmp)
    assert not result.accepted and result.reasons == ["mutation_not_run"]


def test_require_mutation_accepts_when_the_mutation_command_passed_and_reports_it(project):
    tmp, config = project
    config["spec"]["require_mutation"] = True
    spec_id = _red_to_green(project, mutation_command=PASS)
    result = complete_task(spec_id, "t1", "e", config=config, root=tmp)
    assert result.accepted and result.independence == {"baseline_red": True, "mutation": True, "reviewer": False}


def test_a_failing_mutation_command_rejects_the_task_through_the_gate(project):
    tmp, config = project
    spec_id = _red_to_green(project, mutation_command=FAIL)
    result = complete_task(spec_id, "t1", "e", config=config, root=tmp)
    assert not result.accepted and "verify_gate_failed" in result.reasons


def _reviewer(tmp, name, body):
    (tmp / name).write_text(body, encoding="utf-8")
    return f"python {name}"


APPROVE = "import json, sys\nsys.stdin.read()\nprint(json.dumps({'approved': True, 'reasons': ['matches R1']}))\n"
REJECT = "import json, sys\nsys.stdin.read()\nprint(json.dumps({'approved': False, 'reasons': ['does not handle empty input']}))\n"


def test_an_approving_reviewer_accepts_and_is_reported(project):
    tmp, config = project
    spec_id = _red_to_green(project, reviewer_command=_reviewer(tmp, "approve.py", APPROVE))
    result = complete_task(spec_id, "t1", "e", config=config, root=tmp)
    assert result.accepted and result.independence["reviewer"] is True


def test_a_rejecting_reviewer_blocks_the_task_and_explains_why(project):
    tmp, config = project
    spec_id = _red_to_green(project, reviewer_command=_reviewer(tmp, "reject.py", REJECT))
    result = complete_task(spec_id, "t1", "e", config=config, root=tmp)
    assert not result.accepted and result.reasons == ["reviewer_rejected"]
    assert result.notes == ["does not handle empty input"]


def test_a_broken_reviewer_fails_closed(project):
    tmp, config = project
    spec_id = _red_to_green(project, reviewer_command=_reviewer(tmp, "broken.py", "print('oops')\n"))
    result = complete_task(spec_id, "t1", "e", config=config, root=tmp)
    assert not result.accepted and result.reasons == ["reviewer_failed"] and result.notes


def test_require_reviewer_rejects_when_none_is_configured(project):
    tmp, config = project
    config["spec"]["require_reviewer"] = True
    spec_id = _red_to_green(project)
    result = complete_task(spec_id, "t1", "e", config=config, root=tmp)
    assert not result.accepted and result.reasons == ["reviewer_not_configured"]


def test_reviewer_receives_the_requirements_the_task_covers_and_the_evidence(project):
    tmp, config = project
    spy = "import json, sys\nd = json.load(sys.stdin)\nopen('payload.json', 'w').write(json.dumps(d))\nprint(json.dumps({'approved': True}))\n"
    spec_id = _red_to_green(project, reviewer_command=_reviewer(tmp, "spy.py", spy))
    complete_task(spec_id, "t1", "my evidence", config=config, root=tmp)
    payload = json.loads((tmp / "payload.json").read_text(encoding="utf-8"))
    assert payload["spec_id"] == spec_id and payload["task_id"] == "t1" and payload["evidence"] == "my evidence"
    assert payload["requirements"] == [{"id": "R1", "text": "The system shall do A."}]
    assert payload["checks"][0]["requirement_id"] == "R1" and payload["checks"][0]["passed"] is True


def test_every_layer_together_is_reported(project):
    tmp, config = project
    config["spec"].update({"require_mutation": True, "require_reviewer": True})
    spec_id = _red_to_green(project, mutation_command=PASS, reviewer_command=_reviewer(tmp, "approve.py", APPROVE))
    result = complete_task(spec_id, "t1", "e", config=config, root=tmp)
    assert result.accepted and result.independence == {"baseline_red": True, "mutation": True, "reviewer": True}


def test_mutation_is_optional_by_default(project):
    tmp, config = project
    spec_id = _red_to_green(project)
    result = complete_task(spec_id, "t1", "e", config=config, root=tmp)
    assert result.accepted and result.independence["mutation"] is False
