# core/policy/engine.py
"""check_policy — docs/ARCHITECTURE.md §2. Evaluate-and-return policy
engine over glob-pattern rules loaded from policies/ (repo-level) plus any
pack-contributed rules (packs are Phase 8, not wired here). First matching
rule wins; no match falls through to policy.default_effect (deny by
default, per CLAUDE.md's security posture).
"""
from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

import yaml

from core.config.resolve import resolve_config_auto
from core.policy.models import PolicyDecision, PolicyRule


def _policies_dir(config: dict[str, Any]) -> Path:
    rel = config.get("paths", {}).get("policies_dir", "policies")
    return Path(rel)


def load_policy(config: dict[str, Any] | None = None) -> list[PolicyRule]:
    config = config if config is not None else resolve_config_auto()
    directory = _policies_dir(config)
    if not directory.exists():
        return []

    rules: list[PolicyRule] = []
    for path in sorted(directory.glob("*.yaml")):
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for raw_rule in data.get("rules", []):
            rules.append(PolicyRule(**raw_rule))
    return rules


def check_policy(action: str, config: dict[str, Any] | None = None) -> PolicyDecision:
    config = config if config is not None else resolve_config_auto()
    rules = load_policy(config)

    for rule in rules:
        if fnmatch.fnmatch(action, rule.action):
            allowed = rule.effect == "allow"
            return PolicyDecision(
                allowed=allowed,
                reason=f"matched rule '{rule.action}' -> {rule.effect}",
                matched_rule=rule.action,
            )

    default_effect = config.get("policy", {}).get("default_effect", "deny")
    allowed = default_effect == "allow"
    return PolicyDecision(
        allowed=allowed,
        reason=f"no matching rule, default_effect={default_effect}",
        matched_rule=None,
    )
