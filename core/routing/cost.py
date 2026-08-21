"""cost_report — docs/research/aug2026-findings.md Part 5 row 5, the
$/completed-task metric. Stateless: takes the records to report over as an
argument. A durable ledger (persisting records across requests) is a later
phase's concern once the structured store exists — Phase 1 proves the
metric works, Phase 4+ makes it durable.
"""
from __future__ import annotations

from pydantic import BaseModel

from core.routing.models import ModelTier


class CostRecord(BaseModel):
    tier: str
    tokens_in: int
    tokens_out: int


def record_cost(record: CostRecord, tier_obj: ModelTier) -> float:
    return (record.tokens_in / 1000) * tier_obj.cost_per_1k_input_usd + (
        record.tokens_out / 1000
    ) * tier_obj.cost_per_1k_output_usd


def cost_report(records: list[CostRecord], catalog: dict[str, ModelTier]) -> dict:
    total_cost = 0.0
    by_tier: dict[str, dict] = {}
    for record in records:
        tier_obj = catalog[record.tier]
        cost = record_cost(record, tier_obj)
        total_cost += cost
        entry = by_tier.setdefault(record.tier, {"tasks": 0, "cost_usd": 0.0})
        entry["tasks"] += 1
        entry["cost_usd"] += cost

    completed_tasks = len(records)
    cost_per_task = (total_cost / completed_tasks) if completed_tasks else 0.0

    return {
        "total_cost_usd": round(total_cost, 6),
        "completed_tasks": completed_tasks,
        "cost_per_completed_task_usd": round(cost_per_task, 6),
        "by_tier": {
            name: {"tasks": entry["tasks"], "cost_usd": round(entry["cost_usd"], 6)}
            for name, entry in by_tier.items()
        },
    }
