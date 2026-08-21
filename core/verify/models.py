from typing import Literal

from pydantic import BaseModel

Severity = Literal["error", "warning", "info"]


class VerifyFinding(BaseModel):
    tool: str
    severity: Severity
    message: str
    file: str | None = None
    line: int | None = None


class ToolRunResult(BaseModel):
    tool: str
    ran: bool
    passed: bool
    output: str
    findings: list[VerifyFinding] = []


class VerifyResult(BaseModel):
    passed: bool
    results: list[ToolRunResult]
    blocked_reason: str | None = None
    retry_loop_broken: bool = False
