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
