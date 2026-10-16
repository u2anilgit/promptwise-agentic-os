"""Ruling 2: an operator-supplied mutation command is orchestrated by the gate; exit 0 means the
tool's own threshold was met. Core never parses scores or knows a language."""
from core.verify.gate import verify_output

PASS = 'python -c "pass"'
FAIL = 'python -c "import sys; sys.exit(3)"'


def _config(tmp_path, test=PASS, mutation=None):
    verify = {"test_command": test, "lint_command": "", "failure_ledger_path": str(tmp_path / "l.json")}
    if mutation is not None:
        verify["mutation_command"] = mutation
    return {"verify": verify}


def test_mutation_is_not_run_when_not_configured(tmp_path):
    result = verify_output(diff="c", cwd=tmp_path, config=_config(tmp_path))
    assert [r.tool for r in result.results if r.tool == "mutation"] == []
    assert result.mutation_passed is False


def test_a_passing_mutation_command_is_reported_and_marks_mutation_passed(tmp_path):
    result = verify_output(diff="c", cwd=tmp_path, config=_config(tmp_path, mutation=PASS))
    mutation = next(r for r in result.results if r.tool == "mutation")
    assert mutation.ran and mutation.passed
    assert result.passed and result.mutation_passed is True


def test_a_failing_mutation_command_blocks_the_gate(tmp_path):
    result = verify_output(diff="c", cwd=tmp_path, config=_config(tmp_path, mutation=FAIL))
    assert result.passed is False and "mutation" in (result.blocked_reason or "")
    assert result.mutation_passed is False


def test_mutation_is_skipped_when_the_tests_already_fail(tmp_path):
    result = verify_output(diff="c", cwd=tmp_path, config=_config(tmp_path, test=FAIL, mutation=PASS))
    assert result.passed is False
    assert [r.tool for r in result.results if r.tool == "mutation"] == []


def test_a_hanging_mutation_command_times_out_and_blocks(tmp_path):
    cfg = _config(tmp_path, mutation='python -c "import time; time.sleep(60)"')
    cfg["verify"]["mutation_timeout_seconds"] = 1
    result = verify_output(diff="c", cwd=tmp_path, config=cfg)
    assert result.passed is False and result.mutation_passed is False
