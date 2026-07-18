"""Add classroom assignments and intervention loop.

Revision ID: 20260718_0002
Revises: 20260711_0001
"""

from alembic import op
import sqlalchemy as sa


revision = "20260718_0002"
down_revision = "20260711_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "classrooms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("course_name", sa.String(160), nullable=False, server_default="概率论与数理统计"),
        sa.Column("join_code", sa.String(12), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("join_code", name="classrooms_join_code_key"),
    )
    op.create_index("ix_classrooms_teacher_id", "classrooms", ["teacher_id"])
    op.create_index("ix_classrooms_join_code", "classrooms", ["join_code"], unique=True)
    op.create_table(
        "classroom_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("classroom_id", sa.Integer(), sa.ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("classroom_id", "student_id", name="uq_classroom_student"),
    )
    op.create_index("ix_classroom_memberships_classroom_id", "classroom_memberships", ["classroom_id"])
    op.create_index("ix_classroom_memberships_student_id", "classroom_memberships", ["student_id"])
    op.create_table(
        "learning_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("classroom_id", sa.Integer(), sa.ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_assignment_id", sa.Integer(), sa.ForeignKey("learning_assignments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(24), nullable=False, server_default="diagnostic"),
        sa.Column("topic", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="published"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_learning_assignments_classroom_id", "learning_assignments", ["classroom_id"])
    op.create_index("ix_learning_assignments_created_by", "learning_assignments", ["created_by"])
    op.create_index("ix_learning_assignments_source_assignment_id", "learning_assignments", ["source_assignment_id"])
    op.create_table(
        "assignment_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("learning_assignments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", sa.String(16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("assignment_id", "question_id", name="uq_assignment_question"),
    )
    op.create_index("ix_assignment_items_assignment_id", "assignment_items", ["assignment_id"])
    op.create_index("ix_assignment_items_question_id", "assignment_items", ["question_id"])
    op.create_table(
        "assignment_recipients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("learning_assignments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_label", sa.String(80), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="assigned"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("assignment_id", "student_id", name="uq_assignment_recipient"),
    )
    op.create_index("ix_assignment_recipients_assignment_id", "assignment_recipients", ["assignment_id"])
    op.create_index("ix_assignment_recipients_student_id", "assignment_recipients", ["student_id"])
    with op.batch_alter_table("question_attempts") as batch_op:
        batch_op.add_column(sa.Column("assignment_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_question_attempts_assignment_id",
            "learning_assignments",
            ["assignment_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_question_attempts_assignment_id", ["assignment_id"])


def downgrade() -> None:
    with op.batch_alter_table("question_attempts") as batch_op:
        batch_op.drop_index("ix_question_attempts_assignment_id")
        batch_op.drop_constraint("fk_question_attempts_assignment_id", type_="foreignkey")
        batch_op.drop_column("assignment_id")
    op.drop_table("assignment_recipients")
    op.drop_table("assignment_items")
    op.drop_table("learning_assignments")
    op.drop_table("classroom_memberships")
    op.drop_table("classrooms")
