"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-12

"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lifelogs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_starred", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("graph_ingested", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_lifelogs_start_time", "lifelogs", ["start_time"])
    op.create_index("ix_lifelogs_end_time", "lifelogs", ["end_time"])
    op.create_index("ix_lifelogs_updated_at", "lifelogs", ["updated_at"])

    op.create_table(
        "utterances",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "lifelog_id",
            sa.String(),
            sa.ForeignKey("lifelogs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("node_type", sa.String(32), nullable=True),
        sa.Column("speaker_name", sa.String(256), nullable=True),
        sa.Column("speaker_identifier", sa.String(64), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_offset_ms", sa.Integer(), nullable=True),
        sa.Column("end_offset_ms", sa.Integer(), nullable=True),
        sa.UniqueConstraint("lifelog_id", "sequence", name="uq_utterance_seq"),
    )
    op.create_index("ix_utterances_lifelog_id", "utterances", ["lifelog_id"])
    op.create_index("ix_utterances_speaker_name", "utterances", ["speaker_name"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "lifelog_id",
            sa.String(),
            sa.ForeignKey("lifelogs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("speakers", sa.JSON(), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_sequence", sa.Integer(), nullable=True),
        sa.Column("last_sequence", sa.Integer(), nullable=True),
        sa.Column("pinecone_id", sa.String(128), nullable=True),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("lifelog_id", "chunk_index", name="uq_chunk_index"),
    )
    op.create_index("ix_chunks_lifelog_id", "chunks", ["lifelog_id"])
    op.create_index("ix_chunks_start_time", "chunks", ["start_time"])
    op.create_index("ix_chunks_pinecone_id", "chunks", ["pinecone_id"], unique=True)

    op.create_table(
        "sync_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_started", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_finished", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(32), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("lifelogs_synced", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("sync_state")
    op.drop_table("chunks")
    op.drop_table("utterances")
    op.drop_table("lifelogs")
