"""Pinecone vector store using integrated embeddings.

The index is created with a hosted embedding model whose field map points at
`chunk_text`, so we upsert/search with raw text and Pinecone handles
vectorization server-side.
"""

import logging
from datetime import datetime
from typing import Any

from pinecone import Pinecone

from app.config import get_settings

logger = logging.getLogger(__name__)

UPSERT_BATCH_SIZE = 90

# Pinecone caps record metadata at ~40KB. The embedding model only reads the
# first ~2048 tokens anyway, so longer text adds nothing for retrieval.
MAX_CHUNK_TEXT_CHARS = 9000


class PineconeStore:
    def __init__(self):
        settings = get_settings()
        self._pc = Pinecone(api_key=settings.pinecone_api_key)
        self._index = self._pc.Index(settings.pinecone_index_name)
        self.namespace = settings.pinecone_namespace

    def upsert_chunks(self, records: list[dict[str, Any]]) -> None:
        """Each record needs `_id`, `chunk_text`, and metadata fields."""
        for record in records:
            text = record.get("chunk_text") or ""
            if len(text) > MAX_CHUNK_TEXT_CHARS:
                record["chunk_text"] = text[:MAX_CHUNK_TEXT_CHARS]
        for i in range(0, len(records), UPSERT_BATCH_SIZE):
            batch = records[i : i + UPSERT_BATCH_SIZE]
            self._index.upsert_records(records=batch, namespace=self.namespace)
        logger.info("Upserted %d records to Pinecone", len(records))

    def search(
        self,
        query: str,
        top_k: int = 10,
        start: datetime | None = None,
        end: datetime | None = None,
        speaker: str | None = None,
    ) -> list[dict[str, Any]]:
        filter_clauses: list[dict[str, Any]] = []
        if start:
            filter_clauses.append({"start_ts": {"$gte": start.timestamp()}})
        if end:
            filter_clauses.append({"start_ts": {"$lte": end.timestamp()}})
        if speaker:
            filter_clauses.append({"speakers": {"$in": [speaker]}})

        query_payload: dict[str, Any] = {"inputs": {"text": query}, "top_k": top_k}
        if len(filter_clauses) == 1:
            query_payload["filter"] = filter_clauses[0]
        elif filter_clauses:
            query_payload["filter"] = {"$and": filter_clauses}

        result = self._index.search(namespace=self.namespace, query=query_payload)
        result_dict = result.to_dict() if hasattr(result, "to_dict") else dict(result)
        hits = (result_dict.get("result") or {}).get("hits", [])
        out = []
        for hit in hits:
            fields = hit.get("fields", {})
            out.append(
                {
                    "id": hit.get("_id"),
                    "score": hit.get("_score"),
                    "text": fields.get("chunk_text", ""),
                    "lifelog_id": fields.get("lifelog_id"),
                    "lifelog_title": fields.get("lifelog_title"),
                    "start_time": fields.get("start_time"),
                    "end_time": fields.get("end_time"),
                    "speakers": fields.get("speakers", []),
                    "chunk_index": fields.get("chunk_index"),
                }
            )
        return out

    def stats(self) -> dict[str, Any]:
        return self._index.describe_index_stats().to_dict()
