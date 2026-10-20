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
