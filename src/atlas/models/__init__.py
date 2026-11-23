"""Persisted entities: one SQLAlchemy dataclass per table.

Every model module is imported here so that importing ``atlas.models``
registers the whole schema on ``Base.metadata``, which is what Alembic
compares against. This is the one package that re-exports, for that reason;
all its modules import SQLAlchemy anyway, so it costs nothing extra.
"""

from atlas.models.chat import Chat, Message
from atlas.models.connector import Connector
from atlas.models.document import Document, DocumentTag
from atlas.models.job import IngestionJob
from atlas.models.project import Project, ProjectMember
from atlas.models.settings import StoredSettings
from atlas.models.user import User

__all__ = [
    "Chat",
    "Connector",
    "Document",
    "DocumentTag",
    "IngestionJob",
    "Message",
    "Project",
    "ProjectMember",
    "StoredSettings",
    "User",
]
