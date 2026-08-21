# core/tests/verify/test_ledger.py
from pathlib import Path

from core.verify.ledger import load_ledger, record_failure, record_success


def _config(tmp_path, max_failures=3):
    return {
        "verify": {
            "failure_ledger_path": str(tmp_path / "failure_ledger.json"),
            "max_identical_failures": max_failures,
        }
    }


def test_record_failure_does_not_break_loop_below_threshold(tmp_path):
    config = _config(tmp_path, max_failures=3)
    assert record_failure(config, "task-1", "same-error") is False
    assert record_failure(config, "task-1", "same-error") is False


def test_record_failure_breaks_loop_at_threshold(tmp_path):
    config = _config(tmp_path, max_failures=3)
    record_failure(config, "task-1", "same-error")
    record_failure(config, "task-1", "same-error")
    assert record_failure(config, "task-1", "same-error") is True


def test_different_signature_resets_the_streak(tmp_path):
    config = _config(tmp_path, max_failures=3)
    record_failure(config, "task-1", "error-A")
    record_failure(config, "task-1", "error-A")
    assert record_failure(config, "task-1", "error-B") is False  # different failure, streak resets
    ledger = load_ledger(config)
    assert ledger["task-1"].failure_count == 1


def test_record_success_clears_the_entry(tmp_path):
    config = _config(tmp_path, max_failures=3)
    record_failure(config, "task-1", "same-error")
    record_failure(config, "task-1", "same-error")
    record_success(config, "task-1")
    ledger = load_ledger(config)
    assert "task-1" not in ledger


def test_ledger_persists_across_calls(tmp_path):
    config = _config(tmp_path, max_failures=5)
    record_failure(config, "task-1", "same-error")
    ledger = load_ledger(config)
    assert ledger["task-1"].failure_count == 1
    record_failure(config, "task-1", "same-error")
    ledger = load_ledger(config)
    assert ledger["task-1"].failure_count == 2


def test_missing_ledger_file_starts_empty(tmp_path):
    config = _config(tmp_path)
    ledger = load_ledger(config)
    assert ledger == {}
