# core/tests/actions/test_fs.py
from pathlib import Path

from core.actions.fs import fs_write, undo_last
from core.audit.log import verify_chain


def _config(tmp_path, allow: bool = True):
    policies_dir = tmp_path / "policies"
    policies_dir.mkdir(exist_ok=True)
    effect = "allow" if allow else "deny"
    (policies_dir / "test.yaml").write_text(f"rules:\n  - action: fs.write.*\n    effect: {effect}\n")
    return {
        "paths": {"policies_dir": str(policies_dir)},
        "policy": {"default_effect": "deny"},
        "audit": {"log_path": str(tmp_path / "audit.jsonl")},
        "actions": {"undo_buffer_path": str(tmp_path / "undo_buffer.json"), "undo_buffer_max": 50},
    }


def test_fs_write_allowed_writes_the_file(tmp_path):
    config = _config(tmp_path, allow=True)
    target = tmp_path / "workdir" / "hello.txt"
    result = fs_write(config, target, "hello world")
    assert result.allowed is True
    assert result.written is True
    assert target.read_text() == "hello world"


def test_fs_write_denied_does_not_touch_the_file(tmp_path):
    config = _config(tmp_path, allow=False)
    target = tmp_path / "workdir" / "hello.txt"
    result = fs_write(config, target, "hello world")
    assert result.allowed is False
    assert result.written is False
    assert not target.exists()


def test_fs_write_records_an_audit_entry_either_way(tmp_path):
    config = _config(tmp_path, allow=True)
    fs_write(config, tmp_path / "a.txt", "x")
    config_deny = _config(tmp_path, allow=False)
    config_deny["audit"]["log_path"] = config["audit"]["log_path"]  # same log
    fs_write(config_deny, tmp_path / "b.txt", "y")
    ok, broken_at = verify_chain(config)
    assert ok is True
    assert broken_at is None


def test_undo_last_restores_previous_content(tmp_path):
    config = _config(tmp_path, allow=True)
    target = tmp_path / "existing.txt"
    target.write_text("original")
    fs_write(config, target, "overwritten")
    assert target.read_text() == "overwritten"
    entry = undo_last(config)
    assert entry is not None
    assert target.read_text() == "original"


def test_undo_last_deletes_a_file_that_did_not_exist_before(tmp_path):
    config = _config(tmp_path, allow=True)
    target = tmp_path / "new_file.txt"
    fs_write(config, target, "brand new")
    assert target.exists()
    undo_last(config)
    assert not target.exists()


def test_undo_last_on_empty_buffer_returns_none(tmp_path):
    config = _config(tmp_path, allow=True)
    assert undo_last(config) is None
