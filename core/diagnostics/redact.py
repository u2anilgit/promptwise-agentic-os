"""Shared redaction utility — docs/MAINTENANCE.md §3: "one implementation,
not two." Used by the support bundle (redact_secrets) and the memory
layer's PII flagging (contains_pii, docs/superpowers/specs/2026-08-24-memory-fact-layer-design.md).
Pattern-based, not exhaustive — covers common secret shapes (API keys,
bearer tokens, password assignments) and common PII shapes (email,
phone); redacted before write, never after, per the same section.
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


_PII_PATTERNS = [
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),          # email
    re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),  # US-style phone
]


def contains_pii(text: str) -> bool:
    """Detection only — never mutates the input. A flagged fact still
    stores its full text locally; the flag only gates cloud-bound
    context assembly (docs/superpowers/specs/2026-08-24-memory-fact-layer-design.md,
    Decision 4)."""
    for pattern in _PATTERNS + _PII_PATTERNS:
        if pattern.search(text):
            return True
    return False
