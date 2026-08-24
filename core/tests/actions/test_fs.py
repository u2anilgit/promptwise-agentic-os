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


def test_undo_buffer_max_zero_disables_undo_history(tmp_path):
    """Regression: buffer[-max_size:] with max_size=0 slices as [0:] (the
    whole list) because Python treats -0 as 0, not "keep nothing". An
    operator setting undo_buffer_max: 0 to disable undo retention must
    actually get an empty buffer, not the full history.
    """
    config = _config(tmp_path, allow=True)
    config["actions"]["undo_buffer_max"] = 0
    fs_write(config, tmp_path / "a.txt", "x")

    import json

    with open(config["actions"]["undo_buffer_path"], encoding="utf-8") as f:
        assert json.load(f) == []


def test_fs_write_policy_scope_is_directory_specific_not_just_basename(tmp_path):
    """Regression: fs_write's policy scope must include the full path, not
    just the filename — otherwise a rule can't distinguish
    workspace/hello.txt from secrets/hello.txt, and directory-scoped
    allow/deny policy (the entire point of governed fs actions) is
    unexpressible.
    """
    policies_dir = tmp_path / "policies"
    policies_dir.mkdir()
    workdir = tmp_path / "workspace"
    secrets_dir = tmp_path / "secrets"
    (policies_dir / "test.yaml").write_text(
        f"rules:\n"
        f"  - action: \"fs.write.{workdir.as_posix()}/*\"\n"
        f"    effect: allow\n"
        f"  - action: \"fs.write.{secrets_dir.as_posix()}/*\"\n"
        f"    effect: deny\n"
    )
    config = {
        "paths": {"policies_dir": str(policies_dir)},
        "policy": {"default_effect": "deny"},
        "audit": {"log_path": str(tmp_path / "audit.jsonl")},
        "actions": {"undo_buffer_path": str(tmp_path / "undo_buffer.json"), "undo_buffer_max": 50},
    }

    allowed_result = fs_write(config, workdir / "hello.txt", "ok")
    assert allowed_result.allowed is True
    assert (workdir / "hello.txt").read_text() == "ok"

    denied_result = fs_write(config, secrets_dir / "hello.txt", "leak")
    assert denied_result.allowed is False
    assert not (secrets_dir / "hello.txt").exists()
