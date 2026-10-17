# gateway/auth.py
"""Bearer-token auth for the gateway's HTTP surface (docs/superpowers/specs/2026-10-17-dashboard-design.md, D1).

One operator-owned token in `gateway.token_path`, generated on first use and re-read on every
request (replace the file to rotate). Comparison is constant-time; denials are audited but
rate-limited so an unauthenticated flood cannot grow the audit log, and the offered credential
is never recorded.
"""
from __future__ import annotations

import hmac
import os
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from core.audit.log import record_audit
from core.config.resolve import resolve_path
from gateway.mcp_guard import operator_config

DEFAULT_TOKEN_PATH = ".promptwise/dashboard_token"
DENIAL_AUDIT_INTERVAL = 1.0

_last_denial_audit = 0.0
_suppressed = 0


def reset_denial_throttle() -> None:
    global _last_denial_audit, _suppressed
    _last_denial_audit, _suppressed = 0.0, 0


def token_path(op: dict[str, Any]) -> Path:
    return resolve_path(op, "gateway.token_path", DEFAULT_TOKEN_PATH, root=Path.cwd())


def load_or_create_token(op: dict[str, Any] | None = None) -> str:
    op = op if op is not None else operator_config()
    path = token_path(op)
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if existing:
        return existing
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:  # best effort; not meaningful on every platform
        pass
    return token


def _offered(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme == "Bearer" else ""


def _audit_denial(op: dict[str, Any], request: Request) -> None:
    global _last_denial_audit, _suppressed
    now = time.monotonic()
    if _last_denial_audit and now - _last_denial_audit < DENIAL_AUDIT_INTERVAL:
        _suppressed += 1
        return
    detail = {"path": request.url.path, "method": request.method, "suppressed_since_last": _suppressed}
    _last_denial_audit, _suppressed = now, 0
    try:
        record_audit(op, actor="api", action="api_auth_denied", target=request.url.path, result="deny", detail=detail)
    except Exception:  # noqa: BLE001 - an unwritable audit log must not turn a 401 into a 500
        pass


def require_token(request: Request) -> None:
    op = operator_config()
    expected = load_or_create_token(op)  # always created, so a first rejected request still leaves a usable token
    offered = _offered(request)
    if not offered or not hmac.compare_digest(offered.encode("utf-8"), expected.encode("utf-8")):
        _audit_denial(op, request)
        raise HTTPException(status_code=401, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"})
