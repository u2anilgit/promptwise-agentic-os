import time

from core.memory.models import Fact
from core.memory.store import open_store, save_fact, search_fts


def _config(tmp_path):
    return {"memory": {"db_path": str(tmp_path / "memory.sqlite3")}}


def test_save_fact_assigns_an_id(tmp_path):
    conn = open_store(_config(tmp_path))
    fact = Fact(text="user prefers pytest", category="preference", scope="project", root="/repo", created_at=time.time())
    saved = save_fact(conn, fact)
    assert saved.id is not None


def test_search_fts_finds_a_saved_fact_by_lexical_match(tmp_path):
    conn = open_store(_config(tmp_path))
    save_fact(conn, Fact(text="user prefers pytest over unittest", category="preference", scope="project", root="/repo", created_at=time.time()))
    save_fact(conn, Fact(text="decided: SQLite for dev, Postgres for prod", category="decision", scope="project", root="/repo", created_at=time.time()))

    results = search_fts(conn, "pytest", scope="project", root="/repo")
    assert len(results) == 1
    assert "pytest" in results[0].text


def test_search_fts_scopes_by_root(tmp_path):
    conn = open_store(_config(tmp_path))
    save_fact(conn, Fact(text="alpha decision", category="decision", scope="project", root="/repo-a", created_at=time.time()))
    save_fact(conn, Fact(text="alpha decision elsewhere", category="decision", scope="project", root="/repo-b", created_at=time.time()))

    results = search_fts(conn, "alpha", scope="project", root="/repo-a")
    assert len(results) == 1
    assert results[0].root == "/repo-a"


def test_search_fts_scopes_by_session_not_root(tmp_path):
    conn = open_store(_config(tmp_path))
    save_fact(conn, Fact(text="working the login bug", category="context", scope="session", session_id="s1", created_at=time.time()))
    save_fact(conn, Fact(text="working the login bug elsewhere", category="context", scope="session", session_id="s2", created_at=time.time()))

    results = search_fts(conn, "login", scope="session", root=None)
    assert len(results) == 2  # session scope isn't root-filtered; caller filters by session_id itself if needed


def test_search_fts_no_match_returns_empty(tmp_path):
    conn = open_store(_config(tmp_path))
    save_fact(conn, Fact(text="user prefers pytest", category="preference", scope="project", root="/repo", created_at=time.time()))
    assert search_fts(conn, "nonexistent_term_xyz", scope="project", root="/repo") == []


def test_search_fts_respects_limit(tmp_path):
    conn = open_store(_config(tmp_path))
    for i in range(5):
        save_fact(conn, Fact(text=f"fact number {i} about testing", category="context", scope="project", root="/repo", created_at=time.time()))
    assert len(search_fts(conn, "testing", scope="project", root="/repo", limit=3)) == 3


def test_search_fts_survives_a_query_that_is_a_bare_fts5_keyword(tmp_path):
    conn = open_store(_config(tmp_path))
    save_fact(conn, Fact(text="user decided to use OR logic", category="decision", scope="project", root="/repo", created_at=time.time()))
    # Bare FTS5 keywords like "OR", "AND", "NOT" would crash without proper quoting.
    # Verify they are treated as literal search terms, not operators.
    results = search_fts(conn, "OR", scope="project", root="/repo")
    assert len(results) == 1
    assert "OR" in results[0].text

    # Also test "AND" and "NOT"
    save_fact(conn, Fact(text="decision about AND gates", category="decision", scope="project", root="/repo", created_at=time.time()))
    results = search_fts(conn, "AND", scope="project", root="/repo")
    assert len(results) == 1
    assert "AND" in results[0].text

    save_fact(conn, Fact(text="NOT a good approach", category="decision", scope="project", root="/repo", created_at=time.time()))
    results = search_fts(conn, "NOT", scope="project", root="/repo")
    assert len(results) == 1
    assert "NOT" in results[0].text
