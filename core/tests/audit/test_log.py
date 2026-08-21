# core/tests/audit/test_log.py
from core.audit.log import record_audit, verify_chain


def _config(tmp_path):
    return {"audit": {"log_path": str(tmp_path / "audit.jsonl")}}


def test_record_audit_returns_a_record_with_a_hash(tmp_path):
    config = _config(tmp_path)
    record = record_audit(config, actor="cli", action="fs_write", target="foo.txt", result="allow")
    assert record.hash
    assert record.prev_hash == "0" * 64  # genesis


def test_second_record_chains_to_the_first(tmp_path):
    config = _config(tmp_path)
    r1 = record_audit(config, actor="cli", action="fs_write", target="a.txt", result="allow")
    r2 = record_audit(config, actor="cli", action="fs_write", target="b.txt", result="allow")
    assert r2.prev_hash == r1.hash
    assert r2.hash != r1.hash


def test_verify_chain_passes_on_untampered_log(tmp_path):
    config = _config(tmp_path)
    record_audit(config, actor="cli", action="a", target="x", result="allow")
    record_audit(config, actor="cli", action="b", target="y", result="deny")
    ok, broken_at = verify_chain(config)
    assert ok is True
    assert broken_at is None


def test_verify_chain_detects_tampering(tmp_path):
    config = _config(tmp_path)
    record_audit(config, actor="cli", action="a", target="x", result="allow")
    record_audit(config, actor="cli", action="b", target="y", result="allow")
    path = config["audit"]["log_path"]
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    import json

    tampered = json.loads(lines[0])
    tampered["target"] = "tampered"
    lines[0] = json.dumps(tampered) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    ok, broken_at = verify_chain(config)
    assert ok is False
    assert broken_at == 0


def test_verify_chain_on_empty_or_missing_log_is_clean(tmp_path):
    config = _config(tmp_path)
    ok, broken_at = verify_chain(config)
    assert ok is True
    assert broken_at is None


def test_record_audit_result_must_be_one_of_the_allowed_values(tmp_path):
    import pytest
    from pydantic import ValidationError

    config = _config(tmp_path)
    with pytest.raises(ValidationError):
        record_audit(config, actor="cli", action="a", target="x", result="not-a-real-result")
