from core.audit.log import record_audit
from core.audit.read import read_audit, read_audit_tail


def _config(tmp_path):
    return {"audit": {"log_path": str(tmp_path / "audit.jsonl")}}


def _seed(config):
    for target in ("spec-1", "spec-10", "spec-1", "other"):
        record_audit(config, actor="t", action="complete_task", target=target, result="allow")


def test_target_filter_is_an_exact_match_not_a_prefix(tmp_path):
    config = _config(tmp_path)
    _seed(config)
    assert [r.target for r in read_audit(config, target="spec-1").records] == ["spec-1", "spec-1"]
    assert [r.target for r in read_audit_tail(config, target="spec-10").records] == ["spec-10"]


def test_target_filter_combines_with_the_others(tmp_path):
    config = _config(tmp_path)
    _seed(config)
    record_audit(config, actor="t", action="tasks", target="spec-1", result="deny")
    page = read_audit_tail(config, target="spec-1", action="tasks", result="deny")
    assert len(page.records) == 1


# --- review fixes: bounded, incremental tail reads that say when they are partial ---
import core.audit.read as reader


def test_tail_reports_truncation_when_more_matches_exist_than_the_limit(tmp_path):
    config = _config(tmp_path)
    for i in range(5):
        record_audit(config, actor="t", action="a", target="spec-1", result="allow", detail={"i": i})
    page = read_audit_tail(config, limit=3, target="spec-1")
    assert [r.detail["i"] for r in page.records] == [2, 3, 4]
    assert page.truncated is True
    assert read_audit_tail(config, limit=10, target="spec-1").truncated is False


def test_tail_reports_truncation_when_the_scan_budget_ends_before_the_start_of_the_log(tmp_path, monkeypatch):
    config = _config(tmp_path)
    record_audit(config, actor="t", action="a", target="old-spec", result="allow")
    for i in range(200):
        record_audit(config, actor="t", action="a", target="busy", result="allow", detail={"pad": "x" * 100})
    monkeypatch.setattr(reader, "MAX_READ_BYTES", 8 * 1024)
    monkeypatch.setattr(reader, "TAIL_CHUNK", 2 * 1024)
    page = read_audit_tail(config, limit=5, target="old-spec")
    assert page.records == []
    assert page.truncated is True  # "nothing found" here means "not looked far enough", and says so


def test_tail_parses_each_line_at_most_once(tmp_path, monkeypatch):
    config = _config(tmp_path)
    for i in range(400):
        record_audit(config, actor="t", action="a", target="busy", result="allow", detail={"pad": "x" * 50})
    calls = []
    original = reader._parse
    monkeypatch.setattr(reader, "_parse", lambda line: (calls.append(1), original(line))[1])
    monkeypatch.setattr(reader, "TAIL_CHUNK", 4 * 1024)
    read_audit_tail(config, limit=5, target="never-matches")
    assert len(calls) <= 400


def test_tail_still_returns_the_newest_in_order_across_chunk_boundaries(tmp_path, monkeypatch):
    config = _config(tmp_path)
    ids = [record_audit(config, actor="t", action="a", target="s", result="allow", detail={"pad": "x" * 70}).id for _ in range(120)]
    monkeypatch.setattr(reader, "TAIL_CHUNK", 1024)
    page = read_audit_tail(config, limit=50, target="s")
    assert [r.id for r in page.records] == ids[-50:]
    assert page.truncated is True
    assert read_audit(config, after=page.next_cursor).records == []
