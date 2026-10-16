# core/memory/store.py
"""SQLite-backed fact storage with FTS5 lexical (BM25) search. External-
content FTS5 table (content='facts', content_rowid='id') — no built-in
sync triggers, so save_fact writes both tables in one transaction.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from core.config.resolve import resolve_path
from core.memory.models import Fact

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    category TEXT NOT NULL,
    scope TEXT NOT NULL,
    root TEXT,
    session_id TEXT,
    pii INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(text, content='facts', content_rowid='id');
CREATE INDEX IF NOT EXISTS idx_facts_scope_root ON facts(scope, root);
CREATE INDEX IF NOT EXISTS idx_facts_scope_session ON facts(scope, session_id);
"""


def open_store(config: dict[str, Any], root: Path | None = None) -> sqlite3.Connection:
    db_path = resolve_path(config, "memory.db_path", ".promptwise/memory.sqlite3", root=root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)  # same busy-timeout convention as core/index/store.py
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def save_fact(conn: sqlite3.Connection, fact: Fact) -> Fact:
    with conn:
        cursor = conn.execute(
            "INSERT INTO facts (text, category, scope, root, session_id, pii, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (fact.text, fact.category, fact.scope, fact.root, fact.session_id, int(fact.pii), fact.created_at),
        )
        fact_id = cursor.lastrowid
        conn.execute("INSERT INTO facts_fts (rowid, text) VALUES (?, ?)", (fact_id, fact.text))
    return fact.model_copy(update={"id": fact_id})


_FACT_COLUMNS = "id, text, category, scope, root, session_id, pii, created_at"


def _row_to_fact(row: tuple) -> Fact:
    # Single place that knows _FACT_COLUMNS' positional order.
    return Fact(id=row[0], text=row[1], category=row[2], scope=row[3], root=row[4], session_id=row[5], pii=bool(row[6]), created_at=row[7])


def get_fact(
    conn: sqlite3.Connection,
    fact_id: int,
    scope: str,
    root: str | None = None,
    session_id: str | None = None,
) -> Fact | None:
    """Fetch one fact by id, but only if it also satisfies the caller's
    scope/root/session predicates — defense in depth for ids that arrive
    from the vector store, which is not trusted to have filtered correctly.
    """
    sql = f"SELECT {_FACT_COLUMNS} FROM facts WHERE id = ? AND scope = ?"
    params: list[Any] = [fact_id, scope]
    if root is not None:
        sql += " AND root = ?"
        params.append(root)
    if session_id is not None:
        sql += " AND session_id = ?"
        params.append(session_id)
    row = conn.execute(sql, params).fetchone()
    return _row_to_fact(row) if row else None


def _sanitize_fts_query(query: str) -> str:
    # FTS5's query syntax treats punctuation specially (AND/OR/NOT, quotes,
    # NEAR, column filters, etc.). A raw user string could be malformed
    # syntax rather than a search term — extract word tokens and OR them,
    # same "treat untrusted input as a handled state" convention as the
    # rest of this repo, not a security fix (parameters are still bound).
    # Quoting each token makes FTS5 treat it as a literal phrase, preventing
    # FTS5 keywords (OR, AND, NOT) from being parsed as operators.
    tokens = re.findall(r"\w+", query)
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens)


def search_fts(
    conn: sqlite3.Connection,
    query: str,
    scope: str,
    root: str | None = None,
    limit: int = 10,
    session_id: str | None = None,
) -> list[Fact]:
    fts_query = _sanitize_fts_query(query)
    if not fts_query:
        return []

    sql = (
        "SELECT f.id, f.text, f.category, f.scope, f.root, f.session_id, f.pii, f.created_at "
        "FROM facts_fts JOIN facts f ON f.id = facts_fts.rowid "
        "WHERE facts_fts MATCH ? AND f.scope = ?"
    )
    params: list[Any] = [fts_query, scope]
    if root is not None:
        sql += " AND f.root = ?"
        params.append(root)
    if session_id is not None:
        sql += " AND f.session_id = ?"
        params.append(session_id)
    # bm25()'s score is negative; more negative = more relevant. ASC puts
    # the best match first (verified live against a real FTS5 table).
    sql += " ORDER BY bm25(facts_fts) ASC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [_row_to_fact(r) for r in rows]
