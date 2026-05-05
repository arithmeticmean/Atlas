from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class Project:
    """A tenant boundary: documents, connectors and members live under it."""

    id: str
    name: str
    created_by: str  # user id of the creator (an owner)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class ProjectMember:
    """A user's membership of a project and their role within it.

    Roles are per-project: ``admin`` moderates the project (connectors,
    documents, members); ``member`` uses it. The global owner
    (``User.role == "owner"``) moderates every project and needs no membership
    row.
    """

    project_id: str
    user_id: str
    role: str  # "admin" | "member"
    created_at: datetime | None = None
