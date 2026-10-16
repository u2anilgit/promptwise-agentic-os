"""Ruling 3: operator-supplied reviewer command; strict JSON contract; fail closed."""
import json

from core.verify.reviewer import run_reviewer

PAYLOAD = {"spec_id": "s1", "task_id": "t1", "requirements": [{"id": "R1", "text": "The system shall X."}], "evidence": "did X", "checks": []}


def _cfg(command, **extra):
    return {"verify": {"reviewer_command": command, **extra}}


def _script(tmp_path, name, body):
    (tmp_path / name).write_text(body, encoding="utf-8")
    return f"python {name}"


def test_not_configured_is_not_run(tmp_path):
    verdict = run_reviewer({"verify": {}}, tmp_path, PAYLOAD)
    assert verdict.ran is False and verdict.approved is False


def test_approval_passes_the_payload_on_stdin_and_bounds_reasons(tmp_path):
    cmd = _script(tmp_path, "ok.py", (
        "import sys, json\n"
        "data = json.load(sys.stdin)\n"
        "open('seen.json', 'w').write(json.dumps(data))\n"
        "print(json.dumps({'approved': True, 'reasons': ['r' * 1000] * 50}))\n"
    ))
    verdict = run_reviewer(_cfg(cmd), tmp_path, PAYLOAD)
    assert verdict.ran and verdict.approved and verdict.error is None
    assert len(verdict.reasons) == 10 and all(len(r) <= 300 for r in verdict.reasons)
    assert json.loads((tmp_path / "seen.json").read_text(encoding="utf-8")) == PAYLOAD


def test_a_rejection_carries_its_reasons(tmp_path):
    cmd = _script(tmp_path, "no.py", "import json\nprint(json.dumps({'approved': False, 'reasons': ['misses R1']}))\n")
    verdict = run_reviewer(_cfg(cmd), tmp_path, PAYLOAD)
    assert verdict.ran and not verdict.approved and verdict.reasons == ["misses R1"] and verdict.error is None


def test_everything_else_fails_closed(tmp_path):
    cases = {
        "garbage": "print('not json')\n",
        "wrongtype": "import json\nprint(json.dumps({'approved': 'yes'}))\n",
        "notdict": "import json\nprint(json.dumps([True]))\n",
        "exit1": "import sys, json\nprint(json.dumps({'approved': True}))\nsys.exit(1)\n",
        "empty": "pass\n",
    }
    for name, body in cases.items():
        verdict = run_reviewer(_cfg(_script(tmp_path, f"{name}.py", body)), tmp_path, PAYLOAD)
        assert verdict.ran and not verdict.approved and verdict.error, name


def test_missing_executable_unparsable_command_and_timeout_fail_closed(tmp_path):
    for command in ("definitely-not-a-real-program --x", 'python -c "unclosed'):
        verdict = run_reviewer(_cfg(command), tmp_path, PAYLOAD)
        assert verdict.ran and not verdict.approved and verdict.error, command
    slow = run_reviewer(_cfg('python -c "import time; time.sleep(60)"', reviewer_timeout_seconds=1), tmp_path, PAYLOAD)
    assert slow.ran and not slow.approved and "timed out" in slow.error
