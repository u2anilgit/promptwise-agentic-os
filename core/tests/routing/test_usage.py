import json
import time

import pytest

from core.db.migrate import head_revision
from core.routing.usage import record_usage, usage_report


@pytest.fixture
def cfg(tmp_path):
    return {
        "database": {"url": f"sqlite:///{(tmp_path / 'usage.db').as_posix()}"},
        "audit": {"log_path": str(tmp_path / "audit.jsonl")},
        "paths": {"model_catalog": "catalog/model_catalog.yaml"},
    }


def _audit_actions(tmp_path):
    path = tmp_path / "audit.jsonl"
    return [json.loads(line)["action"] for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_head_revision_includes_the_usage_table():
    assert head_revision() == "0004"


def test_record_fixes_the_cost_at_record_time_from_the_catalog(cfg, tmp_path):
    event = record_usage("local-small", 1000, 500, agent="claude", task_ref="T-1", config=cfg, root=tmp_path)
    assert event.tier == "local-small" and event.cost_usd == 0.0  # local tiers are free
    cloud = record_usage("cloud-premium", 1000, 1000, agent="claude", task_ref="T-1", config=cfg, root=tmp_path)
    assert cloud.cost_usd > 0
    assert "usage_recorded" in _audit_actions(tmp_path)


@pytest.mark.parametrize("tin,tout", [(-1, 0), (0, -5), (10**10, 0), (0, 10**10)])
def test_out_of_range_tokens_are_rejected_and_nothing_is_written(cfg, tmp_path, tin, tout):
    with pytest.raises(ValueError, match="tokens"):
        record_usage("local-small", tin, tout, config=cfg, root=tmp_path)
    assert usage_report(config=cfg, root=tmp_path).events == 0


def test_non_integer_tokens_are_rejected(cfg, tmp_path):
    with pytest.raises(ValueError, match="tokens"):
        record_usage("local-small", 1.5, 0, config=cfg, root=tmp_path)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="tokens"):
        record_usage("local-small", float("nan"), 0, config=cfg, root=tmp_path)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="tokens"):
        record_usage("local-small", True, 0, config=cfg, root=tmp_path)  # type: ignore[arg-type]


def test_unknown_tier_is_rejected_never_guessed(cfg, tmp_path):
    with pytest.raises(ValueError, match="unknown tier"):
        record_usage("quantum-ultra", 1, 1, config=cfg, root=tmp_path)
    assert usage_report(config=cfg, root=tmp_path).events == 0


def test_oversized_strings_are_rejected(cfg, tmp_path):
    for field in ("agent", "task_ref", "spec_id"):
        with pytest.raises(ValueError, match=field):
            record_usage("local-small", 1, 1, config=cfg, root=tmp_path, **{field: "x" * 201})


def test_report_aggregates_by_tier_and_agent_and_counts_tasks_once(cfg, tmp_path):
    record_usage("local-small", 1000, 0, agent="claude", task_ref="T-1", config=cfg, root=tmp_path)
    record_usage("cloud-premium", 1000, 1000, agent="claude", task_ref="T-1", config=cfg, root=tmp_path)
    record_usage("cloud-premium", 1000, 1000, agent="aider", task_ref="T-1", config=cfg, root=tmp_path)  # same task, other agent
    record_usage("local-small", 10, 10, agent="aider", task_ref="T-2", config=cfg, root=tmp_path)
    report = usage_report(config=cfg, root=tmp_path)
    assert report.events == 4
    assert report.tasks == 2
    assert report.by_tier["cloud-premium"].events == 2
    assert report.by_agent["claude"].events == 2 and report.by_agent["aider"].events == 2
    assert report.cost_per_task_usd == pytest.approx(report.total_cost_usd / 2)
    assert report.tokens_in == 3010
    assert len(report.recent) == 4


def test_cost_per_task_is_null_without_task_references(cfg, tmp_path):
    record_usage("cloud-premium", 1000, 1000, config=cfg, root=tmp_path)
    report = usage_report(config=cfg, root=tmp_path)
    assert report.tasks == 0 and report.cost_per_task_usd is None


def test_empty_window_is_zeros_not_an_error(cfg, tmp_path):
    report = usage_report(config=cfg, root=tmp_path)
    assert (report.events, report.total_cost_usd, report.by_tier, report.cost_per_task_usd, report.recent) == (0, 0.0, {}, None, [])


def test_window_filters_by_event_time(cfg, tmp_path):
    from sqlalchemy import update

    from core.db.base import session_scope
    from core.routing.tables import UsageRow

    record_usage("local-small", 1, 1, task_ref="old", config=cfg, root=tmp_path)
    record_usage("local-small", 1, 1, task_ref="new", config=cfg, root=tmp_path)
    with session_scope(cfg, tmp_path) as session:
        session.execute(update(UsageRow).where(UsageRow.task_ref == "old").values(ts=time.time() - 30 * 86400))
    assert usage_report(days=7, config=cfg, root=tmp_path).events == 1
    assert usage_report(days=60, config=cfg, root=tmp_path).events == 2


def test_recent_is_bounded_and_newest_first(cfg, tmp_path):
    for i in range(60):
        record_usage("local-small", 1, 1, task_ref=f"T-{i}", config=cfg, root=tmp_path)
    report = usage_report(config=cfg, root=tmp_path)
    assert len(report.recent) == 50 and report.recent[0].task_ref == "T-59"


@pytest.mark.parametrize("days", [0, -1, 366])
def test_report_window_is_bounded(cfg, tmp_path, days):
    with pytest.raises(ValueError, match="days"):
        usage_report(days=days, config=cfg, root=tmp_path)


def test_concurrent_writers_do_not_lose_events(cfg, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    record_usage("local-small", 1, 1, config=cfg, root=tmp_path)  # migrate once, up front
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: record_usage("local-small", 1, 1, task_ref=f"c{i}", config=cfg, root=tmp_path), range(40)))
    assert usage_report(config=cfg, root=tmp_path).events == 41
