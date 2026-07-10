"""Convert all timestamp columns to TIMESTAMPTZ

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_TZ = sa.DateTime(timezone=True)
_NO_TZ = sa.DateTime(timezone=False)

_cols = [
    ("users", "created_at"),
    ("questions", "created_at"),
    ("research_tasks", "started_at"),
    ("research_tasks", "finished_at"),
    ("gate_results", "ran_at"),
    ("reports", "created_at"),
    ("report_chat_messages", "created_at"),
    ("pending_documents", "reviewed_at"),
    ("pending_documents", "created_at"),
]


def upgrade() -> None:
    for table, col in _cols:
        op.alter_column(table, col, type_=_TZ, postgresql_using=f"{col} AT TIME ZONE 'UTC'")


def downgrade() -> None:
    for table, col in _cols:
        op.alter_column(table, col, type_=_NO_TZ)
