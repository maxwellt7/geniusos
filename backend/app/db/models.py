from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Lifelog(Base):
    __tablename__ = "lifelogs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    graph_ingested: Mapped[bool] = mapped_column(Boolean, default=False)

    utterances: Mapped[list["Utterance"]] = relationship(
        back_populates="lifelog", cascade="all, delete-orphan", order_by="Utterance.sequence"
    )
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="lifelog", cascade="all, delete-orphan", order_by="Chunk.chunk_index"
    )


class Utterance(Base):
    __tablename__ = "utterances"
    __table_args__ = (UniqueConstraint("lifelog_id", "sequence", name="uq_utterance_seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lifelog_id: Mapped[str] = mapped_column(
        ForeignKey("lifelogs.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    node_type: Mapped[str | None] = mapped_column(String(32))
    speaker_name: Mapped[str | None] = mapped_column(String(256), index=True)
    speaker_identifier: Mapped[str | None] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Limitless sometimes emits absolute epoch-ms offsets (~1.7e12), which
    # overflow a 32-bit Postgres INTEGER. SQLite's dynamic ints hid this.
    start_offset_ms: Mapped[int | None] = mapped_column(BigInteger)
    end_offset_ms: Mapped[int | None] = mapped_column(BigInteger)

    lifelog: Mapped[Lifelog] = relationship(back_populates="utterances")


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (UniqueConstraint("lifelog_id", "chunk_index", name="uq_chunk_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lifelog_id: Mapped[str] = mapped_column(
        ForeignKey("lifelogs.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    speakers: Mapped[list] = mapped_column(JSON, default=list)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_sequence: Mapped[int | None] = mapped_column(Integer)
    last_sequence: Mapped[int | None] = mapped_column(Integer)
    pinecone_id: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lifelog: Mapped[Lifelog] = relationship(back_populates="chunks")


class PrivacyEvent(Base):
    """Audit log of privacy-sensitive queries attempted in guest mode."""

    __tablename__ = "privacy_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    question: Mapped[str] = mapped_column(Text)
    subject_person: Mapped[str | None] = mapped_column(String(256))
    action: Mapped[str] = mapped_column(String(32), default="blocked")


class SyncState(Base):
    """Single-row table tracking the ingestion watermark."""

    __tablename__ = "sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    # Latest lifelog updatedAt we have fully processed.
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_started: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_finished: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(String(32))
    last_sync_error: Mapped[str | None] = mapped_column(Text)
    lifelogs_synced: Mapped[int] = mapped_column(Integer, default=0)
