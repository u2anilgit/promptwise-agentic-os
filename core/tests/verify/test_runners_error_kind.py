from core.verify.runners import run_command


def test_error_kind_distinguishes_infrastructure_failures_from_a_failing_command(tmp_path):
    assert run_command("t", 'python -c "import sys; sys.exit(1)"', tmp_path).error_kind is None  # a genuine failure
    assert run_command("t", "definitely-not-a-program", tmp_path).error_kind == "not_found"
    assert run_command("t", 'python -c "unclosed', tmp_path).error_kind == "parse"
    assert run_command("t", 'python -c "import time; time.sleep(60)"', tmp_path, timeout=1).error_kind == "timeout"
