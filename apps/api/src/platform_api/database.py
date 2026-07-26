from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings


def sync_database_url(url: str) -> str:
    scheme, separator, remainder = url.partition("://")
    if not separator:
        return url
    sync_schemes = {
        "postgresql+asyncpg": "postgresql+psycopg",
        "postgresql": "postgresql+psycopg",
        "postgres": "postgresql+psycopg",
        "sqlite+aiosqlite": "sqlite",
    }
    return f"{sync_schemes.get(scheme, scheme)}://{remainder}"


@lru_cache
def get_engine() -> Engine:
    return create_engine(sync_database_url(get_settings().database_url), pool_pre_ping=True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db_session() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine() -> None:
    get_engine().dispose()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
