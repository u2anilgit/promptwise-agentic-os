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


class AuditPage(BaseModel):
    records: list[AuditRecord]
    next_cursor: int


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
    """The newest `limit` matching records, oldest first; next_cursor is the end of the last complete line."""
    path: Path = _log_path(config)
    limit = _clamp(limit)
    if not path.exists():
        return AuditPage(records=[], next_cursor=0)

    size = path.stat().st_size
    window = 64 * 1024
    while True:
        window = min(window, MAX_READ_BYTES)
        start = max(0, size - window)
        with path.open("rb") as f:
            f.seek(max(0, start - 1))  # one byte of look-behind: is `start` on a line boundary?
            data = f.read(size - max(0, start - 1))
        if start > 0:
            on_boundary = data[:1] == b"\n"
            data = data[1:]
        else:
            on_boundary = True
        complete_end = data.rfind(b"\n") + 1  # drop a partial trailing line
        body = data[:complete_end]
        if not on_boundary:  # the first line of the window is probably cut: drop it
            first_nl = body.find(b"\n")
            body = body[first_nl + 1:] if first_nl != -1 else b""
        found: list[AuditRecord] = []
        for line in body.split(b"\n"):
            line = line.rstrip(b"\r")
            if not line.strip():
                continue
            record = _parse(line)
            if record is not None and _matches(record, action, result, target):
                found.append(record)
        if len(found) >= limit or start == 0 or window >= MAX_READ_BYTES:
            return AuditPage(records=found[-limit:], next_cursor=start + complete_end)
        window *= 4
