"""Atlas's configuration, in two parts.

``BootstrapSettings``
    The four values needed before the database can be opened, read only from
    the environment: ``ATLAS_DATA_PATH``, ``ATLAS_HOST``, ``ATLAS_PORT`` and
    the optional ``ATLAS_MASTER_KEY``.

``InstanceSettings``
    Everything else. Stored in the database and changed while Atlas runs,
    through ``services.settings.SettingsService``.

``Settings`` is the immutable snapshot of both that the rest of the code
receives when it is constructed. Nothing imports a global settings object.
"""

from atlas.config.encryption import MasterKey
from atlas.config.settings import (
    SECRET_FIELDS,
    BootstrapSettings,
    InstanceSettings,
    Settings,
)

__all__ = [
    "SECRET_FIELDS",
    "BootstrapSettings",
    "InstanceSettings",
    "MasterKey",
    "Settings",
]
