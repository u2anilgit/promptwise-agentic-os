# core/routing/tables.py — durable usage ledger. Portable types only.
from __future__ import annotations

from sqlalchemy import Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class UsageRow(Base):
    __tablename__ = "usage_event"
    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[float] = mapped_column(Float)
    tier: Mapped[str] = mapped_column(String(64))
    tokens_in: Mapped[int] = mapped_column(Integer)
    tokens_out: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[float] = mapped_column(Float)  # fixed at record time from the catalog tier
    agent: Mapped[str] = mapped_column(String(200))
    task_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    spec_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    __table_args__ = (Index("ix_usage_event_ts", "ts"),)
