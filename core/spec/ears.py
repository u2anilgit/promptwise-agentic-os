# core/spec/ears.py
"""Structural EARS (Easy Approach to Requirements Syntax) validator — a
linter, not a generator or semantic scorer. Core has no LLM client; this
checks a caller-authored requirement against the five canonical EARS
shapes via regex and reports violations as warnings.
"""
from __future__ import annotations

import re

from core.spec.models import EarsViolation, Requirement

_SHAPES: dict[str, re.Pattern[str]] = {
    "Ubiquitous": re.compile(r"^The \S.* shall .+", re.IGNORECASE),
    "Event-driven": re.compile(r"^When .+, the \S.* shall .+", re.IGNORECASE),
    "State-driven": re.compile(r"^While .+, the \S.* shall .+", re.IGNORECASE),
    "Unwanted behavior": re.compile(r"^If .+, then the \S.* shall .+", re.IGNORECASE),
    "Optional feature": re.compile(r"^Where .+, the \S.* shall .+", re.IGNORECASE),
}


def validate_ears(requirements: list[Requirement]) -> list[EarsViolation]:
    violations: list[EarsViolation] = []
    for requirement in requirements:
        if not any(pattern.match(requirement.text) for pattern in _SHAPES.values()):
            violations.append(
                EarsViolation(
                    requirement_id=requirement.id,
                    shape_expected="one of: " + ", ".join(_SHAPES),
                    reason="does not match any EARS sentence shape",
                )
            )
    return violations
