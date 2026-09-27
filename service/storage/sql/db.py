"""Async SQLAlchemy engine, session factory, and the declarative base.

The engine is built lazily rather than at import. That is what lets ``atlas
init`` import this package *before* an instance exists: constructing an engine
at import time would bind it to whatever ``database_url`` happened to be
resolvable then, which for a fresh install is a database that has not been
created yet. Building on first use also means ``reload_settings()`` after
``atlas init`` writes its files is actually honoured.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from service.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> AsyncEngine:
    """The process-wide engine, created on first use.

    Chosen entirely by the URL: sqlite+aiosqlite for self-hosting,
    postgresql+asyncpg for a Postgres deployment. No code changes to switch.
    """
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=settings.sql_echo,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a session, committing on success and rolling back on error."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Close pooled connections and drop the cached engine.

    Needed when the database URL changes inside one process -- ``atlas init``
    creating an instance it then immediately connects to, and tests that build
    an instance per case.
    """
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
