# core/index/store.py
"""SQLite-backed symbol table for the code index. A file's rows are
always replaced as a unit (delete-then-insert inside one transaction) —
there is no partial-update path, so a file's stored rows are always
consistent with the mtime that produced them.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from core.config.resolve import resolve_path
from core.index.models import CodeLocation

_SCHEMA = """
CREATE TABLE IF NOT EXISTS code_index (
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,
    file TEXT NOT NULL,
    line INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS indexed_file_mtimes (
    file TEXT PRIMARY KEY,
    mtime REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_code_index_symbol ON code_index(symbol);
CREATE INDEX IF NOT EXISTS idx_code_index_file ON code_index(file);
"""


def open_store(config: dict[str, Any], root: Path | None = None) -> sqlite3.Connection:
    db_path = resolve_path(config, "index.db_path", ".promptwise/code_index.sqlite3", root=root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # timeout: how long a writer waits on another connection's lock before
    # raising `database is locked`, instead of the sqlite3 default of 5s.
    # WAL mode lets concurrent readers proceed without blocking on a writer
    # — relevant once this verb is called from concurrent MCP requests.
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def get_stored_mtime(conn: sqlite3.Connection, file: str) -> float | None:
    row = conn.execute("SELECT mtime FROM indexed_file_mtimes WHERE file = ?", (file,)).fetchone()
    return row[0] if row is not None else None


def replace_file_rows(conn: sqlite3.Connection, file: str, mtime: float, locations: list[CodeLocation]) -> None:
    with conn:
        conn.execute("DELETE FROM code_index WHERE file = ?", (file,))
        conn.executemany(
            "INSERT INTO code_index (symbol, kind, file, line) VALUES (?, ?, ?, ?)",
            [(loc.symbol, loc.kind, loc.file, loc.line) for loc in locations],
        )
        conn.execute(
            "INSERT INTO indexed_file_mtimes (file, mtime) VALUES (?, ?) "
            "ON CONFLICT(file) DO UPDATE SET mtime = excluded.mtime",
            (file, mtime),
        )


def delete_file_rows(conn: sqlite3.Connection, file: str) -> None:
    with conn:
        conn.execute("DELETE FROM code_index WHERE file = ?", (file,))
        conn.execute("DELETE FROM indexed_file_mtimes WHERE file = ?", (file,))


def query_symbol(conn: sqlite3.Connection, symbol: str, kind: str | None = None) -> list[CodeLocation]:
    sql = "SELECT symbol, kind, file, line FROM code_index WHERE symbol LIKE ?"
    params: list[Any] = [f"%{symbol}%"]
    if kind is not None:
        sql += " AND kind = ?"
        params.append(kind)
    # exact match first, then substring, both alphabetical by file for a stable order
    sql += " ORDER BY (symbol != ?) ASC, file ASC, line ASC"
    params.append(symbol)

    rows = conn.execute(sql, params).fetchall()
    return [CodeLocation(symbol=s, kind=k, file=f, line=l) for s, k, f, l in rows]


def indexed_files(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT file FROM indexed_file_mtimes").fetchall()
    return {row[0] for row in rows}
