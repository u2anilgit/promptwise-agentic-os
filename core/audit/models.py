# core/audit/models.py
from typing import Any, Literal

from pydantic import BaseModel

AuditResult = Literal["allow", "deny", "error"]


class AuditRecord(BaseModel):
    id: str
    timestamp: str
    actor: str
    action: str
    target: str
    result: AuditResult
    detail: dict[str, Any] = {}
    prev_hash: str
    hash: str
