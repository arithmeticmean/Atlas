"""Where Atlas keeps everything it owns on the local machine.

One directory holds the entire instance -- configuration, secrets, the SQLite
database, the LanceDB index, the raw document blobs, and logs. That is a
deliberate choice over scattering state across XDG's config/data/state/cache
split: the SQLite database and the LanceDB index are only meaningful *together*
(chunk rows live in LanceDB, their document metadata in SQLite), so a backup or
a move that catches one but not the other is a corrupt instance. One directory
makes "back it up", "move it to another machine", and "delete it" single,
obvious operations.

Resolution order:

1. ``ATLAS_HOME`` -- an explicit instance directory, however the user spells it
   (``~`` and environment variables are expanded).
2. ``~/.atlas`` -- the default.

Nothing here reads configuration, so this module is safe to import before an
instance exists. That matters: ``atlas init`` has to know where to *write*
config before any config can be read.
"""

import os
from pathlib import Path

ENV_HOME = "ATLAS_HOME"

_DEFAULT_DIRNAME = ".atlas"

CONFIG_NAME = "config.toml"
SECRETS_NAME = "secrets.toml"
DB_NAME = "atlas.db"
VECTOR_DIRNAME = "lance"
BLOB_DIRNAME = "blobs"
LOG_DIRNAME = "logs"


def atlas_home() -> Path:
    """The instance directory. Not created as a side effect of asking."""
    raw = os.environ.get(ENV_HOME)
    if raw:
        return Path(os.path.expandvars(raw)).expanduser().resolve()
    return (Path.home() / _DEFAULT_DIRNAME).resolve()


def config_file() -> Path:
    """Non-secret settings. Safe to read, share, or paste into a bug report."""
    return atlas_home() / CONFIG_NAME


def secrets_file() -> Path:
    """API keys and the token-signing secret. Written 0600, never logged."""
    return atlas_home() / SECRETS_NAME


def database_path() -> Path:
    return atlas_home() / DB_NAME


def database_url() -> str:
    """A SQLite URL for this instance.

    Absolute, so the database no longer depends on the working directory the
    process happened to start in. Note the four slashes: ``sqlite:///`` plus a
    path that itself begins with ``/``.
    """
    return f"sqlite+aiosqlite:///{database_path()}"


def vector_path() -> Path:
    return atlas_home() / VECTOR_DIRNAME


def blob_path() -> Path:
    return atlas_home() / BLOB_DIRNAME


def log_dir() -> Path:
    return atlas_home() / LOG_DIRNAME


def ensure_home() -> Path:
    """Create the instance directory tree; return its root.

    Idempotent. ``mode=0o700`` on the root because secrets live inside it.
    """
    home = atlas_home()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    for child in (vector_path(), blob_path(), log_dir()):
        child.mkdir(parents=True, exist_ok=True)
    return home


def is_initialized() -> bool:
    """Whether ``atlas init`` has been run for this instance directory."""
    return config_file().is_file()
