"""Minimal semver + range parsing for pack.yaml `requires_core`
(docs/ARCHITECTURE.md §3). No external dependency — we only need to parse
plain X.Y.Z versions and comma-separated two-sided ranges like
">=0.4.0,<0.5.0", matching the exact syntax used in pack.yaml examples
throughout ARCHITECTURE.md and the pack-loader-foundation spec.
"""
from __future__ import annotations

import re

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_CLAUSE_RE = re.compile(r"^(>=|<=|>|<|==)(.+)$")


class InvalidVersionError(ValueError):
    """Raised for a malformed version string or requires_core clause."""


def parse_version(v: str) -> tuple[int, int, int]:
    match = _VERSION_RE.match(v.strip())
    if not match:
        raise InvalidVersionError(f"{v!r} is not a valid X.Y.Z version")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _compare(a: tuple[int, int, int], op: str, b: tuple[int, int, int]) -> bool:
    if op == ">=":
        return a >= b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    if op == "<":
        return a < b
    if op == "==":
        return a == b
    raise InvalidVersionError(f"unsupported operator {op!r}")  # unreachable: _CLAUSE_RE constrains op


def satisfies(version: str, requires_range: str) -> bool:
    """e.g. satisfies("0.4.2", ">=0.4.0,<0.5.0") -> True"""
    target = parse_version(version)
    for raw_clause in requires_range.split(","):
        clause = raw_clause.strip()
        match = _CLAUSE_RE.match(clause)
        if not match:
            raise InvalidVersionError(f"{clause!r} in requires_core range is not a valid clause")
        op, bound = match.group(1), match.group(2)
        if not _compare(target, op, parse_version(bound)):
            return False
    return True
