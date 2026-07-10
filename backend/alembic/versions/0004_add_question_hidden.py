"""add hidden flag to questions (soft delete)

Revision ID: 0004
down_revision = "0003"
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("questions", "hidden")
