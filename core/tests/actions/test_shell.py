# core/tests/actions/test_shell.py
"""shell_exec: the governed shell action. Policy-gated when asked, audited before it runs (fail-closed) and
after (outcome + output hash, never the output itself)."""
import hashlib
import json
import sys

import pytest

from core.actions import shell
from core.actions.shell import command_action, shell_exec

PY = f'"{sys.executable}"'


def _config(tmp_path, rules=""):
    (tmp_path / "policies").mkdir(exist_ok=True)
    (tmp_path / "policies" / "p.yaml").write_text(f"rules:\n{rules}" if rules else "rules: []\n", encoding="utf-8")
    return {"paths": {"policies_dir": str(tmp_path / "policies")}, "audit": {"log_path": str(tmp_path / "audit.jsonl")}}


def _records(tmp_path):
    path = tmp_path / "audit.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_denied_command_does_not_run_and_is_audited(tmp_path):
    marker = tmp_path / "ran.txt"
    config = _config(tmp_path)
    result = shell_exec("tests", f"{PY} -c \"open(r'{marker}', 'w')\"", tmp_path, config, actor="verify", enforce_policy=True)
    assert not marker.exists()
    assert result.ran is False and result.passed is False and result.error_kind == "policy_denied"
    (record,) = _records(tmp_path)
    assert record["action"] == "shell_exec" and record["result"] == "deny" and record["actor"] == "verify"


def test_allowed_run_audits_start_and_outcome_with_an_output_hash_only(tmp_path):
    config = _config(tmp_path)
    result = shell_exec("tests", f"{PY} -c \"print('secret' + '-output')\"", tmp_path, config, actor="verify", enforce_policy=False)
    assert result.ran and result.passed and "secret-output" in result.output
    start, end = _records(tmp_path)
    assert start["detail"]["phase"] == "start" and end["detail"]["phase"] == "end"
    assert end["detail"]["passed"] is True
    assert end["detail"]["output_sha256"] == hashlib.sha256(result.output.encode("utf-8")).hexdigest()
    assert "secret-output" not in json.dumps([start, end])


def test_policy_allow_rule_lets_it_run(tmp_path):
    config = _config(tmp_path, "  - action: 'shell:run:" + command_action(PY + " -c pass", tmp_path).removeprefix("shell:run:") + "'\n    effect: allow\n")
    result = shell_exec("tests", f"{PY} -c pass", tmp_path, config, actor="verify", enforce_policy=True)
    assert result.ran and result.passed


def test_unwritable_audit_log_means_the_command_does_not_run(tmp_path, monkeypatch):
    marker = tmp_path / "ran.txt"
    config = _config(tmp_path)

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(shell, "record_audit", broken)
    result = shell_exec("tests", f"{PY} -c \"open(r'{marker}', 'w')\"", tmp_path, config, actor="verify", enforce_policy=False)
    assert not marker.exists()
    assert result.ran is False and result.error_kind == "audit_unavailable"


def test_blank_command_is_skipped_without_audit(tmp_path):
    config = _config(tmp_path)
    result = shell_exec("lint", "  ", tmp_path, config, actor="verify", enforce_policy=True)
    assert result.ran is False and result.passed is True
    assert _records(tmp_path) == []


def test_long_commands_are_truncated_in_the_audit(tmp_path):
    config = _config(tmp_path)
    shell_exec("tests", f"{PY} -c pass " + "x" * 2000, tmp_path, config, actor="verify", enforce_policy=False)
    assert len(_records(tmp_path)[0]["detail"]["command"]) <= 500


@pytest.mark.parametrize("command,expected", [
    ("python check.py", "shell:run:python"),
    ("pytest.exe -q", "shell:run:pytest"),
    ("", "shell:run:"),
    ("'unclosed", "shell:run:"),
])
def test_command_action_for_bare_programs(tmp_path, command, expected):
    assert command_action(command, tmp_path) == expected


def test_command_action_for_a_path_is_its_resolved_location(tmp_path):
    assert command_action("bin/python.exe x", tmp_path) == "shell:run:" + (tmp_path / "bin" / "python.exe").resolve().as_posix()
