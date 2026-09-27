"""Application service for projects and membership.

Encodes the tenancy rules:

* a **global owner** (``Principal.role == "owner"``) creates projects and
  moderates every project;
* a project **admin** (``project_members.role``) moderates their own project
  (connectors, documents, members);
* a project **member** may use the project but not moderate it.

Permission checks (``project_role`` / ``require_access`` /
``require_moderate``) are the single source of truth the web deps build on.
"""

import uuid
from datetime import UTC, datetime

from service.core.auth import PermissionDenied, Principal
from service.models import Project, ProjectMember
from service.storage.store import ProjectStore

_MODERATOR_ROLES = ("owner", "admin")


class ProjectError(Exception):
    """Base class for project-management failures."""


class UnknownProject(ProjectError):
    """No project with the given id."""


class ProjectService:
    def __init__(self, *, store: ProjectStore) -> None:
        self._store = store

    # -- projects ---------------------------------------------------------

    async def create(self, *, name: str, creator: Principal) -> Project:
        if creator.role != "owner":
            raise PermissionDenied("only the owner can create projects")
        now = datetime.now(UTC)
        project = Project(
            id=uuid.uuid4().hex,
            name=name,
            created_by=creator.user_id,
            created_at=now,
            updated_at=now,
        )
        await self._store.add(project)
        return project

    async def get(self, project_id: str) -> Project:
        project = await self._store.get(project_id)
        if project is None:
            raise UnknownProject(project_id)
        return project

    async def list_visible(self, principal: Principal) -> list[Project]:
        """Owner sees all projects; everyone else sees their memberships."""
        if principal.role == "owner":
            return await self._store.list_all()
        return await self._store.list_for_user(principal.user_id)

    async def delete(self, project_id: str, actor: Principal) -> None:
        if actor.role != "owner":
            raise PermissionDenied("only the owner can delete projects")
        await self._store.delete(project_id)

    # -- permission checks ------------------------------------------------

    async def project_role(
        self, principal: Principal, project_id: str
    ) -> str | None:
        """The caller's effective role on a project, or ``None`` if no access.

        The global owner is ``"owner"`` on every project without a membership
        row.
        """
        if principal.role == "owner":
            return "owner"
        member = await self._store.get_member(project_id, principal.user_id)
        return member.role if member is not None else None

    async def require_access(
        self, principal: Principal, project_id: str
    ) -> str:
        role = await self.project_role(principal, project_id)
        if role is None:
            raise PermissionDenied("not a member of this project")
        return role

    async def require_moderate(
        self, principal: Principal, project_id: str
    ) -> str:
        role = await self.require_access(principal, project_id)
        if role not in _MODERATOR_ROLES:
            raise PermissionDenied("requires project admin")
        return role

    # -- members ----------------------------------------------------------

    async def list_members(self, project_id: str) -> list[ProjectMember]:
        return await self._store.list_members(project_id)

    async def add_member(
        self, *, project_id: str, user_id: str, role: str, actor: Principal
    ) -> ProjectMember:
        await self.require_moderate(actor, project_id)
        if role not in ("admin", "member"):
            raise ProjectError(f"invalid project role: {role!r}")
        # only the owner may grant the admin role
        if role == "admin" and actor.role != "owner":
            raise PermissionDenied("only the owner can add project admins")
        member = ProjectMember(
            project_id=project_id,
            user_id=user_id,
            role=role,
            created_at=datetime.now(UTC),
        )
        await self._store.add_member(member)
        return member

    async def remove_member(
        self, *, project_id: str, user_id: str, actor: Principal
    ) -> None:
        await self.require_moderate(actor, project_id)
        await self._store.remove_member(project_id, user_id)

    async def accept_invite(
        self, *, project_id: str, user_id: str, role: str
    ) -> ProjectMember:
        """Add a membership from a verified project invite.

        No actor check: the signed invite *is* the authorization (its issuer
        was checked at mint time). The project must still exist.
        """
        if role not in ("admin", "member"):
            raise ProjectError(f"invalid project role: {role!r}")
        await self.get(project_id)  # raises UnknownProject if it vanished
        member = ProjectMember(
            project_id=project_id,
            user_id=user_id,
            role=role,
            created_at=datetime.now(UTC),
        )
        await self._store.add_member(member)
        return member
