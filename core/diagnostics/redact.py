"""Shared redaction utility — docs/MAINTENANCE.md §3: "one implementation,
not two." Used by the support bundle (this phase) and, later, any
dashboard log-viewing panel (Phase 6). Pattern-based, not exhaustive —
covers the common secret shapes (API keys, bearer tokens, password
assignments); redacted before write, never after, per the same section.
"""
from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9\-_.]{20,}"),
    re.compile(r'(?i)(password|passwd|secret|api[_-]?key)\s*[:=]\s*["\']?[^\s"\']{6,}["\']?'),
]


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern in _PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted
