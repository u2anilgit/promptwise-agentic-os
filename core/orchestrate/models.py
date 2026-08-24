# core/orchestrate/models.py
from __future__ import annotations

from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict


class DagNode(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    run: Callable[[dict[str, Any]], Any]
    depends_on: list[str] = []
    task_type: str = "general"
    privacy_sensitive: bool = False


class Dag(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    nodes: list[DagNode]


class NodeResult(BaseModel):
    status: Literal["done", "error", "skipped"]
    output: Any = None
    error: str | None = None


class DagResult(BaseModel):
    dag_name: str
    nodes: dict[str, NodeResult]
