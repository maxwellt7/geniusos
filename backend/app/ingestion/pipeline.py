"""Sync pipeline: Limitless API -> Postgres -> Pinecone -> (optionally) Neo4j.

Idempotent: lifelogs are upserted by ID, chunks/utterances are replaced per
lifelog, Pinecone records use deterministic IDs, and a watermark on lifelog
`updatedAt` lets incremental syncs resume where the last one stopped.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Chunk, Lifelog, SyncState, Utterance, utcnow
from app.db.session import db_session
from app.ingestion.chunker import chunk_utterances
from app.ingestion.limitless_client import LimitlessClient
from app.ingestion.parser import flatten_content_nodes, parse_iso
from app.vector.pinecone_store import PineconeStore

logger = logging.getLogger(__name__)

# Re-fetch a small window before the watermark to catch late edits.
WATERMARK_OVERLAP = timedelta(hours=1)


def _total_lifelogs(session: Session) -> int:
    return session.execute(select(func.count()).select_from(Lifelog)).scalar() or 0


def get_or_create_sync_state(session: Session) -> SyncState:
    state = session.get(SyncState, 1)
    if state is None:
        state = SyncState(id=1)
        session.add(state)
        session.flush()
    return state


def _store_lifelog(session: Session, raw: dict, store: PineconeStore | None) -> None:
    lifelog_id = raw["id"]
    utterances = flatten_content_nodes(raw.get("contents"))
    chunks = chunk_utterances(utterances)

    lifelog = session.get(Lifelog, lifelog_id)
    if lifelog is None:
        lifelog = Lifelog(id=lifelog_id)
        session.add(lifelog)
    else:
        # Replace children on re-ingest (lifelog was updated upstream).
        lifelog.utterances.clear()
        lifelog.chunks.clear()
        lifelog.graph_ingested = False
        session.flush()

    lifelog.title = raw.get("title")
    lifelog.markdown = raw.get("markdown")
    lifelog.start_time = parse_iso(raw.get("startTime"))
    lifelog.end_time = parse_iso(raw.get("endTime"))
    lifelog.is_starred = bool(raw.get("isStarred"))
    lifelog.updated_at = parse_iso(raw.get("updatedAt")) or lifelog.start_time
    lifelog.raw_json = raw
    lifelog.ingested_at = utcnow()

    for u in utterances:
        session.add(
            Utterance(
                lifelog_id=lifelog_id,
                sequence=u.sequence,
                node_type=u.node_type,
                speaker_name=u.speaker_name,
                speaker_identifier=u.speaker_identifier,
                text=u.text,
                start_time=u.start_time,
                end_time=u.end_time,
                start_offset_ms=u.start_offset_ms,
                end_offset_ms=u.end_offset_ms,
            )
        )

    records = []
    for idx, draft in enumerate(chunks):
        pinecone_id = f"{lifelog_id}#{idx}"
        chunk_start = draft.start_time or lifelog.start_time
        chunk_end = draft.end_time or lifelog.end_time
        session.add(
            Chunk(
                lifelog_id=lifelog_id,
                chunk_index=idx,
                text=draft.render(),
                speakers=draft.speakers,
                start_time=chunk_start,
                end_time=chunk_end,
                first_sequence=draft.first_sequence,
                last_sequence=draft.last_sequence,
                pinecone_id=pinecone_id,
                embedded_at=utcnow() if store else None,
            )
        )
        record = {
            "_id": pinecone_id,
            "chunk_text": draft.render(),
            "lifelog_id": lifelog_id,
            "lifelog_title": lifelog.title or "Untitled",
            "chunk_index": idx,
            "speakers": draft.speakers,
        }
        if chunk_start:
            record["start_time"] = chunk_start.isoformat()
            record["start_ts"] = chunk_start.timestamp()
        if chunk_end:
            record["end_time"] = chunk_end.isoformat()
        records.append(record)

    if records and store:
        store.upsert_chunks(records)


def run_sync(full: bool = False) -> dict:
    """Run an incremental (or full) sync. Returns a summary dict."""
    settings = get_settings()
    client = LimitlessClient()
    if settings.pinecone_api_key:
        store = PineconeStore()
    else:
        store = None
        logger.warning("PINECONE_API_KEY not set; skipping vector upserts (backfill later)")
    synced = 0

    with db_session() as session:
        state = get_or_create_sync_state(session)
        state.last_sync_started = utcnow()
        state.last_sync_status = "running"
        state.last_sync_error = None
        watermark = None if full else state.last_updated_at

    start_param = None
    if watermark:
        start_param = (watermark - WATERMARK_OVERLAP).strftime("%Y-%m-%d %H:%M:%S")

    max_updated: datetime | None = watermark
    try:
        for raw in client.iter_lifelogs(start=start_param, direction="asc"):
            with db_session() as session:
                _store_lifelog(session, raw, store)
            synced += 1
            updated = parse_iso(raw.get("updatedAt")) or parse_iso(raw.get("endTime"))
            if updated and (max_updated is None or updated > max_updated):
                max_updated = updated
            if synced % 25 == 0:
                logger.info("Synced %d lifelogs so far...", synced)
                with db_session() as session:
                    state = get_or_create_sync_state(session)
                    # Total in the DB, not this run's count: incremental runs
                    # would otherwise shrink the sidebar's "Synced N lifelogs".
                    state.lifelogs_synced = _total_lifelogs(session)
                    state.last_updated_at = max_updated

        with db_session() as session:
            state = get_or_create_sync_state(session)
            state.last_updated_at = max_updated
            state.last_sync_finished = utcnow()
            state.last_sync_status = "success"
            state.lifelogs_synced = _total_lifelogs(session)
    except Exception as exc:
        logger.exception("Sync failed")
        with db_session() as session:
            state = get_or_create_sync_state(session)
            state.last_sync_finished = utcnow()
            state.last_sync_status = "error"
            state.last_sync_error = str(exc)[:2000]
        raise
    finally:
        client.close()

    result = {"lifelogs_synced": synced, "watermark": max_updated.isoformat() if max_updated else None}

    if settings.enable_graph_ingestion:
        graph_result = asyncio.run(ingest_graph_pending())
        result["graph_episodes_added"] = graph_result["episodes_added"]

    return result


async def ingest_graph_pending(limit: int | None = None) -> dict:
    """Ingest lifelogs that haven't been added to the knowledge graph yet."""
    from app.graph.graphiti_service import GraphService

    service = GraphService()
    await service.initialize()
    added = 0
    failed = 0
    try:
        with db_session() as session:
            # Most recent first: recent memories are queried most; substantial
            # conversations (several utterances) before fragments.
            from sqlalchemy import func

            from app.db.models import Utterance

            stmt = (
                select(Lifelog.id)
                .join(Utterance, Utterance.lifelog_id == Lifelog.id)
                .where(Lifelog.graph_ingested.is_(False))
                .group_by(Lifelog.id)
                .having(func.count(Utterance.id) >= 5)
                .order_by(Lifelog.start_time.desc())
            )
            if limit:
                stmt = stmt.limit(limit)
            pending_ids = [row[0] for row in session.execute(stmt).all()]

        for lifelog_id in pending_ids:
            with db_session() as session:
                lifelog = session.get(Lifelog, lifelog_id)
                if lifelog is None:
                    continue
                transcript = "\n".join(
                    f"{u.speaker_name or ('You' if u.speaker_identifier == 'user' else 'Unknown')}: {u.text}"
                    for u in lifelog.utterances
                    if u.node_type not in ("heading1", "heading2", "heading3")
                )
                title = lifelog.title
                start_time = lifelog.start_time
            if not transcript.strip():
                with db_session() as session:
                    session.get(Lifelog, lifelog_id).graph_ingested = True
                continue
            # Keep episode bodies within a sane LLM context budget.
            if len(transcript) > 24000:
                transcript = transcript[:24000]

            try:
                await service.add_lifelog_episode(lifelog_id, title, transcript, start_time)
            except Exception:
                logger.exception("Graph ingestion failed for lifelog %s; skipping", lifelog_id)
                failed += 1
                continue
            with db_session() as session:
                session.get(Lifelog, lifelog_id).graph_ingested = True
            added += 1
            if added % 10 == 0:
                logger.info("Graph ingestion progress: %d episodes added", added)
    finally:
        await service.close()

    return {"episodes_added": added, "failed": failed}
