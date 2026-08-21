# core/diagnostics/models.py
from typing import Literal

from pydantic import BaseModel

Status = Literal["PASS", "WARN", "FAIL"]


class CheckResult(BaseModel):
    name: str
    status: Status
    message: str
