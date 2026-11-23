"""Build the SQLite engine and session factory.

Nothing is created at import: startup calls these once and owns the result,
including ``await engine.dispose()`` at shutdown.
"""

from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from atlas.config import BootstrapSettings

_CONNECTION_PRAGMAS = (
    "PRAGMA journal_mode=WAL",  # readers don't wait for the writer
    "PRAGMA synchronous=NORMAL",  # safe with WAL, and much faster
    "PRAGMA busy_timeout=5000",  # wait for a brief write lock, don't fail
    "PRAGMA foreign_keys=ON",  # SQLite leaves these off by default
)


def create_engine(*, settings: BootstrapSettings) -> AsyncEngine:
    engine = create_async_engine(settings.database_url)
    event.listen(engine.sync_engine, "connect", _configure_connection)
    return engine


def create_sessionmaker(
    *, engine: AsyncEngine
) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: entities stay readable after their unit of work
    # closes, which background code and responses rely on.
    return async_sessionmaker(engine, expire_on_commit=False)


def _configure_connection(connection: Any, _record: Any) -> None:
    cursor = connection.cursor()
    for pragma in _CONNECTION_PRAGMAS:
        cursor.execute(pragma)
    cursor.close()
