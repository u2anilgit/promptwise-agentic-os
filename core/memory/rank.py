# core/memory/rank.py
"""Reciprocal Rank Fusion — standard IR technique for merging two
already-ranked result lists without needing their scores to be on
comparable scales (BM25 and cosine similarity aren't). k=60 is the
literature-standard smoothing constant; there's no repo-specific reason
to deviate (design spec's open question, resolved here).
"""
from __future__ import annotations


def reciprocal_rank_fusion(bm25_ids: list[int], vector_ids: list[int], k: int = 60) -> list[int]:
    scores: dict[int, float] = {}
    for rank, fact_id in enumerate(bm25_ids, start=1):
        scores[fact_id] = scores.get(fact_id, 0.0) + 1.0 / (k + rank)
    for rank, fact_id in enumerate(vector_ids, start=1):
        scores[fact_id] = scores.get(fact_id, 0.0) + 1.0 / (k + rank)

    return sorted(scores, key=lambda fact_id: scores[fact_id], reverse=True)
