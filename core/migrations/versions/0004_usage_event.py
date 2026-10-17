"""usage ledger: agent-reported token usage with cost fixed at record time

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_event",
        sa.Column("pk", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.Float, nullable=False),
        sa.Column("tier", sa.String(64), nullable=False),
        sa.Column("tokens_in", sa.Integer, nullable=False),
        sa.Column("tokens_out", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.Float, nullable=False),
        sa.Column("agent", sa.String(200), nullable=False),
        sa.Column("task_ref", sa.String(200), nullable=True),
        sa.Column("spec_id", sa.String(200), nullable=True),
    )
    op.create_index("ix_usage_event_ts", "usage_event", ["ts"])


def downgrade() -> None:
    op.drop_index("ix_usage_event_ts", table_name="usage_event")
    op.drop_table("usage_event")
