# core/tests/verify/test_gate.py
from pathlib import Path

from core.verify.gate import verify_output


def _write_project(tmp_path: Path, test_command: str) -> dict:
    return {"verify": {"test_command": test_command, "lint_command": "", "max_identical_failures": 3, "failure_ledger_path": str(tmp_path / "ledger.json")}}


def test_verify_output_blocks_a_deliberately_broken_diff(tmp_path):
    config = _write_project(tmp_path, "python -c \"import sys; sys.exit(1)\"")
    result = verify_output(diff="broken change", spec="add a feature", cwd=tmp_path, config=config)
    assert result.passed is False
    assert result.blocked_reason is not None


def test_verify_output_passes_a_correct_diff(tmp_path):
    config = _write_project(tmp_path, "python -c \"print('all good')\"")
    result = verify_output(diff="correct change", spec="add a feature", cwd=tmp_path, config=config)
    assert result.passed is True
    assert result.blocked_reason is None


def test_verify_output_records_failure_and_breaks_loop_after_max_identical(tmp_path):
    config = _write_project(tmp_path, "python -c \"import sys; sys.exit(1)\"")
    config["verify"]["max_identical_failures"] = 2
    r1 = verify_output(diff="d", spec="s", cwd=tmp_path, config=config, ledger_key="task-x")
    assert r1.retry_loop_broken is False
    r2 = verify_output(diff="d", spec="s", cwd=tmp_path, config=config, ledger_key="task-x")
    assert r2.retry_loop_broken is True


def test_verify_output_success_clears_the_ledger(tmp_path):
    fail_config = _write_project(tmp_path, "python -c \"import sys; sys.exit(1)\"")
    fail_config["verify"]["max_identical_failures"] = 5
    verify_output(diff="d", spec="s", cwd=tmp_path, config=fail_config, ledger_key="task-y")

    from core.verify.ledger import load_ledger

    ledger = load_ledger(fail_config)
    assert "task-y" in ledger

    pass_config = _write_project(tmp_path, "python -c \"print('ok')\"")
    pass_config["verify"]["failure_ledger_path"] = fail_config["verify"]["failure_ledger_path"]
    verify_output(diff="d2", spec="s", cwd=tmp_path, config=pass_config, ledger_key="task-y")

    ledger = load_ledger(pass_config)
    assert "task-y" not in ledger


def test_verify_output_without_ledger_key_never_touches_the_ledger(tmp_path):
    config = _write_project(tmp_path, "python -c \"import sys; sys.exit(1)\"")
    result = verify_output(diff="d", spec="s", cwd=tmp_path, config=config)  # no ledger_key
    assert result.passed is False
    assert result.retry_loop_broken is False


def test_verify_output_no_test_command_configured_still_passes(tmp_path):
    config = {"verify": {"test_command": "", "lint_command": "", "max_identical_failures": 3, "failure_ledger_path": str(tmp_path / "ledger.json")}}
    result = verify_output(diff="d", spec="s", cwd=tmp_path, config=config)
    assert result.passed is True


def test_verify_output_with_no_explicit_config_resolves_from_cwd_not_process_cwd(tmp_path, monkeypatch):
    """A real MCP caller passes `cwd` (the target project) but no `config` —
    verify_output must resolve that target project's own org config, not
    whatever config happens to sit at the gateway process's cwd. Regression
    test for a bug found while adding the MCP end-to-end test: config
    resolution silently used process cwd instead of the `cwd` argument.
    """
    monkeypatch.chdir(tmp_path)  # process cwd is NOT the target project
    target = tmp_path / "target-project"
    target.mkdir()
    (target / "promptwise.config.yaml").write_text('verify:\n  test_command: "python -c \\"print(1)\\""\n')

    result = verify_output(diff="d", spec="s", cwd=target)
    assert result.passed is True
    tests_result = next(r for r in result.results if r.tool == "tests")
    assert tests_result.ran is True  # proves the target project's own config was picked up
