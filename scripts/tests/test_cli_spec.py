import json

import pytest
from typer.testing import CliRunner

from scripts.promptwise import app

runner = CliRunner()
REQS = ["The system shall log in users.", "The system shall log out users."]


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".promptwise").mkdir()
    (tmp_path / ".promptwise" / "config.yaml").write_text(
        "verify:\n  test_command: 'python -c \"pass\"'\n  lint_command: ''\n", encoding="utf-8"
    )
    (tmp_path / "policies").mkdir()
    (tmp_path / "policies" / "allow.yaml").write_text("rules:\n  - action: 'shell:run:python'\n    effect: allow\n", encoding="utf-8")
    (tmp_path / "check_login.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    (tmp_path / "check_logout.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    (tmp_path / "tasks.json").write_text(json.dumps([
        {"id": "t1", "requirement_ids": ["R1"]},
        {"id": "t2", "requirement_ids": ["R2"], "depends_on": ["t1"]},
    ]), encoding="utf-8")
    (tmp_path / "checks.json").write_text(json.dumps([
        {"requirement_id": "R1", "command": "python check_login.py", "files": ["check_login.py"], "expect_baseline": "pass"},
        {"requirement_id": "R2", "command": "python check_logout.py", "files": ["check_logout.py"], "expect_baseline": "pass"},
    ]), encoding="utf-8")
    return tmp_path


def _specify():
    result = runner.invoke(app, ["spec", "specify", "add login", "-r", REQS[0], "-r", REQS[1]])
    assert result.exit_code == 0, result.stdout
    return next(line.split()[-1] for line in result.stdout.splitlines() if line.startswith("spec_id"))


def test_full_lifecycle_through_the_cli(proj):
    spec_id = _specify()
    assert runner.invoke(app, ["spec", "plan", spec_id, "just do it"]).exit_code == 0
    tasks = runner.invoke(app, ["spec", "tasks", spec_id, "--tasks", "tasks.json", "--checks", "checks.json"])
    assert tasks.exit_code == 0 and "frozen 2 acceptance check(s)" in tasks.stdout
    for task_id in ("t1", "t2"):
        done = runner.invoke(app, ["spec", "complete", spec_id, task_id, "--evidence", "implemented"])
        assert done.exit_code == 0 and "accepted" in done.stdout, done.stdout
    assert runner.invoke(app, ["spec", "verify", spec_id]).exit_code == 0
    converge = runner.invoke(app, ["spec", "converge", spec_id])
    assert converge.exit_code == 0 and "not stale" in converge.stdout
    status = runner.invoke(app, ["spec", "status", spec_id])
    assert "stage: verified" in status.stdout and "t1" in status.stdout


def test_specify_prints_ears_violations_but_succeeds(proj):
    result = runner.invoke(app, ["spec", "specify", "x", "-r", "make it fast"])
    assert result.exit_code == 0 and "EARS" in result.stdout and "R1" in result.stdout


def test_a_rejected_completion_exits_one_and_lists_reasons(proj):
    spec_id = _specify()
    runner.invoke(app, ["spec", "plan", spec_id, "a"])
    runner.invoke(app, ["spec", "tasks", spec_id, "--tasks", "tasks.json", "--checks", "checks.json"])
    (proj / "check_login.py").write_text("import sys\nsys.exit(0)  # edited\n", encoding="utf-8")
    result = runner.invoke(app, ["spec", "complete", spec_id, "t1", "--evidence", "e"])
    assert result.exit_code == 1 and "acceptance_check_modified" in result.stdout


def test_verify_and_converge_exit_nonzero_when_not_ok(proj):
    spec_id = _specify()
    runner.invoke(app, ["spec", "plan", spec_id, "a"])
    runner.invoke(app, ["spec", "tasks", spec_id, "--tasks", "tasks.json", "--checks", "checks.json"])
    assert runner.invoke(app, ["spec", "verify", spec_id]).exit_code == 1
    (proj / "check_logout.py").unlink()
    converge = runner.invoke(app, ["spec", "converge", spec_id])
    assert converge.exit_code == 1 and "check_file_missing:check_logout.py" in converge.stdout


def test_amend_reopens_work(proj):
    spec_id = _specify()
    runner.invoke(app, ["spec", "plan", spec_id, "a"])
    runner.invoke(app, ["spec", "tasks", spec_id, "--tasks", "tasks.json", "--checks", "checks.json"])
    assert runner.invoke(app, ["spec", "complete", spec_id, "t1", "--evidence", "e"]).exit_code == 0
    (proj / "check_login.py").write_text("import sys\nsys.exit(0)  # revised\n", encoding="utf-8")
    amended = runner.invoke(app, ["spec", "amend", spec_id, "R1", "--command", "python check_login.py",
                                  "--file", "check_login.py", "--reason", "flow changed", "--expect-baseline", "pass"])
    assert amended.exit_code == 0 and "reopened: t1" in amended.stdout


def test_errors_are_one_line_with_exit_code_two_and_no_traceback(proj):
    for args in (["spec", "plan", "ghost", "a"], ["spec", "status", "ghost"], ["spec", "verify", "ghost"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 2 and "error: unknown spec" in result.stdout and "Traceback" not in result.stdout


def test_tasks_with_a_missing_or_malformed_json_file_is_a_clean_error(proj):
    spec_id = _specify()
    runner.invoke(app, ["spec", "plan", spec_id, "a"])
    missing = runner.invoke(app, ["spec", "tasks", spec_id, "--tasks", "nope.json", "--checks", "checks.json"])
    assert missing.exit_code == 2 and "error:" in missing.stdout
    (proj / "bad.json").write_text("{not json", encoding="utf-8")
    bad = runner.invoke(app, ["spec", "tasks", spec_id, "--tasks", "bad.json", "--checks", "checks.json"])
    assert bad.exit_code == 2 and "error:" in bad.stdout and "Traceback" not in bad.stdout


def test_complete_reports_independence_layers_and_reviewer_notes(proj):
    (proj / "check_a.py").write_text("import sys, pathlib\nsys.exit(0 if pathlib.Path('a.done').exists() else 1)\n", encoding="utf-8")
    (proj / "reject.py").write_text("import json, sys\nsys.stdin.read()\nprint(json.dumps({'approved': False, 'reasons': ['needs a null case']}))\n", encoding="utf-8")
    (proj / "one_task.json").write_text(json.dumps([{"id": "t1", "requirement_ids": ["R1"]}]), encoding="utf-8")
    (proj / "one_check.json").write_text(json.dumps([{"requirement_id": "R1", "command": "python check_a.py", "files": ["check_a.py"]}]), encoding="utf-8")
    spec_id = _specify_one()
    assert runner.invoke(app, ["spec", "plan", spec_id, "a"]).exit_code == 0
    made = runner.invoke(app, ["spec", "tasks", spec_id, "--tasks", "one_task.json", "--checks", "one_check.json"])
    assert made.exit_code == 0, made.stdout
    (proj / "a.done").write_text("x", encoding="utf-8")
    ok = runner.invoke(app, ["spec", "complete", spec_id, "t1", "--evidence", "e"])
    assert ok.exit_code == 0 and "independent layers: baseline_red" in ok.stdout, ok.stdout
    status = runner.invoke(app, ["spec", "status", spec_id])
    assert "check R1: baseline failed (expect fail)" in status.stdout


def _specify_one():
    result = runner.invoke(app, ["spec", "specify", "a", "-r", "The system shall do A."])
    return next(line.split()[-1] for line in result.stdout.splitlines() if line.startswith("spec_id"))
