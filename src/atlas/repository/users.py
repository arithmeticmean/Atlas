from sqlalchemy import Select, or_, select

from atlas.models.user import User
from atlas.repository.base import CrudRepository, Paged, PageRequest


class UserRepository(CrudRepository[User]):
    model = User

    async def by_email(self, email: str) -> User | None:
        rows = await self.session.scalars(
            select(User).where(User.email == email)
        )
        return rows.first()

    async def page(
        self,
        page: PageRequest,
        *,
        q: str | None = None,
        role: str | None = None,
        status: str | None = None,
    ) -> Paged[User]:
        query = _matching(select(User), q)
        if role:
            query = query.where(User.role == role)
        if status:
            query = query.where(User.status == status)
        return await self._page(query.order_by(User.email), page)

    async def search_active(
        self, q: str, *, limit: int, among: set[str] | None = None
    ) -> list[User]:
        """Active accounts matching ``q``, optionally only within ``among``."""
        query = _matching(select(User), q).where(User.status == "active")
        if among is not None:
            query = query.where(User.id.in_(among))
        rows = await self.session.scalars(
            query.order_by(User.email).limit(limit)
        )
        return list(rows)

    async def by_username(self, username: str) -> User | None:
        rows = await self.session.scalars(
            select(User).where(User.username == username)
        )
        return rows.first()

    async def owner(self) -> User | None:
        rows = await self.session.scalars(
            select(User).where(User.role == "owner")
        )
        return rows.first()


def _matching(
    query: Select[tuple[User]], q: str | None
) -> Select[tuple[User]]:
    if not q:
        return query
    return query.where(
        or_(
            User.email.icontains(q, autoescape=True),
            User.username.icontains(q, autoescape=True),
        )
    )
