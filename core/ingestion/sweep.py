# core/ingestion/sweep.py
"""run_ingestion_sweep — the one verb this sub-project ships. Refreshes
the code index (a side effect of query_code_index's own walk) and
records caller-supplied session text as memory facts. NOT a background
process: this function runs once per call and returns; scheduling it
is an ops concern (cron/systemd/Task Scheduler), not this module's job
(design spec Ruling 1). Every step is independently fail-soft — a
code-index failure doesn't block fact recording and vice versa, and one
failed text block doesn't block its siblings (design spec's Global
Constraints).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient

from core.config.resolve import resolve_config_auto
from core.index.query import query_code_index
from core.ingestion.models import IngestionResult
from core.memory.embed import HttpPost, default_http_post
from core.memory.memory import record_memory


def run_ingestion_sweep(
    root: Path,
    session_texts: list[str] | None = None,
    session_id: str | None = None,
    config: dict[str, Any] | None = None,
    http_post: HttpPost = default_http_post,
    qdrant_client: QdrantClient | None = None,
) -> IngestionResult:
    config = config if config is not None else resolve_config_auto(root=root)
    result = IngestionResult(root=str(root))

    try:
        query_code_index("", root=root, config=config)  # side effect only, result discarded
        result.code_index_refreshed = True
    except Exception as exc:  # noqa: BLE001 — one failed subsystem must not abort the sweep
        result.errors.append(f"code index refresh failed: {exc}")

    for index, text in enumerate(session_texts or []):
        try:
            facts = record_memory(
                text, scope="session", root=str(root), session_id=session_id,
                config=config, http_post=http_post, qdrant_client=qdrant_client,
            )
            result.facts_recorded += len(facts)
        except Exception as exc:  # noqa: BLE001 — one failed text block must not abort the rest
            result.facts_failed += 1
            result.errors.append(f"record_memory failed for session_texts[{index}]: {exc}")

    return result
