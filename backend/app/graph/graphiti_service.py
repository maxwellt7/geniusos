"""Graphiti + Neo4j Aura integration.

Each lifelog is ingested as a Graphiti *episode* with reference_time set to
the lifelog's start time, giving us the bi-temporal model out of the box
(fact validity vs. ingestion time). Episode names embed the lifelog ID so
every extracted fact traces back to its source lifelog.

Provider setup:
- LLM: Theo (hitheo.ai) via Graphiti's OpenAIGenericClient in json_object
  mode (Theo doesn't support json_schema constrained decoding).
- Embeddings: local sentence-transformers (Theo has no embeddings endpoint).
- Reranker: local BGE cross-encoder (no logprobs-based OpenAI reranking).
"""

import asyncio
import logging
import os
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.graph.entities import ENTITY_TYPES

logger = logging.getLogger(__name__)

EPISODE_PREFIX = "lifelog:"
LOCAL_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
LOCAL_EMBEDDING_DIM = 384

# Must be set before graphiti_core.embedder is imported (module-level constant).
os.environ.setdefault("EMBEDDING_DIM", str(LOCAL_EMBEDDING_DIM))


from graphiti_core.embedder.client import EmbedderClient  # noqa: E402
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient  # noqa: E402


class TolerantOpenAIGenericClient(OpenAIGenericClient):
    """Hardens the generic client for quirky OpenAI-compatible providers (Theo).

    - Extracts the first JSON value from responses that wrap JSON in prose
      (Theo appends commentary after the object even in json_object mode).
    - Validates against the expected response model and raises a retryable
      error when the model echoes the JSON schema instead of an instance.
    """

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        import json as _json

        stripped = OpenAIGenericClient._strip_code_fences(text)
        for opener in ("{", "["):
            start = stripped.find(opener)
            if start == -1:
                continue
            try:
                value, _ = _json.JSONDecoder().raw_decode(stripped[start:])
                return _json.dumps(value)
            except _json.JSONDecodeError:
                continue
        return stripped

    async def _generate_response(self, messages, response_model=None, *args, **kwargs):
        from graphiti_core.llm_client.errors import EmptyResponseError
        from pydantic import ValidationError

        result = await super()._generate_response(messages, response_model, *args, **kwargs)
        if response_model is not None and isinstance(result, dict):
            # Schema echo: the model returned the JSON schema we sent it.
            if "properties" in result and result.get("type") == "object":
                raise EmptyResponseError("LLM echoed the JSON schema instead of an instance")
            try:
                response_model.model_validate(result)
            except ValidationError as exc:
                raise EmptyResponseError(
                    f"LLM response failed {response_model.__name__} validation: {exc}"
                ) from exc
        return result


class LocalEmbedder(EmbedderClient):
    """Graphiti EmbedderClient backed by a local sentence-transformers model."""

    def __init__(self):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(LOCAL_EMBEDDING_MODEL)

    def _encode(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, normalize_embeddings=True).tolist()

    async def create(
        self, input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]]
    ) -> list[float]:
        text = input_data if isinstance(input_data, str) else list(input_data)[0]
        return (await asyncio.to_thread(self._encode, [str(text)]))[0]

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._encode, [str(t) for t in input_data_list])


class GraphService:
    def __init__(self):
        settings = get_settings()
        if not settings.neo4j_uri:
            raise RuntimeError("NEO4J_URI is not configured")

        from graphiti_core import Graphiti
        from graphiti_core.cross_encoder.bge_reranker_client import BGERerankerClient
        from graphiti_core.llm_client.config import LLMConfig

        llm_config = LLMConfig(
            api_key=settings.openai_api_key,
            model=settings.chat_model,
            small_model=settings.router_model,
            base_url=settings.openai_base_url,
        )
        llm_client = TolerantOpenAIGenericClient(
            config=llm_config, structured_output_mode="json_object"
        )

        self._graphiti = Graphiti(
            settings.neo4j_uri,
            settings.neo4j_user,
            settings.neo4j_password,
            llm_client=llm_client,
            embedder=LocalEmbedder(),
            cross_encoder=BGERerankerClient(),
        )

    async def initialize(self) -> None:
        await self._graphiti.build_indices_and_constraints()

    async def add_lifelog_episode(
        self,
        lifelog_id: str,
        title: str | None,
        transcript: str,
        start_time: datetime | None,
    ) -> None:
        from graphiti_core.nodes import EpisodeType

        reference_time = start_time or datetime.now(timezone.utc)
        kwargs: dict[str, Any] = dict(
            name=f"{EPISODE_PREFIX}{lifelog_id}",
            episode_body=transcript,
            source=EpisodeType.text,
            source_description=f"Limitless lifelog '{title or lifelog_id}' ({lifelog_id})",
            reference_time=reference_time,
        )
        try:
            await self._graphiti.add_episode(entity_types=ENTITY_TYPES, **kwargs)
        except TypeError:
            # Older graphiti-core versions don't accept entity_types.
            await self._graphiti.add_episode(**kwargs)
        logger.info("Graph episode added for lifelog %s", lifelog_id)

    async def search(self, query: str, num_results: int = 10) -> list[dict[str, Any]]:
        """Hybrid graph search; returns facts with lifelog provenance."""
        results = await self._graphiti.search(query, num_results=num_results)

        # Edge.episodes holds episode UUIDs; resolve them to episode names
        # (which embed the source lifelog ID) for citations.
        episode_uuids = {u for edge in results for u in (getattr(edge, "episodes", []) or [])}
        uuid_to_lifelog: dict[str, str] = {}
        if episode_uuids:
            try:
                from graphiti_core.nodes import EpisodicNode

                nodes = await EpisodicNode.get_by_uuids(
                    self._graphiti.driver, list(episode_uuids)
                )
                for node in nodes:
                    if node.name.startswith(EPISODE_PREFIX):
                        uuid_to_lifelog[node.uuid] = node.name[len(EPISODE_PREFIX):]
            except Exception:
                logger.exception("Failed to resolve episode provenance")

        facts: list[dict[str, Any]] = []
        for edge in results:
            lifelog_ids = [
                uuid_to_lifelog[u]
                for u in (getattr(edge, "episodes", []) or [])
                if u in uuid_to_lifelog
            ]
            facts.append(
                {
                    "fact": getattr(edge, "fact", str(edge)),
                    "valid_at": _iso(getattr(edge, "valid_at", None)),
                    "invalid_at": _iso(getattr(edge, "invalid_at", None)),
                    "created_at": _iso(getattr(edge, "created_at", None)),
                    "episodes": [f"{EPISODE_PREFIX}{lid}" for lid in lifelog_ids],
                }
            )
        return facts

    async def close(self) -> None:
        await self._graphiti.close()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None
