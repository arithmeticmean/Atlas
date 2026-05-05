"""Project store port (projects + their memberships)."""

from abc import ABC, abstractmethod

from models import Project, ProjectMember


class ProjectStore(ABC):
    @abstractmethod
    async def add(self, project: Project) -> None:
        """Insert a new project."""

    @abstractmethod
    async def get(self, project_id: str) -> Project | None:
        """Return the project, or ``None``."""

    @abstractmethod
    async def list_all(self) -> list[Project]:
        """Every project (owner view), newest first."""

    @abstractmethod
    async def list_for_user(self, user_id: str) -> list[Project]:
        """Projects the user is a member of, newest first."""

    @abstractmethod
    async def delete(self, project_id: str) -> None:
        """Delete a project and its membership rows."""

    @abstractmethod
    async def add_member(self, member: ProjectMember) -> None:
        """Add a member, or update their role if already present."""

    @abstractmethod
    async def get_member(
        self, project_id: str, user_id: str
    ) -> ProjectMember | None:
        """Return the membership row, or ``None``."""

    @abstractmethod
    async def list_members(self, project_id: str) -> list[ProjectMember]:
        """All members of a project."""

    @abstractmethod
    async def remove_member(self, project_id: str, user_id: str) -> None:
        """Remove a member (no error if absent)."""
