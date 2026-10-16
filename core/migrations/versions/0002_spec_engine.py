"""spec engine tables

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "spec",
        sa.Column("spec_id", sa.String(64), primary_key=True),
        sa.Column("request", sa.Text, nullable=False),
        sa.Column("complexity", sa.String(16), nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
    )
    op.create_table(
        "spec_requirement",
        sa.Column("pk", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("spec_id", sa.String(64), sa.ForeignKey("spec.spec_id"), nullable=False),
        sa.Column("req_id", sa.String(32), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.UniqueConstraint("spec_id", "req_id"),
    )
    op.create_table(
        "plan",
        sa.Column("spec_id", sa.String(64), sa.ForeignKey("spec.spec_id"), primary_key=True),
        sa.Column("approach", sa.Text, nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("requirements_sha256", sa.String(64), nullable=False, server_default=""),
    )
    op.create_table(
        "spec_stage",
        sa.Column("spec_id", sa.String(64), sa.ForeignKey("spec.spec_id"), primary_key=True),
        sa.Column("stage", sa.String(16), nullable=False),
    )
    op.create_table(
        "task",
        sa.Column("pk", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("spec_id", sa.String(64), sa.ForeignKey("spec.spec_id"), nullable=False),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("requirement_ids", sa.JSON, nullable=False),
        sa.Column("depends_on", sa.JSON, nullable=False),
        sa.Column("expected_symbols", sa.JSON, nullable=False),
        sa.Column("interactive", sa.Boolean, nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.UniqueConstraint("spec_id", "task_id"),
    )
    op.create_table(
        "acceptance_check",
        sa.Column("pk", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("spec_id", sa.String(64), sa.ForeignKey("spec.spec_id"), nullable=False),
        sa.Column("requirement_id", sa.String(32), nullable=False),
        sa.Column("command", sa.Text, nullable=False),
        sa.Column("files", sa.JSON, nullable=False),
        sa.Column("file_hashes", sa.JSON, nullable=False),
        sa.Column("frozen_at", sa.Float, nullable=False),
        sa.UniqueConstraint("spec_id", "requirement_id"),
    )


def downgrade() -> None:
    for table in ("acceptance_check", "task", "spec_stage", "plan", "spec_requirement", "spec"):
        op.drop_table(table)
