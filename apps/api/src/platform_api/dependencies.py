from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from .config import get_settings


async def check_database() -> bool:
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")
        return True
    finally:
        await engine.dispose()


async def check_redis() -> bool:
    client = Redis.from_url(get_settings().redis_url, socket_connect_timeout=1)
    try:
        return bool(await client.ping())
    finally:
        await client.aclose()
