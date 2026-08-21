# core/policy/models.py
from typing import Literal

from pydantic import BaseModel


class PolicyRule(BaseModel):
    action: str
    effect: Literal["allow", "deny"]


class PolicyDecision(BaseModel):
    allowed: bool
    reason: str
    matched_rule: str | None = None
