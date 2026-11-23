from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, relationship
from sqlalchemy.orm import mapped_column as column

from atlas.models.base import Base, Timestamped, UTCDateTime, new_id

DocumentStatus = Literal["queued", "processing", "indexed", "failed"]


class DocumentTag(Base, kw_only=True, eq=False):
    """One label on one document."""

    __tablename__ = "document_tags"

    document_id: Mapped[str] = column(
        ForeignKey("documents_metadata.id", ondelete="CASCADE"),
        primary_key=True,
        init=False,
    )
    tag: Mapped[str] = column(String(64), primary_key=True, index=True)


class Document(Timestamped, Base, kw_only=True, eq=False):
    """A stored file and its ingestion state, within one project."""

    __tablename__ = "documents_metadata"

    id: Mapped[str] = column(String, primary_key=True, default_factory=new_id)
    project_id: Mapped[str] = column(String, server_default="", index=True)
    title: Mapped[str] = column(String)
    mime_type: Mapped[str | None] = column(String, default=None)
    # The stored file. Set only by DocumentRepository.add, from the bytes it
    # actually stored -- so no document can point at a file that is not
    # there. The column is still named source_path; older rows hold a full
    # path in it, which the file store resolves by its final component.
    file_key: Mapped[str] = column("source_path", Text, init=False)
    file_size_bytes: Mapped[int | None] = column(
        BigInteger, init=False, default=None
    )
    # Not unique: the same bytes may live in more than one project.
    content_hash: Mapped[str | None] = column(String, init=False, default=None)
    status: Mapped[DocumentStatus] = column(
        String, default="queued", index=True
    )
    indexed_at: Mapped[datetime | None] = column(UTCDateTime(), default=None)
    _tag_rows: Mapped[list[DocumentTag]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        init=False,
        default_factory=list,
        repr=False,
    )

    @property
    def tags(self) -> list[str]:
        return sorted(row.tag for row in self._tag_rows)

    def set_tags(self, tags: Iterable[str]) -> None:
        """Keep the rows that stay, so an unchanged tag is not rewritten."""
        wanted = set(tags)
        self._tag_rows[:] = [r for r in self._tag_rows if r.tag in wanted]
        existing = {row.tag for row in self._tag_rows}
        self._tag_rows.extend(
            DocumentTag(tag=tag) for tag in sorted(wanted - existing)
        )
