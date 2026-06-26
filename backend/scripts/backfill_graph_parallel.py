"""Parallel, resumable knowledge-graph backfill.

Ingests every lifelog not yet in the graph (graph_ingested=False, >=5
utterances) into Graphiti/Neo4j with bounded concurrency. Resumable: the
graph_ingested flag is the checkpoint, so re-running continues where it left
off. A single shared GraphService (one Neo4j driver + one local embedder +
one reranker) is reused across workers; only the LLM extraction calls and DB
reads fan out.

Usage:
    DATABASE_URL=postgresql://...  GRAPH_CONCURRENCY=5 \
    python -m scripts.backfill_graph_parallel [--limit N]

Tune GRAPH_CONCURRENCY for throughput vs. provider rate limits.
"""

import argparse
import asyncio
import logging
import os
import time

from sqlalchemy import func, select

from app.db.models import Lifelog, Utterance
from app.db.session import db_session

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backfill")
log.setLevel(logging.INFO)

CONCURRENCY = int(os.environ.get("GRAPH_CONCURRENCY", "5"))
MAX_CHARS = int(os.environ.get("GRAPH_MAX_CHARS", "24000"))


def pending_ids(limit: int | None) -> list[str]:
    with db_session() as s:
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
        return [r[0] for r in s.execute(stmt).all()]


def build_transcript(lifelog_id: str):
    with db_session() as s:
        ll = s.get(Lifelog, lifelog_id)
        if ll is None:
            return None, None, None
        text = "\n".join(
            f"{u.speaker_name or ('You' if u.speaker_identifier == 'user' else 'Unknown')}: {u.text}"
            for u in ll.utterances
            if u.node_type not in ("heading1", "heading2", "heading3")
        )
        return text, ll.title, ll.start_time


def mark_done(lifelog_id: str) -> None:
    with db_session() as s:
        ll = s.get(Lifelog, lifelog_id)
        if ll:
            ll.graph_ingested = True


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    from app.graph.graphiti_service import GraphService

    ids = pending_ids(args.limit)
    total = len(ids)
    log.info("Pending lifelogs to ingest: %d (concurrency=%d)", total, CONCURRENCY)
    if not total:
        return

    svc = GraphService()
    await svc.initialize()

    sem = asyncio.Semaphore(CONCURRENCY)
    state = {"done": 0, "failed": 0, "t0": time.time()}

    async def worker(lifelog_id: str) -> None:
        async with sem:
            transcript, title, start = await asyncio.to_thread(build_transcript, lifelog_id)
            if not transcript or not transcript.strip():
                await asyncio.to_thread(mark_done, lifelog_id)  # nothing to extract
                return
            try:
                await svc.add_lifelog_episode(lifelog_id, title, transcript[:MAX_CHARS], start)
                await asyncio.to_thread(mark_done, lifelog_id)
                state["done"] += 1
            except Exception as exc:
                state["failed"] += 1
                log.warning("FAILED %s: %s", lifelog_id, str(exc)[:120])
            n = state["done"] + state["failed"]
            if n % 10 == 0 or n == total:
                elapsed = time.time() - state["t0"]
                rate = n / elapsed * 60 if elapsed else 0
                remaining = (total - n) / (n / elapsed) if n and elapsed else 0
                log.info(
                    "progress %d/%d (ok=%d fail=%d) | %.1f eps/min | ETA %.1f h",
                    n, total, state["done"], state["failed"], rate, remaining / 3600,
                )

    try:
        await asyncio.gather(*(worker(i) for i in ids))
    finally:
        await svc.close()
    elapsed = time.time() - state["t0"]
    log.info(
        "DONE: %d ingested, %d failed in %.1f min", state["done"], state["failed"], elapsed / 60
    )


if __name__ == "__main__":
    asyncio.run(main())
