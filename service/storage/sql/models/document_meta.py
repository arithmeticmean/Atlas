from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    String,
    Text,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from storage.sql.db import Base


class DocumentMeta(Base):
    __tablename__ = "documents_metadata"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
    )

    project_id: Mapped[str] = mapped_column(
        String,
        nullable=False,
        server_default="",
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    source_path: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    mime_type: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    file_size_bytes: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    # Not globally unique: the same bytes may live in more than one project.
    # Dedup is per-project, enforced in DocumentService via a scoped lookup.
    content_hash: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="pending",
        index=True,
    )

    indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
