"""Client for the Limitless Developer API (/v1/lifelogs).

Handles cursor-based pagination, retry with exponential backoff, and
client-side rate limiting to stay under the 180 requests/minute cap.
"""

import logging
import time
from collections.abc import Iterator
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
PAGE_LIMIT = 10  # Limitless caps limit at 10


class RateLimiter:
    """Simple interval-based rate limiter."""

    def __init__(self, requests_per_minute: int):
        self.min_interval = 60.0 / max(requests_per_minute, 1)
        self._last_request = 0.0

    def wait(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request = time.monotonic()


class LimitlessClient:
    def __init__(self, api_key: str | None = None):
        settings = get_settings()
        self.api_key = api_key or settings.limitless_api_key
        self.base_url = settings.limitless_api_base
        self.rate_limiter = RateLimiter(settings.requests_per_minute)
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"X-API-Key": self.api_key},
            timeout=60.0,
        )

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        backoff = 2.0
        for attempt in range(1, MAX_RETRIES + 1):
            self.rate_limiter.wait()
            try:
                resp = self._client.get(path, params=params)
            except httpx.TransportError as exc:
                if attempt == MAX_RETRIES:
                    raise
                logger.warning("Transport error (%s), retrying in %.1fs", exc, backoff)
                time.sleep(backoff)
                backoff *= 2
                continue

            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", backoff))
                logger.warning("Rate limited; sleeping %.1fs", retry_after)
                time.sleep(retry_after)
                backoff *= 2
                continue
            if resp.status_code >= 500:
                if attempt == MAX_RETRIES:
                    resp.raise_for_status()
                logger.warning("Server error %s, retrying in %.1fs", resp.status_code, backoff)
                time.sleep(backoff)
                backoff *= 2
                continue

            resp.raise_for_status()
            return resp.json()
        raise RuntimeError("Exhausted retries calling Limitless API")

    def iter_lifelogs(
        self,
        start: str | None = None,
        end: str | None = None,
        timezone: str = "UTC",
        direction: str = "asc",
        include_markdown: bool = True,
        include_headings: bool = True,
    ) -> Iterator[dict[str, Any]]:
        """Yield lifelog objects, following cursor pagination."""
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {
                "limit": PAGE_LIMIT,
                "direction": direction,
                "timezone": timezone,
                "includeMarkdown": str(include_markdown).lower(),
                "includeHeadings": str(include_headings).lower(),
            }
            if start:
                params["start"] = start
            if end:
                params["end"] = end
            if cursor:
                params["cursor"] = cursor

            payload = self._get("/lifelogs", params)
            lifelogs = (payload.get("data") or {}).get("lifelogs") or []
            yield from lifelogs

            meta = ((payload.get("meta") or {}).get("lifelogs")) or {}
            cursor = meta.get("nextCursor")
            if not cursor or not lifelogs:
                break

    def close(self) -> None:
        self._client.close()
