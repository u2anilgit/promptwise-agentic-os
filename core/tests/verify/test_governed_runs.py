"""verify_output's test/lint/mutation commands go through shell_exec: always audited, policy-gated when
verify.enforce_command_policy is on."""
import json
import sys

from core.verify.gate import verify_output

PASSING = f'"{sys.executable}" -c pass'


def _config(tmp_path, enforce=False):
    (tmp_path / "policies").mkdir(exist_ok=True)
    (tmp_path / "policies" / "p.yaml").write_text("rules: []\n", encoding="utf-8")
    return {
        "paths": {"policies_dir": str(tmp_path / "policies")},
        "audit": {"log_path": str(tmp_path / "audit.jsonl")},
        "verify": {"test_command": PASSING, "lint_command": "", "failure_ledger_path": str(tmp_path / "ledger.json"),
                   "enforce_command_policy": enforce, "semgrep_enabled": False, "gitleaks_enabled": False},
    }


def _shell_records(tmp_path):
    path = tmp_path / "audit.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    return [r for r in rows if r["action"] == "shell_exec"]


def test_test_command_is_audited(tmp_path):
    result = verify_output("diff", cwd=tmp_path, config=_config(tmp_path))
    assert result.grounded
    records = _shell_records(tmp_path)
    assert [r["detail"]["phase"] for r in records] == ["start", "end"]
    assert all(r["actor"] == "verify" and r["detail"]["tool"] == "tests" for r in records)


def test_enforced_policy_denies_an_unlisted_test_command(tmp_path):
    result = verify_output("diff", cwd=tmp_path, config=_config(tmp_path, enforce=True))
    assert not result.passed and not result.grounded
    (record,) = _shell_records(tmp_path)
    assert record["result"] == "deny"


def test_a_mutation_run_that_policy_denies_blocks_the_gate(tmp_path):
    """Tests allowed, mutation not: the gate must not pass as if mutation were unconfigured."""
    from core.actions.shell import command_action

    config = _config(tmp_path, enforce=True)
    allow = command_action(PASSING, tmp_path).removeprefix("shell:run:")
    (tmp_path / "policies" / "p.yaml").write_text(f"rules:\n  - action: 'shell:run:{allow}'\n    effect: allow\n", encoding="utf-8")
    config["verify"]["mutation_command"] = "mutmut run"
    result = verify_output("diff", cwd=tmp_path, config=config)
    assert result.grounded and not result.passed
    assert "mutation" in (result.blocked_reason or "")
    assert result.mutation_passed is False


def test_an_unauditable_test_run_blocks_the_gate(tmp_path, monkeypatch):
    from core.actions import shell

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(shell, "record_audit", broken)
    result = verify_output("diff", cwd=tmp_path, config=_config(tmp_path))
    assert not result.passed and not result.grounded
