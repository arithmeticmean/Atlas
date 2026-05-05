from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from config import settings


class Base(DeclarativeBase):
    pass


# Engine is chosen entirely by the URL: sqlite+aiosqlite for self-hosting,
# postgresql+asyncpg for the Postgres deployment. No code changes to switch.
engine = create_async_engine(
    settings.database_url,
    echo=settings.sql_echo,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a session, committing on success and rolling back on error."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
