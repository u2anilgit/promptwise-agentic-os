from core.verify.output import truncate_output
from core.verify.runners import run_command, run_lint, run_tests


def test_run_command_with_empty_command_is_a_noop_pass():
    result = run_command("tests", "", None)
    assert result.ran is False
    assert result.passed is True


def test_run_command_runs_a_passing_command(tmp_path):
    result = run_command("tests", "python -c \"print('ok')\"", tmp_path)
    assert result.ran is True
    assert result.passed is True
    assert "ok" in result.output


def test_run_command_runs_a_failing_command(tmp_path):
    result = run_command("tests", "python -c \"import sys; sys.exit(1)\"", tmp_path)
    assert result.ran is True
    assert result.passed is False


def test_run_tests_reads_verify_test_command(tmp_path):
    config = {"verify": {"test_command": "python -c \"print('tests ran')\""}}
    result = run_tests(config, tmp_path)
    assert result.tool == "tests"
    assert result.passed is True
    assert "tests ran" in result.output


def test_run_tests_with_no_configured_command_is_skipped():
    result = run_tests({"verify": {}}, None)
    assert result.ran is False
    assert result.passed is True


def test_run_lint_reads_verify_lint_command(tmp_path):
    config = {"verify": {"lint_command": "python -c \"print('lint ran')\""}}
    result = run_lint(config, tmp_path)
    assert result.tool == "lint"
    assert result.passed is True


def test_run_command_handles_a_nonexistent_executable_without_crashing(tmp_path):
    result = run_command("tests", "this-binary-does-not-exist-anywhere --flag", tmp_path)
    assert result.ran is True
    assert result.passed is False
    assert "error" in result.output.lower() or "not found" in result.output.lower() or "no such file" in result.output.lower()


# --- Fix 5: unbounded output must be truncated, head+tail preserved -------


def test_truncate_output_leaves_short_output_untouched():
    short = "all good, 3 passed"
    assert truncate_output(short, max_output_chars=4000) == short


def test_truncate_output_keeps_head_and_tail_with_marker():
    long_output = ("A" * 5000) + "MIDDLE" + ("Z" * 5000)
    result = truncate_output(long_output, max_output_chars=4000)
    assert len(result) < len(long_output)
    assert result.startswith("A" * 100)
    assert result.endswith("Z" * 100)
    assert "truncated" in result
    assert "chars omitted" in result
    assert "MIDDLE" not in result


def test_run_command_truncates_long_output(tmp_path):
    command = "python -c \"print('X' * 10000)\""
    result = run_command("tests", command, tmp_path, max_output_chars=4000)
    assert result.ran is True
    assert len(result.output) < 10000
    assert "truncated" in result.output


def test_run_command_does_not_truncate_short_output(tmp_path):
    command = "python -c \"print('short output')\""
    result = run_command("tests", command, tmp_path, max_output_chars=4000)
    assert result.output.strip() == "short output"
