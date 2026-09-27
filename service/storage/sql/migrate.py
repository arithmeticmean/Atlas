"""Run Alembic migrations from inside the process.

An installed Atlas has no repository checkout and no ``alembic`` on PATH --
``uv tool install`` exposes only the target package's own entry points, so a
dependency's console script is not available to the user. Shipping schema
management as a shell step therefore cannot work for a distributed application.

Instead ``alembic.ini`` and ``migrations/`` travel inside the package, and this
module drives Alembic's Python API against them. ``script_location`` resolves
from the package's own location rather than the working directory, so it is
correct whether Atlas is running from a checkout, a wheel in site-packages, or
a frozen bundle.
"""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

from service.config import get_settings

logger = logging.getLogger(__name__)

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(_PACKAGE_ROOT / "alembic.ini"))
    # Both are set explicitly: the ini's %(here)s would resolve correctly, but
    # being explicit keeps this working if the package is ever loaded from a
    # zip or a bundle where the ini is not on a real filesystem path.
    config.set_main_option(
        "script_location", str(_PACKAGE_ROOT / "migrations")
    )
    config.set_main_option("sqlalchemy.url", database_url)
    # Tells migrations/env.py not to reconfigure logging or second-guess
    # the URL: we are driving it, not the alembic CLI.
    config.set_main_option("atlas_in_process", "true")
    return config


def upgrade_to_head(database_url: str | None = None) -> None:
    """Bring the configured database up to the latest revision.

    Idempotent: already-current databases are a no-op. Safe to call on every
    startup, which is how an installed instance stays migrated without the user
    ever running a migration command.
    """
    url = database_url or get_settings().database_url
    if url.startswith("sqlite"):
        # Alembic connects with its own engine, so the parent directory has to
        # exist first -- SQLite will not create it.
        _ensure_sqlite_parent(url)
    logger.info("applying database migrations")
    command.upgrade(_alembic_config(url), "head")


def current_revision(database_url: str | None = None) -> str | None:
    """The revision the database is stamped at, or ``None`` if unstamped."""
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine

    url = database_url or get_settings().database_url
    sync_url = url.replace("+aiosqlite", "").replace("+asyncpg", "+psycopg")
    engine = create_engine(sync_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            return context.get_current_revision()
    finally:
        engine.dispose()


def _ensure_sqlite_parent(url: str) -> None:
    path = url.split("///", 1)[-1]
    if path and path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
