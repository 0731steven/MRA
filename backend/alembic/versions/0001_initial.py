"""Initial tables — all 6 models.

Revision ID: 0001
Revises:
Create Date: 2026-05-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("feishu_user_id", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("avatar_url", sa.Text, nullable=True),
        sa.Column("role", sa.String(16), nullable=False, server_default="user"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_table(
        "questions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("tier", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("clarified_text", sa.Text, nullable=True),
        sa.Column("sub_questions_json", sa.Text, nullable=True),
        sa.Column("keywords_draft_json", sa.Text, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="created"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_table(
        "research_tasks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("question_id", sa.Integer, sa.ForeignKey("questions.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="step3_local_search"),
        sa.Column("current_step", sa.String(32), nullable=True),
        sa.Column("keywords_json", sa.Text, nullable=True),
        sa.Column("context_json", sa.Text, nullable=True),
        sa.Column("retry_counters_json", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("error_trace", sa.Text, nullable=True),
    )
    op.create_table(
        "gate_results",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("task_id", sa.Integer, sa.ForeignKey("research_tasks.id"), nullable=False),
        sa.Column("gate_name", sa.String(32), nullable=False),
        sa.Column("exit_code", sa.Integer, nullable=False),
        sa.Column("output", sa.Text, nullable=True),
        sa.Column("ran_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("task_id", sa.Integer, sa.ForeignKey("research_tasks.id"), nullable=False),
        sa.Column("vault_path", sa.Text, nullable=False),
        sa.Column("summary_text", sa.Text, nullable=True),
        sa.Column("citations_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_table(
        "pending_documents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("task_id", sa.Integer, sa.ForeignKey("research_tasks.id"), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("staging_path", sa.Text, nullable=False),
        sa.Column("target_path", sa.Text, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("reviewed_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("pending_documents")
    op.drop_table("reports")
    op.drop_table("gate_results")
    op.drop_table("research_tasks")
    op.drop_table("questions")
    op.drop_table("users")
