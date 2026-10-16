"""acceptance checks record their expected and observed baseline (red before green)

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("acceptance_check", sa.Column("expect_baseline", sa.String(8), nullable=False, server_default="fail"))
    op.add_column("acceptance_check", sa.Column("baseline", sa.String(12), nullable=False, server_default="unverified"))


def downgrade() -> None:
    with op.batch_alter_table("acceptance_check") as batch:
        batch.drop_column("baseline")
        batch.drop_column("expect_baseline")
