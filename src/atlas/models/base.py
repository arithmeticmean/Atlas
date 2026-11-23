"""The declarative base every persisted entity derives from.

An entity *is* its mapping: one class serves as the domain object, the
constructor, the typed query target and the table Alembic reads. Types that
have no table stay plain dataclasses next to the service that produces them.

Entities carry no persistence behaviour -- no ``save()``, no queries. The
session tracks what changed and the unit of work commits it, so changing an
attribute of a loaded entity is how it is updated. The corollary: never
modify a loaded entity just to shape a response, or that change is written.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Dialect, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass
from sqlalchemy.orm import mapped_column as column


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


class UTCDateTime(TypeDecorator[datetime]):
    """A timestamp that is always timezone-aware UTC in Python.

    SQLite stores no timezone, so a plain ``DateTime(timezone=True)`` reads
    back naive there while a fresh value (or Postgres) is aware -- and
    comparing the two raises. Same column in the database either way.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is not None and value.tzinfo is not None:
            return value.astimezone(UTC)
        return value

    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


# Every entity class declares ``kw_only=True, eq=False`` itself: neither is
# inherited from a base class, and type checkers only read them spelled out.
# kw_only: fields with defaults (ids, timestamps) can sit anywhere.
# eq=False: an entity equals only itself, which is also what the session's
# identity map guarantees (one object per row). Field-by-field equality
# would call two different rows with the same values equal.
class Base(MappedAsDataclass, DeclarativeBase):
    pass


class Timestamped(MappedAsDataclass, kw_only=True):
    """Set in Python rather than by a server default, so no schema change
    is needed and SQLite and Postgres store the same thing."""

    created_at: Mapped[datetime | None] = column(
        UTCDateTime(), default_factory=utcnow, init=False
    )
    updated_at: Mapped[datetime | None] = column(
        UTCDateTime(),
        default_factory=utcnow,
        onupdate=utcnow,
        init=False,
    )
