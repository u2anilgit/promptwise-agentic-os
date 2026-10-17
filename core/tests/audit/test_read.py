import json

from core.audit.log import chain_status, record_audit
from core.audit.read import read_audit, read_audit_tail


def _config(tmp_path):
    return {"audit": {"log_path": str(tmp_path / "audit.jsonl")}}


def _fill(config, n, action="a"):
    return [record_audit(config, actor="t", action=action, target=f"x{i}", result="allow") for i in range(n)]


def test_forward_paging_has_no_gaps_or_duplicates(tmp_path):
    config = _config(tmp_path)
    written = _fill(config, 7)
    seen, cursor = [], 0
    while True:
        page = read_audit(config, after=cursor, limit=3)
        if not page.records:
            break
        seen += [r.id for r in page.records]
        cursor = page.next_cursor
    assert seen == [r.id for r in written]


def test_filters_by_action_and_result(tmp_path):
    config = _config(tmp_path)
    record_audit(config, actor="t", action="fs_write", target="a", result="allow")
    record_audit(config, actor="t", action="mcp_call", target="b", result="deny")
    assert [r.target for r in read_audit(config, action="mcp_call").records] == ["b"]
    assert [r.target for r in read_audit(config, result="allow").records] == ["a"]


def test_malformed_line_is_skipped_not_fatal(tmp_path):
    config = _config(tmp_path)
    _fill(config, 2)
    path = tmp_path / "audit.jsonl"
    first, second = path.read_text(encoding="utf-8").splitlines()
    path.write_text(first + "\nnot json\n" + second + "\n", encoding="utf-8")
    assert len(read_audit(config).records) == 2


def test_partial_trailing_line_is_not_consumed_until_complete(tmp_path):
    config = _config(tmp_path)
    _fill(config, 1)
    path = tmp_path / "audit.jsonl"
    first = read_audit(config)
    line = json.dumps({"id": "z", "timestamp": "t", "actor": "t", "action": "late", "target": "q",
                       "result": "allow", "detail": {}, "prev_hash": "p", "hash": "h"})
    with path.open("a", encoding="utf-8", newline="") as f:
        f.write(line[:20])  # writer is mid-append
    mid = read_audit(config, after=first.next_cursor)
    assert mid.records == [] and mid.next_cursor == first.next_cursor
    with path.open("a", encoding="utf-8", newline="") as f:
        f.write(line[20:] + "\n")
    done = read_audit(config, after=first.next_cursor)
    assert [r.action for r in done.records] == ["late"]


def test_tail_returns_newest_in_chronological_order(tmp_path):
    config = _config(tmp_path)
    written = _fill(config, 10)
    page = read_audit_tail(config, limit=4)
    assert [r.id for r in page.records] == [r.id for r in written[-4:]]
    assert read_audit(config, after=page.next_cursor).records == []


def test_tail_with_filter_and_short_file(tmp_path):
    config = _config(tmp_path)
    _fill(config, 2, action="a")
    _fill(config, 2, action="b")
    assert [r.action for r in read_audit_tail(config, limit=10, action="b").records] == ["b", "b"]


def test_limit_is_clamped(tmp_path):
    config = _config(tmp_path)
    _fill(config, 3)
    assert len(read_audit(config, limit=0).records) == 1
    assert len(read_audit(config, limit=10**9).records) == 3
    assert len(read_audit_tail(config, limit=-5).records) == 1


def test_missing_log_is_an_empty_page(tmp_path):
    page = read_audit(_config(tmp_path))
    assert page.records == [] and page.next_cursor == 0


def test_chain_status_ok_and_broken(tmp_path):
    config = _config(tmp_path)
    _fill(config, 3)
    assert chain_status(config).ok is True
    path = tmp_path / "audit.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["target"] = "tampered"
    lines[1] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    status = chain_status(config)
    assert status.ok is False and status.broken_at == 1
