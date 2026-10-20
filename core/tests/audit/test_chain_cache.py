# core/tests/audit/test_chain_cache.py
"""chain_status verifies incrementally: an append re-checks only the new records, but any change to
the already-verified prefix is still caught (the prefix bytes are re-digested on every call)."""
import json

from core.audit import log as audit_log
from core.audit.log import chain_status, record_audit


def _config(tmp_path):
    return {"audit": {"log_path": str(tmp_path / "audit.jsonl")}}


def _count_record_hashes(monkeypatch):
    calls = {"n": 0}
    real = audit_log._record_hash

    def counting(body):
        calls["n"] += 1
        return real(body)

    monkeypatch.setattr(audit_log, "_record_hash", counting)
    return calls


def test_unchanged_log_is_not_reparsed(tmp_path, monkeypatch):
    config = _config(tmp_path)
    for i in range(5):
        record_audit(config, actor="t", action="a", target=str(i), result="allow")
    assert chain_status(config).ok
    calls = _count_record_hashes(monkeypatch)
    assert chain_status(config).ok
    assert calls["n"] == 0


def test_append_verifies_only_the_new_records(tmp_path, monkeypatch):
    config = _config(tmp_path)
    for i in range(5):
        record_audit(config, actor="t", action="a", target=str(i), result="allow")
    assert chain_status(config).ok
    record_audit(config, actor="t", action="a", target="new", result="allow")
    calls = _count_record_hashes(monkeypatch)
    assert chain_status(config).ok
    assert calls["n"] == 1


def _tamper(path, index, field, value):
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    data = json.loads(lines[index])
    data[field] = value
    lines[index] = json.dumps(data) + "\n"
    path.write_text("".join(lines), encoding="utf-8", newline="")


def test_tamper_inside_the_verified_prefix_is_detected_after_an_append(tmp_path):
    config = _config(tmp_path)
    for i in range(4):
        record_audit(config, actor="t", action="a", target=str(i), result="allow")
    assert chain_status(config).ok
    _tamper(tmp_path / "audit.jsonl", 1, "target", "forged")
    record_audit(config, actor="t", action="a", target="after", result="allow")
    status = chain_status(config)
    assert status.ok is False
    assert status.broken_at == 1


def test_same_size_rewrite_of_the_prefix_is_detected(tmp_path):
    config = _config(tmp_path)
    for i in range(3):
        record_audit(config, actor="t", action="a", target=str(i), result="allow")
    assert chain_status(config).ok
    _tamper(tmp_path / "audit.jsonl", 0, "target", "9")  # same length as "0"
    status = chain_status(config)
    assert status.ok is False
    assert status.broken_at == 0


def test_truncated_log_is_reverified_from_the_start(tmp_path):
    config = _config(tmp_path)
    for i in range(3):
        record_audit(config, actor="t", action="a", target=str(i), result="allow")
    assert chain_status(config).ok
    path = tmp_path / "audit.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text("".join(lines[:1]), encoding="utf-8", newline="")
    assert chain_status(config).ok
    record_audit(config, actor="t", action="a", target="x", result="allow")
    assert chain_status(config).ok


def test_broken_append_reports_the_line_index(tmp_path):
    config = _config(tmp_path)
    for i in range(3):
        record_audit(config, actor="t", action="a", target=str(i), result="allow")
    assert chain_status(config).ok
    path = tmp_path / "audit.jsonl"
    with path.open("a", encoding="utf-8", newline="") as f:
        f.write(json.dumps({"prev_hash": "x", "hash": "y"}) + "\n")
    status = chain_status(config)
    assert status.ok is False
    assert status.broken_at == 3


def test_partial_trailing_line_is_left_for_the_next_call(tmp_path):
    config = _config(tmp_path)
    record_audit(config, actor="t", action="a", target="0", result="allow")
    path = tmp_path / "audit.jsonl"
    complete = path.read_bytes()
    second = record_audit(config, actor="t", action="a", target="1", result="allow")
    full = path.read_bytes()
    path.write_bytes(full[: len(complete) + 10])  # a writer mid-append
    assert chain_status(config).ok
    path.write_bytes(full)
    assert chain_status(config).ok
    assert second.hash in path.read_text(encoding="utf-8")


def test_missing_log_is_clean(tmp_path):
    assert chain_status(_config(tmp_path)).ok
