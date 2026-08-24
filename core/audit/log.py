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
    """The chain's tip hash. Every record_audit call needs this, so it
    must not degrade to O(file size) as the log grows — a full read-per-
    write turns a long session's audit trail into an O(n^2) bottleneck.
    Seeks backward from EOF in growing chunks instead of scanning from
    the start; verify_chain still reads the whole file (it has to, to
    check every link) but that's an explicit, occasional operation.
    """
    if not path.exists():
        return GENESIS_HASH

    file_size = path.stat().st_size
    if file_size == 0:
        return GENESIS_HASH

    chunk_size = 4096
    with path.open("rb") as f:
        read_size = min(chunk_size, file_size)
        while True:
            f.seek(-read_size, 2)
            data = f.read(read_size)
            # rstrip \r too: defensive against a log written on a platform
            # (or an older version of this file) that emitted CRLF line
            # endings — the trailing \r must not get left dangling and
            # mistaken for content on the last line.
            stripped = data.rstrip(b"\r\n")
            if b"\n" in stripped or read_size >= file_size:
                break
            read_size = min(read_size * 2, file_size)

    last_line = stripped.rsplit(b"\n", 1)[-1].rstrip(b"\r")
    if not last_line.strip():
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

    # newline="" pins LF-only line endings regardless of platform — JSONL
    # convention, and required for _last_hash's binary tail-seek below to
    # find line boundaries without also having to strip CRLF.
    with path.open("a", encoding="utf-8", newline="") as f:
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
