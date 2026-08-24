# core/memory/memory.py
"""record_memory / query_memory — the two public verbs this sub-project
ships. Ties extraction, embedding, dual storage, and fused retrieval
together. Every failure mode inside a single fact's pipeline (embedding
fails, Qdrant unreachable) degrades that ONE fact to BM25-only rather
than aborting the whole call — same "handled state, not exception"
convention as core/index/query.py.

NOTE: scope="session" is not currently filtered by session_id in
query_memory — a session query returns all facts recorded under that
scope, not just the calling session's. Tracked in docs/BACKLOG.md.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient

from core.audit.log import record_audit
from core.config.resolve import resolve_config_auto
from core.diagnostics.redact import contains_pii
from core.memory.embed import HttpPost, default_http_post, embed_text
from core.memory.extract import extract_facts
from core.memory.models import Fact
from core.memory.rank import reciprocal_rank_fusion
from core.memory.store import open_store, save_fact, search_fts
from core.memory.vectors import ensure_collection, search as vector_search, upsert_fact


def _qdrant_client(config: dict[str, Any]) -> QdrantClient:
    url = config.get("memory", {}).get("qdrant_url", "http://127.0.0.1:6333")
    return QdrantClient(url=url)


def record_memory(
    text: str,
    scope: str,
    root: str | None = None,
    session_id: str | None = None,
    config: dict[str, Any] | None = None,
    http_post: HttpPost = default_http_post,
    qdrant_client: QdrantClient | None = None,
) -> list[Fact]:
    """Extract facts from `text` and persist them (SQLite + best-effort
    Qdrant vector). NOTE: `session_id` is accepted and persisted here, but
    query_memory does not currently filter by it — see module docstring.
    """
    config = config if config is not None else resolve_config_auto(root=Path(root) if root else None)
    conn = open_store(config, root=Path(root) if root else None)

    try:
        client: QdrantClient | None = qdrant_client if qdrant_client is not None else _qdrant_client(config)
        dim = config.get("memory", {}).get("embedding_dim", 768)
        vectors_available = True
        try:
            ensure_collection(client, dim=dim)
        except Exception:
            vectors_available = False

        pii = contains_pii(text)
        raw_facts = extract_facts(text, config, http_post=http_post)

        saved: list[Fact] = []
        for raw in raw_facts:
            fact = Fact(text=raw["text"], category=raw["category"], scope=scope, root=root, session_id=session_id, pii=pii, created_at=time.time())
            fact = save_fact(conn, fact)

            if vectors_available:
                vector = embed_text(fact.text, config, http_post=http_post)
                if vector is not None:
                    try:
                        upsert_fact(client, fact_id=fact.id, vector=vector, scope=scope, root=root, pii=pii)
                    except Exception:
                        pass
            saved.append(fact)

        record_audit(config, actor="record_memory", action=scope, target=root or session_id or "unscoped", result="allow", detail={"fact_count": len(saved), "pii": pii})
        return saved
    finally:
        conn.close()


def query_memory(
    query: str,
    scope: str,
    root: str | None = None,
    allow_pii: bool = True,
    limit: int = 10,
    config: dict[str, Any] | None = None,
    http_post: HttpPost = default_http_post,
    qdrant_client: QdrantClient | None = None,
) -> list[Fact]:
    """Fused BM25 + vector retrieval over recorded facts, filtered by
    `scope` and `root`. NOTE: `scope="session"` is not filtered by
    session_id here — this returns all facts recorded under that scope,
    not just the calling session's. Tracked in docs/BACKLOG.md.
    """
    config = config if config is not None else resolve_config_auto(root=Path(root) if root else None)
    conn = open_store(config, root=Path(root) if root else None)

    try:
        client: QdrantClient | None = qdrant_client if qdrant_client is not None else _qdrant_client(config)
        dim = config.get("memory", {}).get("embedding_dim", 768)
        vectors_available = True
        try:
            ensure_collection(client, dim=dim)
        except Exception:
            vectors_available = False

        bm25_facts = search_fts(conn, query, scope=scope, root=root, limit=limit * 2)
        by_id = {f.id: f for f in bm25_facts}
        bm25_ids = [f.id for f in bm25_facts]

        vector_ids: list[int] = []
        if vectors_available:
            query_vector = embed_text(query, config, http_post=http_post)
            if query_vector is not None:
                try:
                    vector_ids = vector_search(client, query_vector, scope=scope, root=root, limit=limit * 2)
                except Exception:
                    vector_ids = []

        fused_ids = reciprocal_rank_fusion(bm25_ids, vector_ids)

        # vector search can surface fact ids the BM25 pass didn't fetch —
        # look those up individually rather than dropping them.
        results: list[Fact] = []
        for fact_id in fused_ids:
            fact = by_id.get(fact_id)
            if fact is None:
                row = conn.execute("SELECT id, text, category, scope, root, session_id, pii, created_at FROM facts WHERE id = ?", (fact_id,)).fetchone()
                if row is None:
                    continue
                fact = Fact(id=row[0], text=row[1], category=row[2], scope=row[3], root=row[4], session_id=row[5], pii=bool(row[6]), created_at=row[7])
            results.append(fact)

        excluded_count = 0
        if not allow_pii:
            kept = [f for f in results if not f.pii]
            excluded_count = len(results) - len(kept)
            results = kept

        if excluded_count:
            record_audit(config, actor="query_memory", action=scope, target=root or "unscoped", result="allow", detail={"pii_excluded_count": excluded_count})

        return results[:limit]
    finally:
        conn.close()
