"""widen utterance offsets to BigInteger

Limitless sometimes emits absolute epoch-millisecond offsets (~1.7e12) that
overflow a 32-bit Postgres INTEGER. SQLite stored them fine (dynamic ints),
so this only surfaces on Postgres.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-12

"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("utterances", "start_offset_ms", type_=sa.BigInteger(), existing_nullable=True)
    op.alter_column("utterances", "end_offset_ms", type_=sa.BigInteger(), existing_nullable=True)


def downgrade() -> None:
    op.alter_column("utterances", "start_offset_ms", type_=sa.Integer(), existing_nullable=True)
    op.alter_column("utterances", "end_offset_ms", type_=sa.Integer(), existing_nullable=True)
