# core/audit/read.py
"""Read side of the hash-chained audit log, for the dashboard and any other viewer.

Cursors are byte offsets into the JSONL file, so a reader can resume exactly where it
stopped. A trailing line without its newline is a writer mid-append: it is never
consumed and the cursor stays in front of it, so it is delivered whole on the next read.
Malformed lines are skipped rather than fatal; the hash-chain verdict (`chain_status`)
is where tampering is reported. A cursor beyond the end of the file means the log was
replaced by a shorter one: the reader restarts at 0.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from core.audit.log import _log_path
from core.audit.models import AuditRecord

MIN_LIMIT = 1
MAX_LIMIT = 500
MAX_READ_BYTES = 8 * 1024 * 1024  # one read never pulls more than this into memory
SKIP_CHUNK = 1024 * 1024
TAIL_CHUNK = 256 * 1024  # tail reads walk backwards in chunks of this size


class AuditPage(BaseModel):
    records: list[AuditRecord]
    next_cursor: int
    # True when a tail read could not show everything that matches (more matches than the limit, or the
    # scan budget ended before the start of the log): an empty or short result then means "not looked far
    # enough", not "nothing happened".
    truncated: bool = False


def log_size(config: dict[str, Any]) -> int:
    path: Path = _log_path(config)
    return path.stat().st_size if path.exists() else 0


def _clamp(limit: int) -> int:
    return max(MIN_LIMIT, min(int(limit), MAX_LIMIT))


def _parse(line: bytes) -> AuditRecord | None:
    try:
        return AuditRecord(**json.loads(line.decode("utf-8")))
    except (ValueError, TypeError):
        return None


def _matches(record: AuditRecord, action: str | None, result: str | None, target: str | None = None) -> bool:
    return (
        (action is None or record.action == action)
        and (result is None or record.result == result)
        and (target is None or record.target == target)
    )


def _skip_oversized_line(path: Path, position: int) -> int:
    """A single line longer than MAX_READ_BYTES would pin the cursor forever. Move past its newline
    (the oversized line is treated as malformed); if it has none yet, stop where we got to."""
    with path.open("rb") as f:
        f.seek(position)
        while True:
            chunk = f.read(SKIP_CHUNK)
            if not chunk:
                return position
            newline = chunk.find(b"\n")
            if newline != -1:
                return position + newline + 1
            position += len(chunk)


def read_audit(
    config: dict[str, Any], after: int = 0, limit: int = 100, action: str | None = None, result: str | None = None,
    target: str | None = None,
) -> AuditPage:
    path: Path = _log_path(config)
    limit = _clamp(limit)
    after = max(0, int(after))
    if not path.exists():
        return AuditPage(records=[], next_cursor=0)
    size = path.stat().st_size
    if after > size:
        after = 0
    cursor = after

    records: list[AuditRecord] = []
    with path.open("rb") as f:
        f.seek(after)
        data = f.read(MAX_READ_BYTES)
    offset = 0
    while len(records) < limit:
        end = data.find(b"\n", offset)
        if end == -1:  # partial trailing line (or nothing left): stop in front of it
            break
        line = data[offset:end].rstrip(b"\r")
        offset = end + 1
        cursor = after + offset
        if not line.strip():
            continue
        record = _parse(line)
        if record is not None and _matches(record, action, result, target):
            records.append(record)
    if cursor == after and len(data) >= MAX_READ_BYTES and b"\n" not in data:
        cursor = _skip_oversized_line(path, after + len(data))
    return AuditPage(records=records, next_cursor=cursor)


def read_audit_tail(
    config: dict[str, Any], limit: int = 100, action: str | None = None, result: str | None = None,
    target: str | None = None,
) -> AuditPage:
    """The newest `limit` matching records, oldest first; next_cursor is the end of the last complete line.

    Walks the file backwards in TAIL_CHUNK pieces, parsing each line once, and stops after MAX_READ_BYTES
    or once `limit` + 1 matches are known (the extra one only proves there were more)."""
    path: Path = _log_path(config)
    limit = _clamp(limit)
    if not path.exists():
        return AuditPage(records=[], next_cursor=0)

    size = path.stat().st_size
    found: list[AuditRecord] = []  # newest first while scanning
    carry = b""  # the (possibly cut) first line of the chunk above the one being read
    position = size
    consumed = 0
    next_cursor = size
    first = True
    with path.open("rb") as f:
        while position > 0 and consumed < MAX_READ_BYTES and len(found) <= limit:
            start = max(0, position - TAIL_CHUNK)
            f.seek(start)
            data = f.read(position - start) + carry
            consumed += position - start
            lines = data.split(b"\n")
            if first:
                partial = lines.pop()  # text after the final newline: empty, or a writer mid-append
                next_cursor = size - len(partial)
                first = False
            if start > 0:
                carry = lines.pop(0)  # may be cut at the chunk boundary: finish it with the next chunk down
            else:
                carry = b""
            position = start
            for raw in reversed(lines):
                line = raw.rstrip(b"\r")
                if not line.strip():
                    continue
                record = _parse(line)
                if record is not None and _matches(record, action, result, target):
                    found.append(record)
                    if len(found) > limit:
                        break
    reached_start = position == 0 and not carry
    more_than_limit = len(found) > limit
    return AuditPage(
        records=list(reversed(found[:limit])),
        next_cursor=next_cursor,
        truncated=more_than_limit or not reached_start,
    )
