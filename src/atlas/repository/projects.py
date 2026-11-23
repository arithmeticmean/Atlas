"""Projects and their memberships.

Memberships get their own repository because they are their own rows with
their own rules; they live in this module because they mean nothing without
a project.
"""

from typing import Any

from sqlalchemy import Select, delete, func, select

from atlas.models.connector import Connector
from atlas.models.document import Document
from atlas.models.job import IngestionJob
from atlas.models.project import (
    Project,
    ProjectMember,
    ProjectRole,
    ProjectSort,
)
from atlas.models.user import User
from atlas.repository.base import CrudRepository, Paged, PageRequest

_MODERATOR_ROLES = ("admin",)


def _visible(
    query: Select[Any], q: str | None, sort: ProjectSort
) -> Select[Any]:
    if q:
        query = query.where(Project.name.icontains(q, autoescape=True))
    column = (
        func.lower(Project.name)
        if sort.endswith("name")
        else Project.created_at
    )
    ordered = column.desc() if sort.startswith("-") else column.asc()
    return query.order_by(ordered, Project.id)


class ProjectRepository(CrudRepository[Project]):
    model = Project

    async def page(
        self, page: PageRequest, *, q: str | None, sort: ProjectSort
    ) -> Paged[Project]:
        return await self._page(_visible(select(Project), q, sort), page)

    async def page_for_member(
        self,
        user_id: str,
        page: PageRequest,
        *,
        q: str | None,
        sort: ProjectSort,
    ) -> Paged[tuple[Project, ProjectRole]]:
        query = (
            select(Project, ProjectMember.role)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user_id)
        )
        return await self._page_rows(_visible(query, q, sort), page)

    async def list_for_member(
        self, user_id: str
    ) -> list[tuple[Project, ProjectRole]]:
        """The projects ``user_id`` belongs to, with their role on each, in
        one query."""
        rows = await self.session.execute(
            select(Project, ProjectMember.role)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user_id)
            .order_by(Project.created_at.desc())
        )
        return [(project, role) for project, role in rows.tuples()]

    async def delete(self, entity: Project) -> None:
        """The project's rows and everything under it: documents, their
        jobs, connectors, memberships. Explicit because there are no foreign
        keys to cascade yet. Delete the documents' files after committing,
        as for a single document."""
        in_project = Document.project_id == entity.id
        documents = select(Document.id).where(in_project)
        for statement in (
            delete(IngestionJob).where(
                IngestionJob.document_id.in_(documents)
            ),
            delete(Document).where(in_project),
            delete(Connector).where(Connector.project_id == entity.id),
            delete(ProjectMember).where(ProjectMember.project_id == entity.id),
        ):
            await self.session.execute(statement)
        await super().delete(entity)


class MembershipRepository(CrudRepository[ProjectMember]):
    model = ProjectMember

    async def find(
        self, project_id: str, user_id: str
    ) -> ProjectMember | None:
        return await self.get((project_id, user_id))

    async def page_with_users(
        self,
        project_id: str,
        page: PageRequest,
        *,
        role: ProjectRole | None = None,
    ) -> Paged[tuple[ProjectMember, User | None]]:
        """Each membership with its account, in one query. ``None`` for a
        membership whose account has been deleted."""
        query = (
            select(ProjectMember, User)
            .outerjoin(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id)
        )
        if role is not None:
            query = query.where(ProjectMember.role == role)
        return await self._page_rows(
            query.order_by(ProjectMember.created_at, ProjectMember.user_id),
            page,
        )

    async def delete_for_user(self, user_id: str) -> None:
        await self.session.execute(
            delete(ProjectMember).where(ProjectMember.user_id == user_id)
        )

    async def administers_any(self, user_id: str) -> bool:
        rows = await self.session.scalars(
            select(ProjectMember.project_id)
            .where(
                ProjectMember.user_id == user_id,
                ProjectMember.role.in_(_MODERATOR_ROLES),
            )
            .limit(1)
        )
        return rows.first() is not None

    async def user_ids_moderated_by(self, user_id: str) -> set[str]:
        """Everyone in the projects ``user_id`` moderates, themselves
        included."""
        moderated = select(ProjectMember.project_id).where(
            ProjectMember.user_id == user_id,
            ProjectMember.role.in_(_MODERATOR_ROLES),
        )
        rows = await self.session.scalars(
            select(ProjectMember.user_id)
            .where(ProjectMember.project_id.in_(moderated))
            .distinct()
        )
        return set(rows)
