# core/policy/jit.py
"""JIT (just-in-time) permission grants — docs/ARCHITECTURE.md §2's
grant_jit_permission concept. Time-boxed, scope-keyed grants persisted to
a JSON file (same tier of durability as Phase 2's failure ledger) —
expired grants are treated as absent, never specially flagged, so a
caller checking `check_jit_grant` gets a plain bool.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from core.config.resolve import resolve_path


class JitGrant(BaseModel):
    scope: str
    granted_at: str
    expires_at: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _grants_path(config: dict[str, Any]) -> Path:
    return resolve_path(config, "policy.jit_grants_path", ".promptwise/jit_grants.json")


def _load_grants(config: dict[str, Any]) -> dict[str, JitGrant]:
    path = _grants_path(config)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        return {scope: JitGrant(**value) for scope, value in raw.items()}
    except (json.JSONDecodeError, ValueError):
        return {}


def _save_grants(config: dict[str, Any], grants: dict[str, JitGrant]) -> None:
    path = _grants_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump({scope: grant.model_dump() for scope, grant in grants.items()}, f, indent=2)
    tmp_path.replace(path)


def grant_jit_permission(config: dict[str, Any], scope: str, ttl_seconds: int) -> JitGrant:
    now = _now()
    grant = JitGrant(
        scope=scope,
        granted_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=ttl_seconds)).isoformat(),
    )
    grants = _load_grants(config)
    grants[scope] = grant
    _save_grants(config, grants)
    return grant


def check_jit_grant(config: dict[str, Any], scope: str) -> bool:
    grants = _load_grants(config)
    grant = grants.get(scope)
    if grant is None:
        return False
    return datetime.fromisoformat(grant.expires_at) > _now()
