from typing import Protocol, cast

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from .config import get_settings


class RedisHealthClient(Protocol):
    async def ping(self) -> bool: ...

    async def aclose(self) -> None: ...


async def check_database() -> bool:
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")
        return True
    finally:
        await engine.dispose()


async def check_redis() -> bool:
    client = cast(
        RedisHealthClient,
        Redis.from_url(  # pyright: ignore[reportUnknownMemberType]
            get_settings().redis_url,
            socket_connect_timeout=1,
        ),
    )
    try:
        return bool(await client.ping())
    finally:
        await client.aclose()
