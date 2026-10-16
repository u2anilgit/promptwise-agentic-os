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
    # True iff a configured test command actually ran. A pass with grounded=False
    # is vacuous (nothing was tested) and must not be treated as proof of correctness.
    grounded: bool = False
    # True iff an operator-configured mutation command ran and passed (an independent check on test quality).
    mutation_passed: bool = False
