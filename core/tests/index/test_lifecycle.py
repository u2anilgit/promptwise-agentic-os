"""Regression coverage for the code index's connection lifecycle (review findings that shipped without
tests): WAL mode, a generous lock timeout, and query_code_index always closing its connection."""
import sqlite3

import core.index.query as query_module
from core.index.query import query_code_index
from core.index.store import open_store


def _config(tmp_path):
    return {"index": {"db_path": str(tmp_path / "idx.sqlite3")}}


def test_store_uses_wal_mode(tmp_path):
    conn = open_store(_config(tmp_path), root=tmp_path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()


def test_store_waits_on_locks_instead_of_failing_fast(tmp_path, monkeypatch):
    seen = {}
    real = sqlite3.connect

    def connect(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    open_store(_config(tmp_path), root=tmp_path).close()
    assert seen.get("timeout", 5.0) >= 30.0


def test_query_closes_its_connection_even_when_parsing_fails(tmp_path, monkeypatch):
    closed = []
    real_open = query_module.open_store

    def tracking_open(*args, **kwargs):
        conn = real_open(*args, **kwargs)

        class Tracked:
            def __getattr__(self, name):
                return getattr(conn, name)

            def close(self):
                closed.append(True)
                conn.close()

        return Tracked()

    def boom(path):
        raise RuntimeError("parser crashed")

    (tmp_path / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(query_module, "open_store", tracking_open)
    monkeypatch.setattr(query_module, "parse_file", boom)
    try:
        query_code_index("f", root=tmp_path, config=_config(tmp_path))
    except RuntimeError:
        pass
    assert closed == [True]
