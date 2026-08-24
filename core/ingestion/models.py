# core/ingestion/models.py
from pydantic import BaseModel


class IngestionResult(BaseModel):
    root: str
    code_index_refreshed: bool = False
    facts_recorded: int = 0
    facts_failed: int = 0
    errors: list[str] = []
