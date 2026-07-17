from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    limitless_api_key: str = ""
    limitless_api_base: str = "https://api.limitless.ai/v1"

    database_url: str = "sqlite:///./limitless.db"

    # Extra CORS origins (comma-separated) on top of localhost dev defaults,
    # e.g. the deployed frontend URL. A regex can also be supplied to match
    # Vercel preview deployments.
    cors_origins: str = ""
    cors_origin_regex: str = ""

    pinecone_api_key: str = ""
    pinecone_index_name: str = "limitless-lifelogs"
    pinecone_namespace: str = "default"

    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # Any OpenAI-compatible provider (e.g. Theo at https://www.hitheo.ai/api/v1).
    # Use the www host for Theo: the apex domain 307-redirects and strips auth headers.
    openai_api_key: str = ""
    openai_base_url: str | None = None
    chat_model: str = "gpt-4o"
    router_model: str = "gpt-4o-mini"

    # Optional dedicated provider for graph entity-extraction (Graphiti). Bulk
    # extraction is heavy/structured and benefits from a fast, reliable model
    # (e.g. OpenAI gpt-4o-mini) even when chat runs on a different provider.
    # When graph_llm_api_key is empty, extraction falls back to the openai_* /
    # chat_model settings above. Embeddings always stay local (see graph svc).
    graph_llm_api_key: str = ""
    graph_llm_base_url: str | None = None
    graph_llm_model: str = ""

    # Clerk backend auth. When require_clerk_auth is true, API routes require a
    # valid Clerk session JWT (verified against the issuer's JWKS); a valid
    # session is treated as owner. clerk_jwt_issuer is the Clerk Frontend API
    # origin, e.g. https://clerk.maxmayes.io. clerk_authorized_parties is a
    # comma-separated list of allowed `azp` origins (the app domains).
    clerk_jwt_issuer: str = ""
    clerk_authorized_parties: str = ""
    require_clerk_auth: bool = False

    enable_graph_ingestion: bool = False

    # IANA timezone for interpreting dates in queries ("today", "last week").
    # Empty = system local timezone.
    user_timezone: str = ""

    # Privacy: PIN that unlocks owner mode. If empty, the app always runs in
    # owner mode (no lock). Guests are blocked from privacy-sensitive queries
    # and raw transcript access.
    owner_pin: str = ""
    owner_session_timeout_minutes: int = 15

    # Limitless allows 180 requests/minute; stay safely under it.
    requests_per_minute: int = 150

    # Minutes between automatic incremental syncs (0 disables the scheduler).
    sync_interval_minutes: int = 30


    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """Managed Postgres (Railway/Heroku) hands out `postgres://` or
        `postgresql://` URLs, which SQLAlchemy resolves to the psycopg2 dialect.
        We ship psycopg3 (`psycopg[binary]`), so steer to the psycopg3 driver.
        """
        for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://", "sqlite"):
            if value.startswith(prefix):
                return value
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value[len("postgresql://"):]
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value[len("postgres://"):]
        return value

    @property
    def authorized_parties_list(self) -> list[str]:
        return [p.strip() for p in self.clerk_authorized_parties.split(",") if p.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        defaults = ["http://localhost:3000", "http://127.0.0.1:3000"]
        extra = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return defaults + extra


@lru_cache
def get_settings() -> Settings:
    return Settings()
