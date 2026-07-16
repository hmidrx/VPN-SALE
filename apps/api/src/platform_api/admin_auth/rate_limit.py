from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from redis import RedisError
from redis.asyncio import Redis

from platform_api.config import Settings

from .service import hardened_rate_key


class RateLimitUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    retry_after: int


class RateLimiter(Protocol):
    async def check(
        self, purpose: str, *parts: str, limit: int, window_seconds: int
    ) -> RateLimitResult: ...


class InMemoryRateLimiter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._hits: dict[str, tuple[int, datetime]] = {}

    async def check(
        self, purpose: str, *parts: str, limit: int, window_seconds: int
    ) -> RateLimitResult:
        now = datetime.now(UTC)
        key = hardened_rate_key(purpose, *parts, salt=self.settings.opaque_token_hash_salt)
        count, start = self._hits.get(key, (0, now))
        if now >= start + timedelta(seconds=window_seconds):
            count, start = 0, now
        count += 1
        self._hits[key] = (count, start)
        retry = max(1, int((start + timedelta(seconds=window_seconds) - now).total_seconds()))
        return RateLimitResult(count <= limit, retry)


class RedisRateLimiter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = Redis.from_url(settings.redis_url, socket_connect_timeout=1)  # pyright: ignore[reportUnknownMemberType]

    async def check(
        self, purpose: str, *parts: str, limit: int, window_seconds: int
    ) -> RateLimitResult:
        key = hardened_rate_key(purpose, *parts, salt=self.settings.opaque_token_hash_salt)
        try:
            count = await self._client.incr(key)
            if count == 1:
                await self._client.expire(key, window_seconds)
            ttl = await self._client.ttl(key)
        except RedisError as exc:
            raise RateLimitUnavailable("rate limit backend unavailable") from exc
        retry = int(ttl if ttl and ttl > 0 else window_seconds)
        return RateLimitResult(int(count) <= limit, retry)

    async def aclose(self) -> None:
        await self._client.aclose()
