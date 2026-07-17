"""Multi-layer retrieval: Pinecone (semantic), Postgres (temporal/exact),
and the Graphiti knowledge graph (relational)."""

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Lifelog
from app.retrieval.router import RoutedQuery
from app.vector.pinecone_store import PineconeStore

logger = logging.getLogger(__name__)


@dataclass
class RetrievedContext:
    chunks: list[dict[str, Any]] = field(default_factory=list)
    facts: list[dict[str, Any]] = field(default_factory=list)
    lifelogs: list[dict[str, Any]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.chunks or self.facts or self.lifelogs)


def _semantic_search(routed: RoutedQuery, top_k: int = 12) -> list[dict[str, Any]]:
    try:
        store = PineconeStore()
        return store.search(
            routed.search_query,
            top_k=top_k,
            start=routed.start_date,
            end=routed.end_date,
            speaker=routed.speaker,
        )
    except Exception:
        logger.exception("Semantic search failed; continuing without vector results")
        return []


def _as_naive_utc(dt):
    """DB rows hold naive UTC wall times (SQLite drops tzinfo); normalize
    aware datetimes so comparisons bind in the same format."""
    from datetime import timezone

    if dt is None or dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _temporal_search(session: Session, routed: RoutedQuery, limit: int = 40) -> list[dict[str, Any]]:
    from app.db.models import Utterance

    start = _as_naive_utc(routed.start_date)
    end = _as_naive_utc(routed.end_date)
    # Chronological for bounded ranges, most-recent-first otherwise.
    order = Lifelog.start_time.asc() if start else Lifelog.start_time.desc()
    stmt = select(Lifelog).order_by(order).limit(limit * 3)
    if start:
        stmt = stmt.where(Lifelog.start_time >= start)
    if end:
        stmt = stmt.where(Lifelog.start_time <= end)
    lifelogs = session.execute(stmt).scalars().all()
    if not lifelogs:
        return []

    # One aggregate query for speakers instead of loading every utterance.
    ids = [log.id for log in lifelogs]
    speaker_rows = session.execute(
        select(Utterance.lifelog_id, Utterance.speaker_name)
        .where(Utterance.lifelog_id.in_(ids), Utterance.speaker_name.is_not(None))
        .distinct()
    ).all()
    speakers_by_log: dict[str, set[str]] = {}
    for lifelog_id, name in speaker_rows:
        speakers_by_log.setdefault(lifelog_id, set()).add(name)

    results = []
    for log in lifelogs:
        speakers = speakers_by_log.get(log.id, set())
        if routed.speaker and not any(
            routed.speaker.lower() in s.lower() for s in speakers
        ):
            continue
        results.append(
            {
                "lifelog_id": log.id,
                "title": log.title,
                "start_time": log.start_time.isoformat() if log.start_time else None,
                "end_time": log.end_time.isoformat() if log.end_time else None,
                "speakers": sorted(speakers),
            }
        )
        if len(results) >= limit:
            break
    return results


_graph_service = None


def _get_graph_service():
    """Lazy singleton: GraphService loads local embedding/reranker models."""
    global _graph_service
    if _graph_service is None:
        from app.graph.graphiti_service import GraphService

        _graph_service = GraphService()
    return _graph_service


async def _graph_search(routed: RoutedQuery, num_results: int = 12) -> list[dict[str, Any]]:
    try:
        service = _get_graph_service()
        return await service.search(routed.search_query, num_results=num_results)
    except Exception:
        logger.exception("Graph search failed; continuing without graph facts")
        return []


async def retrieve(session: Session, routed: RoutedQuery) -> RetrievedContext:
    """Orchestrate retrieval across layers based on the routed intent."""
    ctx = RetrievedContext()

    # top_k values sized for depth: Claude's context comfortably fits the
    # extra excerpts, and richer context is what lets follow-ups like "tell
    # me more" surface new material instead of re-treading the same chunks.
    if routed.intent == "relational":
        ctx.facts = await _graph_search(routed, num_results=16)
        # Vector search supplements graph facts with verbatim transcript context.
        ctx.chunks = _semantic_search(routed, top_k=10)
    elif routed.intent == "temporal":
        ctx.lifelogs = _temporal_search(session, routed)
        if routed.search_query:
            ctx.chunks = _semantic_search(routed, top_k=10)
    else:  # semantic
        ctx.chunks = _semantic_search(routed, top_k=20)

    return ctx
