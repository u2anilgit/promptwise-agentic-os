# core/spec/models.py
"""Typed contract for the spec engine (docs/superpowers/specs/2026-10-16-spec-engine-v2-design.md).
Pure data — no I/O, no domain knowledge."""
from __future__ import annotations

from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict

Stage = Literal["specified", "planned", "tasked", "implementing", "verified"]
TaskStatus = Literal["pending", "done", "error"]
Complexity = Literal["trivial", "standard"]


class Requirement(BaseModel):
    id: str
    text: str


class AcceptanceCheck(BaseModel):
    requirement_id: str
    command: str
    files: list[str] = []


class FrozenCheck(AcceptanceCheck):
    file_hashes: dict[str, str] = {}


class TaskNode(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    id: str
    depends_on: list[str] = []
    requirement_ids: list[str] = []
    expected_symbols: list[str] = []
    run: Callable[[dict[str, Any]], Any] | None = None
    task_type: str = "general"


class SpecArtifact(BaseModel):
    spec_id: str
    request: str
    complexity: Complexity
    requirements: list[Requirement]
    created_at: float


class PlanArtifact(BaseModel):
    spec_id: str
    approach: str
    created_at: float
    requirements_sha256: str = ""


class EarsViolation(BaseModel):
    requirement_id: str
    shape_expected: str
    reason: str


class ConvergeReport(BaseModel):
    spec_id: str
    planned_tasks: int
    done_tasks: int
    pending_tasks: int
    stale: bool
    reasons: list[str]
