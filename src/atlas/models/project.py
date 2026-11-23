from datetime import datetime
from typing import Literal, get_args

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column as column

from atlas.models.base import Base, Timestamped, UTCDateTime, new_id, utcnow

ProjectRole = Literal["admin", "member"]
ProjectSort = Literal["name", "-name", "created_at", "-created_at"]


class Project(Timestamped, Base, kw_only=True, eq=False):
    """A tenant boundary: documents, connectors and members live under it."""

    __tablename__ = "projects"

    id: Mapped[str] = column(String, primary_key=True, default_factory=new_id)
    name: Mapped[str] = column(String)
    created_by: Mapped[str] = column(String)  # the creating user's id


class ProjectMember(Base, kw_only=True, eq=False):
    """A user's role within one project. The instance owner needs no row:
    they act on every project."""

    __tablename__ = "project_members"

    project_id: Mapped[str] = column(String, primary_key=True)
    user_id: Mapped[str] = column(String, primary_key=True, index=True)
    role: Mapped[ProjectRole] = column(
        Enum(*get_args(ProjectRole), name="project_role")
    )
    created_at: Mapped[datetime | None] = column(
        UTCDateTime(), default_factory=utcnow, init=False
    )
