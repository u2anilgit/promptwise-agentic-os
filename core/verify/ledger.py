# core/verify/ledger.py
"""Failure ledger — docs/ROADMAP.md Phase 2 row: breaks an identical-failure
retry loop after N attempts. A JSON file, config-resolved via resolve_path
(same pattern Phase 1 established for packs/catalog paths) — no database
yet, that's a Phase 4+ concern.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from core.config.resolve import resolve_path


class LedgerEntry(BaseModel):
    key: str
    failure_count: int
    last_signature: str
    last_seen: str


def _ledger_path(config: dict[str, Any]) -> Path:
    return resolve_path(config, "verify.failure_ledger_path", ".promptwise/failure_ledger.json")


def load_ledger(config: dict[str, Any]) -> dict[str, LedgerEntry]:
    """A corrupt or unparseable ledger file is treated the same as a
    missing one — degrading gracefully rather than crashing the
    verification gate itself (a truncated/malformed file must never turn
    into a 500 from /verify or an exception from the MCP tool).
    """
    path = _ledger_path(config)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        return {key: LedgerEntry(**value) for key, value in raw.items()}
    except (json.JSONDecodeError, ValueError):
        return {}


def save_ledger(config: dict[str, Any], ledger: dict[str, LedgerEntry]) -> None:
    """Writes atomically: a temp file in the same directory, then an
    os.replace onto the real path, so a process killed mid-write can never
    leave a torn/corrupt ledger file behind.
    """
    path = _ledger_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump({key: entry.model_dump() for key, entry in ledger.items()}, f, indent=2)
    os.replace(tmp_path, path)


def record_failure(config: dict[str, Any], key: str, signature: str) -> bool:
    """Records a failure under `key`. Returns True if this exact `signature`
    has now repeated `max_identical_failures` times in a row — the caller
    should stop retrying and surface this to the human/agent instead.
    """
    ledger = load_ledger(config)
    max_identical = config.get("verify", {}).get("max_identical_failures", 3)
    now = datetime.now(timezone.utc).isoformat()

    existing = ledger.get(key)
    if existing is not None and existing.last_signature == signature:
        count = existing.failure_count + 1
    else:
        count = 1

    ledger[key] = LedgerEntry(key=key, failure_count=count, last_signature=signature, last_seen=now)
    save_ledger(config, ledger)
    return count >= max_identical


def record_success(config: dict[str, Any], key: str) -> None:
    ledger = load_ledger(config)
    if key in ledger:
        del ledger[key]
        save_ledger(config, ledger)
