# core/memory/models.py
from typing import Literal

from pydantic import BaseModel


class Fact(BaseModel):
    id: int | None = None
    text: str
    category: str
    scope: Literal["session", "project"]
    root: str | None = None
    session_id: str | None = None
    pii: bool = False
    created_at: float
