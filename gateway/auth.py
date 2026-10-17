# gateway/auth.py
"""Bearer auth for the gateway's HTTP surface (docs/superpowers/specs/2026-10-17-dashboard-design.md, D1).

One operator-owned credential file (`gateway.token_path`, default under the user's home, NOT the
gateway's working directory, which may be a project an agent can edit). Generated on first use
with owner-only permissions, re-read per request (replace the file to rotate). Anything wrong with
the file (unwritable, a symlink, too short) fails closed with 503, never 500 and never accepted.
Comparison is constant-time; denials are audited with the client address, throttled per
(client, path) so a flood cannot grow the log, and the offered value is never recorded.
"""
from __future__ import annotations

import hmac
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from core.audit.log import record_audit
from gateway.mcp_guard import operator_config

DEFAULT_TOKEN_PATH = "~/.promptwise/dashboard_token"
MIN_CREDENTIAL_LENGTH = 32
DENIAL_AUDIT_INTERVAL = 1.0
MAX_THROTTLE_KEYS = 256

log = logging.getLogger(__name__)
_last_audit: dict[tuple[str, str], float] = {}
_suppressed: dict[tuple[str, str], int] = {}


class CredentialUnavailable(Exception):
    pass


def reset_denial_throttle() -> None:
    _last_audit.clear()
    _suppressed.clear()


def token_path(op: dict[str, Any]) -> Path:
    configured = (op.get("gateway") or {}).get("token_path") or DEFAULT_TOKEN_PATH
    path = Path(os.path.expanduser(str(configured)))
    return path if path.is_absolute() else Path.cwd() / path


def _read(path: Path) -> str:
    if path.is_symlink():
        raise CredentialUnavailable(f"credential file {path} is a symlink")
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise CredentialUnavailable(f"credential file {path} is unreadable: {exc}") from exc


def _create(path: Path, truncate: bool) -> None:
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if truncate else os.O_EXCL)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, flags, 0o600)  # private from the first byte, not chmod'ed afterwards
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(secrets.token_urlsafe(32) + "\n")


def load_or_create_token(op: dict[str, Any] | None = None) -> str:
    op = op if op is not None else operator_config()
    path = token_path(op)
    try:
        existing = _read(path)
        if not existing:
            try:
                _create(path, truncate=path.exists())  # empty file: re-initialise; absent: exclusive create
            except FileExistsError:  # lost a creation race: use the winner's value
                pass
            existing = _read(path)
    except OSError as exc:
        raise CredentialUnavailable(f"credential file {path} cannot be created: {exc}") from exc
    if len(existing) < MIN_CREDENTIAL_LENGTH:
        raise CredentialUnavailable(f"credential file {path} holds fewer than {MIN_CREDENTIAL_LENGTH} characters")
    return existing


def _offered(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


def _audit_denial(op: dict[str, Any], request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    key = (client, request.url.path)
    now = time.monotonic()
    last = _last_audit.get(key)
    if last is not None and now - last < DENIAL_AUDIT_INTERVAL:
        _suppressed[key] = _suppressed.get(key, 0) + 1
        return
    if len(_last_audit) >= MAX_THROTTLE_KEYS:  # bounded memory under a spray of distinct clients/paths
        reset_denial_throttle()
    detail = {"path": request.url.path, "method": request.method, "client": client,
              "suppressed_since_last": _suppressed.pop(key, 0)}
    _last_audit[key] = now
    try:
        record_audit(op, actor="api", action="api_auth_denied", target=request.url.path, result="deny", detail=detail)
    except Exception:  # noqa: BLE001 - an unwritable audit log must not turn a 401 into a 500
        log.exception("could not audit an authentication denial")


def require_token(request: Request) -> None:
    op = operator_config()
    try:
        expected = load_or_create_token(op)
    except CredentialUnavailable as exc:
        log.error("%s", exc)
        raise HTTPException(status_code=503, detail="credential unavailable") from None
    offered = _offered(request)
    if not offered or not hmac.compare_digest(offered.encode("utf-8"), expected.encode("utf-8")):
        _audit_denial(op, request)
        raise HTTPException(status_code=401, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"})
