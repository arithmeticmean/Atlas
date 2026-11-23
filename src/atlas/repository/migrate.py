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

from atlas.config import BootstrapSettings

logger = logging.getLogger(__name__)

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]


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


def upgrade_to_head(*, settings: BootstrapSettings) -> None:
    """Bring the configured database up to the latest revision.

    Idempotent: already-current databases are a no-op. Safe to call on every
    startup, which is how an installed instance stays migrated without the user
    ever running a migration command.
    """
    settings.create_directories()
    logger.info("applying database migrations")
    command.upgrade(_alembic_config(settings.database_url), "head")


def current_revision(*, settings: BootstrapSettings) -> str | None:
    """The revision the database is stamped at, or ``None`` if unstamped."""
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine

    engine = create_engine(settings.database_url.replace("+aiosqlite", ""))
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            return context.get_current_revision()
    finally:
        engine.dispose()
