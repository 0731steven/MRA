"""Add structured, classroom-aware teaching packages.

Revision ID: 20260718_0003
Revises: 20260718_0002
"""

from alembic import op
import sqlalchemy as sa


revision = "20260718_0003"
down_revision = "20260718_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("teaching_plans") as batch_op:
        batch_op.add_column(sa.Column("classroom_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("lesson_type", sa.String(24), nullable=False, server_default="concept"))
        batch_op.add_column(sa.Column("learner_profile", sa.String(24), nullable=False, server_default="mixed"))
        batch_op.add_column(sa.Column("student_content", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("package_json", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            "fk_teaching_plans_classroom_id",
            "classrooms",
            ["classroom_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_teaching_plans_classroom_id", ["classroom_id"])


def downgrade() -> None:
    with op.batch_alter_table("teaching_plans") as batch_op:
        batch_op.drop_index("ix_teaching_plans_classroom_id")
        batch_op.drop_constraint("fk_teaching_plans_classroom_id", type_="foreignkey")
        batch_op.drop_column("package_json")
        batch_op.drop_column("student_content")
        batch_op.drop_column("learner_profile")
        batch_op.drop_column("lesson_type")
        batch_op.drop_column("classroom_id")
