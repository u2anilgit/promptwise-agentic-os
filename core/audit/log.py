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
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from core.audit.models import AuditRecord
from core.config.resolve import resolve_path

GENESIS_HASH = "0" * 64
MAX_DETAIL_BYTES = 32 * 1024


def _log_path(config: dict[str, Any]) -> Path:
    return resolve_path(config, "audit.log_path", ".promptwise/agentic_audit.jsonl")


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

    detail = detail or {}
    encoded = json.dumps(detail, default=str)
    if len(encoded.encode("utf-8")) > MAX_DETAIL_BYTES:  # a hostile caller cannot bloat the log
        detail = {"truncated": True, "original_bytes": len(encoded.encode("utf-8"))}

    body = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "action": action,
        "target": target,
        "result": result,
        "detail": detail,
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


class ChainStatus(BaseModel):
    ok: bool
    broken_at: int | None = None


@dataclass
class _Verified:
    offset: int  # bytes of complete, verified lines
    digest: Any  # sha256 over those bytes, so an edit anywhere in the prefix is noticed
    prev_hash: str
    lines: int


_VERIFIED: dict[str, _Verified] = {}
_VERIFIED_LOCK = threading.Lock()
_READ_CHUNK = 1 << 20


def chain_status(config: dict[str, Any]) -> ChainStatus:
    """verify_chain for frequent callers (the dashboard polls it). The verified prefix is re-digested as
    raw bytes on every call (cheap) instead of re-parsed and re-hashed record by record, so an append costs
    the new records only while any edit, truncation or same-size rewrite of earlier bytes is still caught
    and triggers a full re-verification. A trailing line without its newline (a writer mid-append) is left
    for the next call. Malformed lines report as a break rather than raising."""
    path = _log_path(config)
    key = str(path.resolve())
    with _VERIFIED_LOCK:
        if not path.exists():
            _VERIFIED.pop(key, None)
            return ChainStatus(ok=True)
        state = _VERIFIED.get(key)
        with path.open("rb") as f:
            if state is not None and not _prefix_matches(f, state):
                state = None
            if state is None:
                f.seek(0)
                state = _Verified(offset=0, digest=hashlib.sha256(), prev_hash=GENESIS_HASH, lines=0)
            broken_at = _verify_from(f, state)
        if broken_at is not None:
            _VERIFIED.pop(key, None)
            return ChainStatus(ok=False, broken_at=broken_at)
        _VERIFIED[key] = state
        return ChainStatus(ok=True)


def _prefix_matches(f, state: _Verified) -> bool:
    digest = hashlib.sha256()
    remaining = state.offset
    while remaining:
        chunk = f.read(min(_READ_CHUNK, remaining))
        if not chunk:
            return False  # the file is shorter than what was verified
        digest.update(chunk)
        remaining -= len(chunk)
    return digest.digest() == state.digest.digest()


def _read_chunk(f) -> bytes:
    return f.read(_READ_CHUNK)


def _verify_from(f, state: _Verified) -> int | None:
    """Verify complete lines from the current position (state.offset), advancing state in place.
    Returns the zero-based line index of the first break, or None."""
    pending: list[bytes] = []  # pieces of a line still waiting for its newline (each chunk is split once)
    while True:
        chunk = _read_chunk(f)
        if not chunk:
            return None
        *complete, rest = chunk.split(b"\n")
        if complete:
            complete[0] = b"".join(pending) + complete[0]
            pending = []
        pending.append(rest)
        for raw in complete:
            line = raw + b"\n"
            if raw.strip():
                try:
                    data = json.loads(raw.decode("utf-8"))
                    claimed_hash = data.pop("hash")
                    intact = data["prev_hash"] == state.prev_hash and _record_hash(data) == claimed_hash
                except (ValueError, KeyError, TypeError, AttributeError):
                    intact = False
                if not intact:
                    return state.lines
                state.prev_hash = claimed_hash
            state.digest.update(line)
            state.offset += len(line)
            state.lines += 1
