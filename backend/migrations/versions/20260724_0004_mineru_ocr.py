"""Store MinerU OCR evidence for handwritten attempts.

Revision ID: 20260724_0004
Revises: 20260718_0003
"""

from alembic import op
import sqlalchemy as sa


revision = "20260724_0004"
down_revision = "20260718_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("question_attempts") as batch_op:
        batch_op.add_column(sa.Column("ocr_text", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("ocr_provider", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("ocr_status", sa.String(24), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("question_attempts") as batch_op:
        batch_op.drop_column("ocr_status")
        batch_op.drop_column("ocr_provider")
        batch_op.drop_column("ocr_text")
