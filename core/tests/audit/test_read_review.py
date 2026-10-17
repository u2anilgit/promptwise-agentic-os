"""Regressions from the adversarial review of the dashboard read API."""
import json

from core.audit.log import record_audit
from core.audit.read import MAX_READ_BYTES, read_audit, read_audit_tail


def _config(tmp_path):
    return {"audit": {"log_path": str(tmp_path / "audit.jsonl")}}


def test_one_oversized_line_does_not_stall_the_cursor_forever(tmp_path):
    config = _config(tmp_path)
    before = record_audit(config, actor="t", action="before", target="a", result="allow")
    path = tmp_path / "audit.jsonl"
    with path.open("a", encoding="utf-8", newline="") as f:
        f.write("x" * (MAX_READ_BYTES + 1000) + "\n")
    with path.open("a", encoding="utf-8", newline="") as f:
        f.write(json.dumps({"id": "z", "timestamp": "t", "actor": "t", "action": "after", "target": "q",
                            "result": "allow", "detail": {}, "prev_hash": "p", "hash": "h"}) + "\n")
    seen, cursor = [], 0
    for _ in range(10):
        page = read_audit(config, after=cursor, limit=50)
        seen += [r.action for r in page.records]
        if page.next_cursor == cursor:
            break
        cursor = page.next_cursor
    assert seen == ["before", "after"]
    assert before.id


def test_oversized_detail_is_truncated_when_recorded(tmp_path):
    config = _config(tmp_path)
    record = record_audit(config, actor="t", action="big", target="a", result="deny", detail={"value": "y" * 500_000})
    assert record.detail.get("truncated") is True
    assert (tmp_path / "audit.jsonl").stat().st_size < 100_000


def test_a_truncated_log_restarts_the_reader_at_zero(tmp_path):
    config = _config(tmp_path)
    for i in range(3):
        record_audit(config, actor="t", action="a", target=f"x{i}", result="allow")
    far = read_audit(config).next_cursor
    path = tmp_path / "audit.jsonl"
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    path.write_text(first_line + "\n", encoding="utf-8")  # rotated to a shorter file
    page = read_audit(config, after=far)
    assert [r.target for r in page.records] == ["x0"]
