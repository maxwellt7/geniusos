from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    limitless_api_key: str = ""
    limitless_api_base: str = "https://api.limitless.ai/v1"

    database_url: str = "sqlite:///./limitless.db"

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
