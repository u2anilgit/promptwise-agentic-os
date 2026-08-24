# core/actions/models.py
from pydantic import BaseModel


class FsWriteResult(BaseModel):
    path: str
    allowed: bool
    written: bool
    reason: str


class UndoEntry(BaseModel):
    path: str
    previous_content: str | None
    timestamp: str
