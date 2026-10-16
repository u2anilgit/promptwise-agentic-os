# core/security/untrusted.py
"""Untrusted-content tagging — prompt-injection defence
(docs/research/2026-10-16-agent-landscape-gap-analysis.md pain point 2).

Text that arrives from outside the user's own instruction channel (issue
titles, web pages, MCP tool results, recalled memory, ingested session
text) is *data*. tag_untrusted wraps it in an unforgeable delimiter that
tells the consuming model so, and scan_for_injection reports well-known
injection/exfiltration shapes. Heuristics are advisory signals for audit
and review, never a sandbox: the wrapper is the control, the flags are
telemetry. Domain-agnostic — no language/stack knowledge lives here.
"""
from __future__ import annotations

import re

from pydantic import BaseModel

_PATTERNS: dict[str, re.Pattern[str]] = {
    "instruction_override": re.compile(
        r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|the)\b[^.\n]{0,20}\b(instructions?|prompts?|rules|directives)\b"
        r"|\byou are now\b|\bnew instructions?\s*:",
        re.IGNORECASE,
    ),
    "exfiltration": re.compile(
        r"\b(send|upload|post|email|exfiltrate|curl|transmit)\b[^\n]{0,80}(\.ssh|api[_ -]?keys?|secrets?|tokens?|passwords?|credentials?|\.env\b|id_rsa)",
        re.IGNORECASE,
    ),
    "markup_spoof": re.compile(r"</?\s*(system|assistant|tool|function_calls?|instructions?)\s*>", re.IGNORECASE),
    "hidden_characters": re.compile("[​-‏‪-‮⁠-⁤﻿\U000e0000-\U000e007f]"),
}

_LABEL_UNSAFE = re.compile(r"[^A-Za-z0-9_.:-]")
_TAG_BREAKOUT = re.compile(r"<\s*/?\s*untrusted\b", re.IGNORECASE)


class TaggedContent(BaseModel):
    source: str
    content: str
    wrapped: str
    risk_flags: list[str]

    @property
    def suspicious(self) -> bool:
        return bool(self.risk_flags)


def scan_for_injection(text: str) -> list[str]:
    return [name for name, pattern in _PATTERNS.items() if pattern.search(text)]


def tag_untrusted(text: str, source: str) -> TaggedContent:
    label = _LABEL_UNSAFE.sub("_", source) or "unknown"
    flags = scan_for_injection(text)
    # Defang any attempt to open/close our own delimiter from inside the data.
    safe = _TAG_BREAKOUT.sub(lambda m: m.group(0).replace("<", "&lt;"), text)
    wrapped = f'<untrusted source="{label}">\n{safe}\n</untrusted>'
    return TaggedContent(source=label, content=text, wrapped=wrapped, risk_flags=flags)
