# core/spec/tables.py — SQLAlchemy tables for spec artifacts. Portable types only.
from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class SpecRow(Base):
    __tablename__ = "spec"
    spec_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request: Mapped[str] = mapped_column(Text)
    complexity: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[float] = mapped_column(Float)


class RequirementRow(Base):
    __tablename__ = "spec_requirement"
    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spec_id: Mapped[str] = mapped_column(ForeignKey("spec.spec_id"))
    req_id: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("spec_id", "req_id"),)


class PlanRow(Base):
    __tablename__ = "plan"
    spec_id: Mapped[str] = mapped_column(ForeignKey("spec.spec_id"), primary_key=True)
    approach: Mapped[str] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float)
    requirements_sha256: Mapped[str] = mapped_column(String(64), default="")


class StageRow(Base):
    __tablename__ = "spec_stage"
    spec_id: Mapped[str] = mapped_column(ForeignKey("spec.spec_id"), primary_key=True)
    stage: Mapped[str] = mapped_column(String(16))


class TaskTable(Base):
    __tablename__ = "task"
    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spec_id: Mapped[str] = mapped_column(ForeignKey("spec.spec_id"))
    task_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    requirement_ids: Mapped[list] = mapped_column(JSON)
    depends_on: Mapped[list] = mapped_column(JSON)
    expected_symbols: Mapped[list] = mapped_column(JSON)
    interactive: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (UniqueConstraint("spec_id", "task_id"),)


class CheckRow(Base):
    __tablename__ = "acceptance_check"
    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spec_id: Mapped[str] = mapped_column(ForeignKey("spec.spec_id"))
    requirement_id: Mapped[str] = mapped_column(String(32))
    command: Mapped[str] = mapped_column(Text)
    files: Mapped[list] = mapped_column(JSON)
    file_hashes: Mapped[dict] = mapped_column(JSON)
    frozen_at: Mapped[float] = mapped_column(Float)
    # One frozen check per requirement: a command may run many tests and files[] lists them all.
    __table_args__ = (UniqueConstraint("spec_id", "requirement_id"),)
