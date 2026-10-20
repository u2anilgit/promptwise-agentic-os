import pytest
from sqlalchemy import text

from core.db.base import make_engine, session_scope
from core.db.migrate import current_revision, head_revision, migrate_to_head


def _config(tmp_path):
    return {"database": {"url": f"sqlite:///{(tmp_path / 't.db').as_posix()}"}}


def test_make_engine_uses_database_url_override(tmp_path):
    engine = make_engine(_config(tmp_path))
    assert engine.url.database == (tmp_path / "t.db").as_posix()


def test_make_engine_defaults_to_a_file_under_dot_promptwise(tmp_path):
    engine = make_engine({}, root=tmp_path)
    assert engine.url.database == (tmp_path / ".promptwise" / "agentic.sqlite3").as_posix()


def test_sqlite_pragmas_applied(tmp_path):
    engine = make_engine(_config(tmp_path))
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"


def test_session_scope_commits_on_success_and_rolls_back_on_error(tmp_path):
    config = _config(tmp_path)
    with session_scope(config) as s:
        s.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)"))
        s.execute(text("INSERT INTO t (v) VALUES ('kept')"))
    with pytest.raises(RuntimeError):
        with session_scope(config) as s:
            s.execute(text("INSERT INTO t (v) VALUES ('lost')"))
            raise RuntimeError("boom")
    with session_scope(config) as s:
        assert [r[0] for r in s.execute(text("SELECT v FROM t"))] == ["kept"]


def test_current_revision_is_none_before_migrate_and_does_not_create_the_file(tmp_path):
    config = _config(tmp_path)
    assert current_revision(config) is None
    assert not (tmp_path / "t.db").exists()


def test_migrate_to_head_from_empty_db_reaches_head(tmp_path):
    config = _config(tmp_path)
    reached = migrate_to_head(config)
    assert reached == head_revision()
    assert current_revision(config) == head_revision()


def test_migrate_to_head_is_idempotent(tmp_path):
    config = _config(tmp_path)
    migrate_to_head(config)
    assert migrate_to_head(config) == head_revision()


def test_migrate_to_head_skips_alembic_when_already_at_head(tmp_path, monkeypatch):
    """GET routes call migrate_to_head on every request; at head it must be a cheap revision read."""
    import core.db.migrate as migrate

    config = _config(tmp_path)
    migrate_to_head(config)
    calls = []
    monkeypatch.setattr(migrate.command, "upgrade", lambda *a, **k: calls.append(a))
    assert migrate_to_head(config) == head_revision()
    assert calls == []


def test_head_revision_is_cached(monkeypatch):
    import core.db.migrate as migrate

    head_revision()
    monkeypatch.setattr(migrate.ScriptDirectory, "from_config", lambda *a, **k: pytest.fail("rescanned"))
    assert head_revision()
