"""Create the initial application schema.

Revision ID: 20260711_0001
Revises:
"""

from alembic import op
import sqlalchemy as sa


revision = "20260711_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.String(256), nullable=True),
        sa.Column("role", sa.String(16), nullable=False, server_default="student"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("mode", sa.String(24), nullable=False, server_default="answer"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources_json", sa.Text(), nullable=True),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])
    op.create_table(
        "teaching_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("topic", sa.String(160), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=False, server_default="45"),
        sa.Column("objectives", sa.Text(), nullable=True),
        sa.Column("question_ids_json", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_teaching_plans_user_id", "teaching_plans", ["user_id"])
    op.create_table(
        "question_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", sa.String(16), nullable=False),
        sa.Column("input_mode", sa.String(24), nullable=False, server_default="formula"),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("image_name", sa.String(255), nullable=True),
        sa.Column("image_data_url", sa.Text(), nullable=True),
        sa.Column("verdict", sa.String(24), nullable=False, server_default="needs_review"),
        sa.Column("feedback", sa.Text(), nullable=False),
        sa.Column("error_type", sa.String(64), nullable=True),
        sa.Column("hint_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_question_attempts_user_id", "question_attempts", ["user_id"])
    op.create_index("ix_question_attempts_question_id", "question_attempts", ["question_id"])
    op.create_table(
        "experiment_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("experiment_id", sa.String(64), nullable=False),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("result_summary", sa.Text(), nullable=False),
        sa.Column("observation", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_experiment_records_user_id", "experiment_records", ["user_id"])
    op.create_index("ix_experiment_records_experiment_id", "experiment_records", ["experiment_id"])


def downgrade() -> None:
    op.drop_table("experiment_records")
    op.drop_table("question_attempts")
    op.drop_table("teaching_plans")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("users")
