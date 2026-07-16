from typing import Protocol, cast

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from .config import get_settings


class RedisHealthClient(Protocol):
    async def ping(self) -> object: ...

    async def aclose(self) -> None: ...


async def check_database() -> bool:
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")
        return True
    finally:
        await engine.dispose()


def create_redis_health_client(redis_url: str) -> RedisHealthClient:
    return cast(
        RedisHealthClient,
        Redis.from_url(redis_url, socket_connect_timeout=1),  # pyright: ignore[reportUnknownMemberType]
    )


async def check_redis() -> bool:
    client = create_redis_health_client(get_settings().redis_url)
    try:
        return bool(await client.ping())
    finally:
        await client.aclose()
