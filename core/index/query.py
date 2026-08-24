# core/index/query.py
"""query_code_index — the public verb. Ties the walk/reindex/query steps
together: re-parses only files that changed since the last call (by
mtime), drops rows for files no longer on disk, then answers the query
against the now-current SQLite table.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from core.config.resolve import resolve_config_auto
from core.index.languages import LANGUAGES
from core.index.models import CodeLocation
from core.index.parser import parse_file
from core.index.store import (
    delete_file_rows,
    get_stored_mtime,
    indexed_files,
    open_store,
    query_symbol,
    replace_file_rows,
)

_IGNORED_DIR_NAMES = {".git", "node_modules", "__pycache__", ".venv", "venv"}


def _iter_source_files(root: Path):
    """os.walk, not Path.rglob: dirnames is mutated in place so ignored
    directories (node_modules, .git, ...) are pruned before the walk
    descends into them, rather than filtered out of results after the
    fact. followlinks=False (the default) so a symlink cycle under root
    can't recurse indefinitely. A PermissionError while listing one
    subdirectory is a handled state, not an exception (os.walk's default
    behavior: skip that subtree, keep walking) — matches the FileNotFoundError
    race handled a few lines below in query_code_index.
    """
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [
            name for name in dirnames
            if name not in _IGNORED_DIR_NAMES and not name.startswith(".")
        ]
        for filename in filenames:
            path = Path(dirpath) / filename
            if path.suffix in LANGUAGES:
                yield path


def query_code_index(
    symbol: str,
    kind: str | None = None,
    root: Path | None = None,
    config: dict[str, Any] | None = None,
) -> list[CodeLocation]:
    root = root if root is not None else Path.cwd()
    if not root.exists():
        return []

    config = config if config is not None else resolve_config_auto(root=root)
    conn = open_store(config, root=root)
    try:
        seen_files: set[str] = set()
        for path in _iter_source_files(root):
            file_key = str(path)
            seen_files.add(file_key)
            try:
                current_mtime = path.stat().st_mtime
            except FileNotFoundError:
                continue  # vanished between the walk and the stat() call — treat as not present

            if get_stored_mtime(conn, file_key) == current_mtime:
                continue  # unchanged since last index

            locations = parse_file(path)
            replace_file_rows(conn, file_key, current_mtime, locations)

        for stale_file in indexed_files(conn) - seen_files:
            delete_file_rows(conn, stale_file)

        return query_symbol(conn, symbol, kind)
    finally:
        conn.close()
