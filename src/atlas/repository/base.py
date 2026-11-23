"""What every repository does the same way.

A repository is a named set of queries over one entity. The generic part --
fetch by primary key, insert, delete -- is written once here; subclasses add
only the queries that have a name (``by_email``, ``list_for_project``).
Changing an entity needs no method at all: the session tracks it.

``Repository`` has no public ``add`` because not every entity can be added on
its own: a document only together with its file. ``CrudRepository`` is the
usual case and exposes it.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from sqlalchemy import Select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from atlas.models.base import Base

M = TypeVar("M", bound=Base)
T = TypeVar("T")
U = TypeVar("U")


@dataclass(frozen=True, slots=True)
class PageRequest:
    offset: int = 0
    limit: int = 25


@dataclass(frozen=True, slots=True)
class Paged(Generic[T]):
    """One page of results, and where the next one starts."""

    items: list[T]
    next_offset: int | None

    @classmethod
    def of(cls, rows: Sequence[T], page: PageRequest) -> "Paged[T]":
        """From up to ``limit + 1`` rows: the extra one proves there's more."""
        has_more = len(rows) > page.limit
        return cls(
            items=list(rows[: page.limit]),
            next_offset=page.offset + page.limit if has_more else None,
        )

    @classmethod
    def slice(cls, items: Sequence[T], page: PageRequest) -> "Paged[T]":
        """For data that does not come from SQL."""
        return cls.of(items[page.offset : page.offset + page.limit + 1], page)

    def map(self, convert: Callable[[T], U]) -> "Paged[U]":
        return Paged([convert(item) for item in self.items], self.next_offset)


class Conflict(Exception):
    """A write broke a uniqueness or integrity constraint (a taken email, a
    duplicate membership). The unit of work must then be rolled back."""


class Repository(Generic[M]):
    model: type[M]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, ident: object) -> M | None:
        """By primary key; a tuple for a composite key."""
        return await self.session.get(self.model, ident)

    async def delete(self, entity: M) -> None:
        await self.session.delete(entity)
        await self.session.flush()

    async def _page(
        self, query: Select[tuple[T]], page: PageRequest
    ) -> Paged[T]:
        rows = await self.session.scalars(
            query.offset(page.offset).limit(page.limit + 1)
        )
        return Paged.of(list(rows), page)

    async def _page_rows(
        self, query: Select[Any], page: PageRequest
    ) -> Paged[Any]:
        """Like ``_page``, for queries selecting several columns."""
        rows = await self.session.execute(
            query.offset(page.offset).limit(page.limit + 1)
        )
        return Paged.of([tuple(row) for row in rows], page)

    async def _insert(self, entity: M) -> M:
        """Insert now rather than at commit, so a constraint violation is
        raised here, where the caller can still say what it means."""
        self.session.add(entity)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise Conflict(str(exc.orig)) from exc
        return entity


class CrudRepository(Repository[M]):
    async def add(self, entity: M) -> M:
        return await self._insert(entity)
