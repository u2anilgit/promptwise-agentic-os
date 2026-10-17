# core/routing/usage.py
"""Durable usage ledger — the data behind $/completed-task.

Core calls no LLM, so only the agent knows what it spent: usage is SELF-REPORTED through
`record_usage` (exposed as a governed MCP tool). Cost is computed once from the catalog tier and
stored, so later catalog edits never rewrite history. Everything is bounded and audited.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy import distinct, func, select

from core.audit.log import record_audit
from core.config.resolve import resolve_config_auto
from core.db.base import session_scope
from core.db.migrate import migrate_to_head
from core.routing.catalog import load_catalog
from core.routing.cost import CostRecord, record_cost
from core.routing.tables import UsageRow

MAX_TOKENS = 1_000_000_000
MAX_TEXT = 200
MAX_RECENT = 50
MAX_DAYS = 365


class UsageEvent(BaseModel):
    id: int
    ts: float
    tier: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    agent: str
    task_ref: str | None = None
    spec_id: str | None = None


class Bucket(BaseModel):
    events: int
    tokens_in: int
    tokens_out: int
    cost_usd: float


class UsageReport(BaseModel):
    days: int
    events: int
    tasks: int
    tokens_in: int
    tokens_out: int
    total_cost_usd: float
    cost_per_task_usd: float | None
    by_tier: dict[str, Bucket]
    by_agent: dict[str, Bucket]
    recent: list[UsageEvent]


def _prepare(config: dict[str, Any] | None, root: Path | None) -> dict[str, Any]:
    config = config if config is not None else resolve_config_auto(root=root)
    migrate_to_head(config, root)
    return config


def _tokens(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_TOKENS:
        raise ValueError(f"{name} tokens must be an integer between 0 and {MAX_TOKENS}")
    return value


def _text(name: str, value: str | None) -> str | None:
    if value is not None and len(value) > MAX_TEXT:
        raise ValueError(f"{name} exceeds {MAX_TEXT} characters")
    return value


def record_usage(
    tier: str,
    tokens_in: int,
    tokens_out: int,
    agent: str = "unknown",
    task_ref: str | None = None,
    spec_id: str | None = None,
    config: dict[str, Any] | None = None,
    root: Path | None = None,
) -> UsageEvent:
    tokens_in = _tokens("input", tokens_in)
    tokens_out = _tokens("output", tokens_out)
    agent = _text("agent", agent or "unknown") or "unknown"
    task_ref = _text("task_ref", task_ref or None)
    spec_id = _text("spec_id", spec_id or None)
    config = _prepare(config, root)
    catalog = load_catalog(config)
    if tier not in catalog:
        raise ValueError(f"unknown tier '{tier}'")
    cost = round(record_cost(CostRecord(tier=tier, tokens_in=tokens_in, tokens_out=tokens_out), catalog[tier]), 6)
    row = UsageRow(
        ts=time.time(), tier=tier, tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost,
        agent=agent, task_ref=task_ref, spec_id=spec_id,
    )
    with session_scope(config, root) as session:
        session.add(row)
        session.flush()
        event = _event(row)
    record_audit(
        config, actor="usage", action="usage_recorded", target=agent, result="allow",
        detail={"tier": tier, "tokens_in": tokens_in, "tokens_out": tokens_out, "cost_usd": cost, "task_ref": task_ref},
    )
    return event


def _event(row: UsageRow) -> UsageEvent:
    return UsageEvent(
        id=row.pk, ts=row.ts, tier=row.tier, tokens_in=row.tokens_in, tokens_out=row.tokens_out,
        cost_usd=row.cost_usd, agent=row.agent, task_ref=row.task_ref, spec_id=row.spec_id,
    )


def _buckets(session, column, since: float) -> dict[str, Bucket]:
    rows = session.execute(
        select(
            column, func.count(), func.coalesce(func.sum(UsageRow.tokens_in), 0),
            func.coalesce(func.sum(UsageRow.tokens_out), 0), func.coalesce(func.sum(UsageRow.cost_usd), 0.0),
        ).where(UsageRow.ts >= since).group_by(column)
    ).all()
    return {
        name: Bucket(events=n, tokens_in=int(tin), tokens_out=int(tout), cost_usd=round(float(cost), 6))
        for name, n, tin, tout, cost in rows
    }


def usage_report(days: int = 7, config: dict[str, Any] | None = None, root: Path | None = None) -> UsageReport:
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= MAX_DAYS:
        raise ValueError(f"days must be an integer between 1 and {MAX_DAYS}")
    config = _prepare(config, root)
    since = time.time() - days * 86400
    with session_scope(config, root) as session:
        events, tin, tout, cost = session.execute(
            select(
                func.count(), func.coalesce(func.sum(UsageRow.tokens_in), 0),
                func.coalesce(func.sum(UsageRow.tokens_out), 0), func.coalesce(func.sum(UsageRow.cost_usd), 0.0),
            ).where(UsageRow.ts >= since)
        ).one()
        tasks = session.scalar(
            select(func.count(distinct(UsageRow.task_ref))).where(UsageRow.ts >= since, UsageRow.task_ref.is_not(None))
        ) or 0
        # $/task: cost of the events that name a task, over the distinct tasks they name
        task_cost = session.scalar(
            select(func.coalesce(func.sum(UsageRow.cost_usd), 0.0)).where(UsageRow.ts >= since, UsageRow.task_ref.is_not(None))
        ) or 0.0
        recent = session.scalars(
            select(UsageRow).where(UsageRow.ts >= since).order_by(UsageRow.ts.desc(), UsageRow.pk.desc()).limit(MAX_RECENT)
        ).all()
        return UsageReport(
            days=days, events=events, tasks=tasks, tokens_in=int(tin), tokens_out=int(tout),
            total_cost_usd=round(float(cost), 6),
            cost_per_task_usd=round(float(task_cost) / tasks, 6) if tasks else None,
            by_tier=_buckets(session, UsageRow.tier, since),
            by_agent=_buckets(session, UsageRow.agent, since),
            recent=[_event(r) for r in recent],
        )
