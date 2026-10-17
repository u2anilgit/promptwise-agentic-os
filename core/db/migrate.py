# core/db/migrate.py
"""Programmatic Alembic — no alembic.ini. The engine is handed to
core/migrations/env.py through Config.attributes."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from core.db.base import database_url, make_engine

# Alembic loads its script modules into shared interpreter state: concurrent callers in one process
# (threaded gateway routes) must take turns, or the loader raises mid-import.
_MIGRATE_LOCK = threading.Lock()
_SCRIPT_LOCATION = Path(__file__).resolve().parent.parent / "migrations"


def _alembic_config(engine=None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
    if engine is not None:
        cfg.attributes["engine"] = engine
    return cfg


def head_revision() -> str:
    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    assert head is not None
    return head


def known_revisions() -> set[str]:
    return {rev.revision for rev in ScriptDirectory.from_config(_alembic_config()).walk_revisions()}


def _sqlite_file_missing(config: dict[str, Any], root: Path | None) -> bool:
    url = database_url(config, root)
    if not url.startswith("sqlite") or url.endswith(":memory:"):
        return False
    return not Path(url.removeprefix("sqlite:///")).exists()


def current_revision(config: dict[str, Any], root: Path | None = None) -> str | None:
    """The DB's applied revision, or None. Never creates a missing SQLite file."""
    if _sqlite_file_missing(config, root):
        return None
    engine = make_engine(config, root)
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()


def migrate_to_head(config: dict[str, Any], root: Path | None = None) -> str:
    with _MIGRATE_LOCK:
        current = current_revision(config, root)
        if current is not None and current not in known_revisions():
            raise ValueError(
                f"database revision {current} is newer than this code (head {head_revision()}) - "
                "upgrade the code; do not downgrade the data"
            )
        engine = make_engine(config, root)
        try:
            command.upgrade(_alembic_config(engine), "head")
        finally:
            engine.dispose()
        return head_revision()
