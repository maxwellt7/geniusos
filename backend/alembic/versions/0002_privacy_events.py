"""privacy events audit table

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-12

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "privacy_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("subject_person", sa.String(256), nullable=True),
        sa.Column("action", sa.String(32), nullable=False, server_default="blocked"),
    )


def downgrade() -> None:
    op.drop_table("privacy_events")
