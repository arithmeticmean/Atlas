"""Projects, and who is in them."""

import logging
from dataclasses import dataclass
from datetime import datetime

from atlas.models.project import (
    Project,
    ProjectMember,
    ProjectRole,
    ProjectSort,
)
from atlas.models.user import User
from atlas.repository.base import Conflict, Paged, PageRequest
from atlas.repository.uow import UnitOfWorkFactory
from atlas.services.access import (
    Caller,
    EffectiveRole,
    load_project,
    require_instance_admin,
)
from atlas.services.ai import AIRuntime
from atlas.services.errors import (
    AlreadyExists,
    InvalidInput,
    NotFound,
    PermissionDenied,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProjectView:
    """A project, with the caller's role on it."""

    id: str
    name: str
    created_by: str
    created_at: datetime | None
    updated_at: datetime | None
    my_role: EffectiveRole


@dataclass(frozen=True, slots=True)
class MemberView:
    user_id: str
    user: User | None  # None once the account has been deleted
    role: ProjectRole
    created_at: datetime | None


def _project_view(project: Project, role: EffectiveRole) -> ProjectView:
    return ProjectView(
        id=project.id,
        name=project.name,
        created_by=project.created_by,
        created_at=project.created_at,
        updated_at=project.updated_at,
        my_role=role,
    )


def _member_view(member: ProjectMember, user: User | None) -> MemberView:
    return MemberView(
        user_id=member.user_id,
        user=user,
        role=member.role,
        created_at=member.created_at,
    )


class ProjectService:
    def __init__(self, *, uow: UnitOfWorkFactory, ai: AIRuntime) -> None:
        self._uow = uow
        self._ai = ai

    # -- projects ----------------------------------------------------------

    async def create(self, caller: Caller, *, name: str) -> ProjectView:
        require_instance_admin(caller)
        async with self._uow() as uow:
            project = await uow.projects.add(
                Project(name=name, created_by=caller.user_id)
            )
        return _project_view(project, "owner")

    async def list_visible(
        self,
        caller: Caller,
        page: PageRequest,
        *,
        q: str | None = None,
        sort: ProjectSort = "name",
    ) -> Paged[ProjectView]:
        """Instance admins see every project; everyone else their own."""
        async with self._uow() as uow:
            if caller.is_instance_admin:
                every = await uow.projects.page(page, q=q, sort=sort)
                return every.map(lambda p: _project_view(p, "owner"))
            mine = await uow.projects.page_for_member(
                caller.user_id, page, q=q, sort=sort
            )
        return mine.map(lambda row: _project_view(*row))

    async def get(self, caller: Caller, project_id: str) -> ProjectView:
        async with self._uow() as uow:
            return _project_view(*await load_project(uow, caller, project_id))

    async def rename(
        self, caller: Caller, project_id: str, *, name: str
    ) -> ProjectView:
        async with self._uow() as uow:
            project, role = await load_project(
                uow, caller, project_id, admin=True
            )
            project.name = name
        return _project_view(project, role)

    async def delete(self, caller: Caller, project_id: str) -> None:
        """The project with its documents, connectors, members and files."""
        require_instance_admin(caller)
        async with self._uow() as uow:
            project, _ = await load_project(uow, caller, project_id)
            documents = await uow.documents.list_for_project(project_id)
            await uow.projects.delete(project)
            await uow.commit()
            for document in documents:
                await uow.documents.delete_file(document)
        try:
            await self._ai.remove_project(project_id)
        except Exception:
            logger.warning(
                "could not remove the chunks of project %s",
                project_id,
                exc_info=True,
            )

    # -- members -----------------------------------------------------------

    async def list_members(
        self,
        caller: Caller,
        project_id: str,
        page: PageRequest,
        *,
        role: ProjectRole | None = None,
    ) -> Paged[MemberView]:
        async with self._uow() as uow:
            await load_project(uow, caller, project_id)
            members = await uow.members.page_with_users(
                project_id, page, role=role
            )
        return members.map(lambda row: _member_view(*row))

    async def add_member(
        self,
        caller: Caller,
        project_id: str,
        *,
        user_id: str,
        role: ProjectRole = "member",
    ) -> MemberView:
        async with self._uow() as uow:
            await load_project(uow, caller, project_id, admin=True)
            if role == "admin" and not caller.is_instance_admin:
                raise PermissionDenied(
                    "only instance admins add project admins"
                )
            user = await uow.users.get(user_id)
            if user is None or user.status != "active":
                raise NotFound("user not found", code="user_not_found")
            try:
                member = await uow.members.add(
                    ProjectMember(
                        project_id=project_id, user_id=user_id, role=role
                    )
                )
            except Conflict as exc:
                raise AlreadyExists(
                    "already a member", code="already_member"
                ) from exc
        return _member_view(member, user)

    async def change_role(
        self,
        caller: Caller,
        project_id: str,
        user_id: str,
        *,
        role: ProjectRole,
    ) -> MemberView:
        async with self._uow() as uow:
            await load_project(uow, caller, project_id, admin=True)
            if not caller.is_instance_admin:
                raise PermissionDenied(
                    "only instance admins change project roles"
                )
            member = await uow.members.find(project_id, user_id)
            if member is None:
                raise NotFound("not a member", code="member_not_found")
            member.role = role
            user = await uow.users.get(user_id)
        return _member_view(member, user)

    async def remove_member(
        self, caller: Caller, project_id: str, user_id: str
    ) -> None:
        """``user_id="me"`` leaves the project. Anyone may leave; removing
        someone else takes a project admin."""
        if user_id == "me":
            user_id = caller.user_id
        async with self._uow() as uow:
            leaving = user_id == caller.user_id
            await load_project(uow, caller, project_id, admin=not leaving)
            member = await uow.members.find(project_id, user_id)
            if member is None:
                if leaving and caller.is_instance_admin:
                    raise InvalidInput(
                        "instance admins belong to every project"
                    )
                raise NotFound("not a member", code="member_not_found")
            await uow.members.delete(member)
