"""add MRA report contract and ME audit table

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("questions", sa.Column("report_type", sa.String(32), nullable=True))
    op.add_column("questions", sa.Column("research_params_json", sa.Text(), nullable=True))
    op.add_column("reports", sa.Column("report_type", sa.String(32), nullable=True))
    op.add_column("reports", sa.Column("research_params_json", sa.Text(), nullable=True))
    op.add_column("reports", sa.Column("me_data_stats_json", sa.Text(), nullable=True))
    op.add_column("reports", sa.Column("coverage_json", sa.Text(), nullable=True))
    op.add_column("reports", sa.Column("qc_warnings_json", sa.Text(), nullable=True))
    op.add_column("reports", sa.Column("eval_scores_json", sa.Text(), nullable=True))
    op.create_table(
        "mra_me_query_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("research_tasks.id"), nullable=True),
        sa.Column("report_type", sa.String(32), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("result_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("mra_me_query_logs")
    for column in ("eval_scores_json", "qc_warnings_json", "coverage_json", "me_data_stats_json", "research_params_json", "report_type"):
        op.drop_column("reports", column)
    op.drop_column("questions", "research_params_json")
    op.drop_column("questions", "report_type")
