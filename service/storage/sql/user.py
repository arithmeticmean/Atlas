"""SQLAlchemy adapter for the UserStore port."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import User
from storage.sql.models import User as OrmUser
from storage.store.user import UserStore


class SqlUserStore(UserStore):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> None:
        self._session.add(_to_orm(user))
        await self._session.flush()

    async def get(self, email: str) -> User | None:
        orm_user = (
            await self._session.execute(
                select(OrmUser).where(OrmUser.email == email)
            )
        ).scalar_one_or_none()

        return _to_domain(orm_user) if orm_user else None

    async def get_by_id(self, user_id: str) -> User | None:
        row = await self._session.get(OrmUser, user_id)
        return _to_domain(row) if row is not None else None


def _to_orm(user: User) -> OrmUser:
    return OrmUser(
        id=user.id,
        email=user.email,
        username=user.username,
        password_hash=user.password_hash,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
    )


def _to_domain(row: OrmUser) -> User:
    return User(
        id=row.id,
        email=row.email,
        username=row.username,
        password_hash=row.password_hash,
        role=row.role,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_login_at=row.last_login_at,
    )
