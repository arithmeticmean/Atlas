"""SQLAlchemy adapter for the ProjectStore port."""

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Project, ProjectMember
from storage.sql.models import Project as OrmProject
from storage.sql.models import ProjectMember as OrmMember
from storage.store.project import ProjectStore


class SqlProjectStore(ProjectStore):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, project: Project) -> None:
        self._session.add(
            OrmProject(
                id=project.id,
                name=project.name,
                created_by=project.created_by,
                created_at=project.created_at,
                updated_at=project.updated_at,
            )
        )
        await self._session.flush()

    async def get(self, project_id: str) -> Project | None:
        row = await self._session.get(OrmProject, project_id)
        return _to_domain(row) if row is not None else None

    async def list_all(self) -> list[Project]:
        rows = (
            await self._session.execute(
                select(OrmProject).order_by(OrmProject.created_at.desc())
            )
        ).scalars().all()
        return [_to_domain(r) for r in rows]

    async def list_for_user(self, user_id: str) -> list[Project]:
        rows = (
            await self._session.execute(
                select(OrmProject)
                .join(OrmMember, OrmMember.project_id == OrmProject.id)
                .where(OrmMember.user_id == user_id)
                .order_by(OrmProject.created_at.desc())
            )
        ).scalars().all()
        return [_to_domain(r) for r in rows]

    async def delete(self, project_id: str) -> None:
        await self._session.execute(
            sa_delete(OrmMember).where(OrmMember.project_id == project_id)
        )
        row = await self._session.get(OrmProject, project_id)
        if row is not None:
            await self._session.delete(row)
        await self._session.flush()

    async def add_member(self, member: ProjectMember) -> None:
        existing = await self._session.get(
            OrmMember,
            {"project_id": member.project_id, "user_id": member.user_id},
        )
        if existing is not None:
            existing.role = member.role
        else:
            self._session.add(
                OrmMember(
                    project_id=member.project_id,
                    user_id=member.user_id,
                    role=member.role,
                    created_at=member.created_at,
                )
            )
        await self._session.flush()

    async def get_member(
        self, project_id: str, user_id: str
    ) -> ProjectMember | None:
        row = await self._session.get(
            OrmMember, {"project_id": project_id, "user_id": user_id}
        )
        return _member_to_domain(row) if row is not None else None

    async def list_members(self, project_id: str) -> list[ProjectMember]:
        rows = (
            await self._session.execute(
                select(OrmMember).where(OrmMember.project_id == project_id)
            )
        ).scalars().all()
        return [_member_to_domain(r) for r in rows]

    async def remove_member(self, project_id: str, user_id: str) -> None:
        row = await self._session.get(
            OrmMember, {"project_id": project_id, "user_id": user_id}
        )
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()


def _to_domain(row: OrmProject) -> Project:
    return Project(
        id=row.id,
        name=row.name,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _member_to_domain(row: OrmMember) -> ProjectMember:
    return ProjectMember(
        project_id=row.project_id,
        user_id=row.user_id,
        role=row.role,
        created_at=row.created_at,
    )
