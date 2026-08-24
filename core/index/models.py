# core/index/models.py
from typing import Literal

from pydantic import BaseModel


class CodeLocation(BaseModel):
    file: str
    line: int
    symbol: str
    kind: Literal["function", "class", "method"]
