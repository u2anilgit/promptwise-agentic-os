# gateway/api/v1.py
"""Authenticated, read-only dashboard API (docs/superpowers/specs/2026-10-17-dashboard-design.md, D2).

Every route is a GET over a core verb; nothing here mutates state. Paths and settings come from
the operator config, never the project's. Strings in responses (audit `detail`, requests, facts)
are data: the UI must render them as escaped text.
"""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from core.audit.log import ChainStatus, chain_status
from core.audit.read import AuditPage, read_audit, read_audit_tail
from core.diagnostics.checks import run_diagnostics
from core.policy.engine import load_policy
from core.spec.engine import SpecStatus, list_specs, spec_status
from core.spec.models import SpecSummary
from gateway.auth import require_token
from gateway.mcp_guard import operator_config, pinned_config

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_token)])

HEARTBEAT_SECONDS = 15.0
MAX_STREAMS = 16
_active_streams = 0


def _config() -> dict[str, Any]:
    return pinned_config(operator_config())  # no project layer: an agent-writable config cannot break or redirect the API


class AuditResponse(AuditPage):
    chain: ChainStatus


@router.get("/audit", response_model=AuditResponse)
def audit(
    cursor: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    action: str | None = Query(None, max_length=100),
    result: Literal["allow", "deny", "error"] | None = None,
    tail: bool = False,
) -> AuditResponse:
    config = _config()
    page = read_audit_tail(config, limit, action, result) if tail else read_audit(config, cursor, limit, action, result)
    return AuditResponse(records=page.records, next_cursor=page.next_cursor, chain=chain_status(config))


@router.get("/specs", response_model=list[SpecSummary])
def specs() -> list[SpecSummary]:
    return list_specs(config=_config(), root=Path.cwd())


@router.get("/specs/{spec_id}", response_model=SpecStatus)
def spec_detail(spec_id: str) -> SpecStatus:
    try:
        return spec_status(spec_id, config=_config(), root=Path.cwd())
    except ValueError:
        raise HTTPException(status_code=404, detail="not found") from None


@router.get("/policy")
def policy() -> dict[str, Any]:
    config = _config()
    return {
        "default_effect": config.get("policy", {}).get("default_effect", "deny"),
        "rules": [rule.model_dump() for rule in load_policy(config)],
    }


@router.get("/diagnostics")
def diagnostics() -> list[dict[str, Any]]:
    return [result.model_dump() for result in run_diagnostics(_config())]


async def audit_events(
    config: dict[str, Any], cursor: int, max_seconds: float, poll_seconds: float
) -> AsyncIterator[str]:
    """SSE chunks for audit records appended after `cursor`. `id:` is the byte cursor after the batch
    (set on its last event only, so a drop mid-batch resumes at-least-once; clients de-duplicate by
    record id). Ends after `max_seconds`; EventSource-style clients reconnect with Last-Event-ID."""
    deadline = time.monotonic() + max_seconds
    last_beat = time.monotonic()
    while time.monotonic() < deadline:
        page = await asyncio.to_thread(read_audit, config, cursor, 100)
        if page.next_cursor != cursor:
            for index, record in enumerate(page.records):
                id_line = f"id: {page.next_cursor}\n" if index == len(page.records) - 1 else ""
                yield f"{id_line}event: audit\ndata: {record.model_dump_json()}\n\n"
            cursor = page.next_cursor
            last_beat = time.monotonic()
            if len(page.records) >= 100:
                continue  # more may be waiting: read again without sleeping
        elif time.monotonic() - last_beat >= HEARTBEAT_SECONDS:
            last_beat = time.monotonic()
            yield ": keepalive\n\n"
        await asyncio.sleep(poll_seconds)


async def _bounded(stream: AsyncIterator[str]) -> AsyncIterator[str]:
    global _active_streams
    try:
        async for chunk in stream:
            yield chunk
    finally:
        _active_streams -= 1


@router.get("/events")
async def events(
    cursor: int | None = Query(None, ge=0),
    last_event_id: str | None = Header(None),
) -> StreamingResponse:
    config = _config()
    if cursor is None and last_event_id is not None and re.fullmatch(r"\d{1,18}", last_event_id):
        cursor = int(last_event_id)
    if cursor is None:  # default: only what arrives from now on
        cursor = read_audit_tail(config, limit=1).next_cursor
    gateway = config.get("gateway", {})
    global _active_streams
    if _active_streams >= MAX_STREAMS:
        raise HTTPException(status_code=429, detail="too many event streams")
    _active_streams += 1
    stream = audit_events(
        config, cursor, float(gateway.get("sse_max_seconds", 300)), float(gateway.get("sse_poll_seconds", 1.0))
    )
    return StreamingResponse(
        _bounded(stream), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    )
