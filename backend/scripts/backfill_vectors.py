"""Backfill Pinecone with chunks that haven't been embedded yet
(e.g. synced while the Pinecone key was missing).

Usage:
    python -m scripts.backfill_vectors
"""

from sqlalchemy import select

from app.db.models import Chunk, Lifelog, utcnow
from app.db.session import db_session
from app.vector.pinecone_store import PineconeStore

BATCH = 200


def main() -> None:
    store = PineconeStore()
    total = 0
    while True:
        with db_session() as session:
            rows = session.execute(
                select(Chunk, Lifelog.title)
                .join(Lifelog, Chunk.lifelog_id == Lifelog.id)
                .where(Chunk.embedded_at.is_(None))
                .limit(BATCH)
            ).all()
            if not rows:
                break

            records = []
            for chunk, title in rows:
                record = {
                    "_id": chunk.pinecone_id,
                    "chunk_text": chunk.text,
                    "lifelog_id": chunk.lifelog_id,
                    "lifelog_title": title or "Untitled",
                    "chunk_index": chunk.chunk_index,
                    "speakers": chunk.speakers or [],
                }
                if chunk.start_time:
                    record["start_time"] = chunk.start_time.isoformat()
                    record["start_ts"] = chunk.start_time.timestamp()
                if chunk.end_time:
                    record["end_time"] = chunk.end_time.isoformat()
                records.append(record)

            store.upsert_chunks(records)
            now = utcnow()
            for chunk, _ in rows:
                chunk.embedded_at = now
            total += len(rows)
            print(f"Backfilled {total} chunks...")

    print(f"Done. {total} chunks embedded.")
    print(store.stats())


if __name__ == "__main__":
    main()
