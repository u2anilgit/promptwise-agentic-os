# core/db/base.py
"""Shared persistence foundation — SQLAlchemy 2.0 declarative Base, engine
factory and a transactional session scope. All new durable state uses this
layer; schema changes ship as Alembic revisions under core/migrations/.
Types stay portable (no SQLite-only SQL) so `database.url` can point at
Postgres with no model change.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session

from core.config.resolve import resolve_path


class Base(DeclarativeBase):
    pass


def database_url(config: dict[str, Any], root: Path | None = None) -> str:
    url = config.get("database", {}).get("url", "")
    if url:
        return url
    path = resolve_path(config, "database.path", ".promptwise/agentic.sqlite3", root=root)
    return f"sqlite:///{path.as_posix()}"


def make_engine(config: dict[str, Any], root: Path | None = None) -> Engine:
    url = database_url(config, root)
    if url.startswith("sqlite"):
        path = url.removeprefix("sqlite:///")
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _record):  # noqa: ANN001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


@contextmanager
def session_scope(config: dict[str, Any], root: Path | None = None) -> Iterator[Session]:
    engine = make_engine(config, root)
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()
