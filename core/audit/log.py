# core/audit/log.py
"""Hash-chained audit log — docs/ARCHITECTURE.md §2, docs/MAINTENANCE.md §2
(the audit.chain doctor check). Append-only JSONL, config-resolved path
(same resolve_path pattern as Phase 1/2's other file-backed stores). Each
record's hash covers the previous record's hash, so tampering with any
record breaks every hash after it — verify_chain walks the file and
reports the first break.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.audit.models import AuditRecord
from core.config.resolve import resolve_path

GENESIS_HASH = "0" * 64


def _log_path(config: dict[str, Any]) -> Path:
    return resolve_path(config, "audit.log_path", ".promptwise/audit.jsonl")


def _record_hash(record_without_hash: dict[str, Any]) -> str:
    canonical = json.dumps(record_without_hash, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _last_hash(path: Path) -> str:
    if not path.exists():
        return GENESIS_HASH
    last_line = None
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                last_line = line
    if last_line is None:
        return GENESIS_HASH
    return json.loads(last_line)["hash"]


def record_audit(
    config: dict[str, Any],
    actor: str,
    action: str,
    target: str,
    result: str,
    detail: dict[str, Any] | None = None,
) -> AuditRecord:
    path = _log_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    prev_hash = _last_hash(path)

    body = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "action": action,
        "target": target,
        "result": result,
        "detail": detail or {},
        "prev_hash": prev_hash,
    }
    record_hash = _record_hash(body)
    record = AuditRecord(**body, hash=record_hash)

    with path.open("a", encoding="utf-8") as f:
        f.write(record.model_dump_json() + "\n")

    return record


def verify_chain(config: dict[str, Any]) -> tuple[bool, int | None]:
    path = _log_path(config)
    if not path.exists():
        return True, None

    prev_hash = GENESIS_HASH
    with path.open("r", encoding="utf-8") as f:
        for index, line in enumerate(f):
            if not line.strip():
                continue
            data = json.loads(line)
            claimed_hash = data.pop("hash")
            if data["prev_hash"] != prev_hash:
                return False, index
            if _record_hash(data) != claimed_hash:
                return False, index
            prev_hash = claimed_hash

    return True, None
