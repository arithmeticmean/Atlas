"""Documents, together with their stored bytes.

``add`` saves the file and then the row; ``open`` reads the file. Deleting
is two steps in this order, so the file is never lost while its row could
still come back::

    await uow.documents.delete(doc)       # the row
    await uow.commit()
    await uow.documents.delete_file(doc)  # then the file
"""

from collections.abc import Iterable
from contextlib import AbstractAsyncContextManager
from datetime import timedelta
from typing import BinaryIO

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from atlas.models.base import utcnow
from atlas.models.document import Document, DocumentTag
from atlas.models.job import IngestionJob
from atlas.repository.base import Paged, PageRequest, Repository
from atlas.repository.files import FileStore


class DocumentRepository(Repository[Document]):
    model = Document

    def __init__(self, session: AsyncSession, files: FileStore) -> None:
        super().__init__(session)
        self._files = files

    async def add(self, document: Document, content: BinaryIO) -> Document:
        """Store ``document`` with ``content`` as its bytes.

        Returns the document that ends up stored: ``document`` itself, or --
        when its project already holds identical bytes -- that existing
        document, and nothing new is kept. ``result is document`` tells which.
        """
        stored = await self._files.put(document.id, content)
        existing = await self.by_content_hash(
            document.project_id, stored.content_hash
        )
        if existing is not None:
            await self._files.delete(document.id)  # nothing refers to it
            return existing
        document.file_key = stored.key
        document.content_hash = stored.content_hash
        document.file_size_bytes = stored.size_bytes
        return await self._insert(document)

    async def delete(self, entity: Document) -> None:
        """The row and its queued jobs. Delete the file with
        :meth:`delete_file` after committing."""
        await self.session.execute(
            delete(IngestionJob).where(IngestionJob.document_id == entity.id)
        )
        await super().delete(entity)

    async def delete_file(self, document: Document) -> None:
        """Only after the row's deletion is committed (see the module
        docstring)."""
        await self._files.delete(document.file_key)

    def open(
        self, document: Document
    ) -> AbstractAsyncContextManager[BinaryIO]:
        """The document's bytes as a seekable stream, for parsing."""
        return self._files.open(document.file_key)

    async def get_in_project(
        self, project_id: str, document_id: str
    ) -> Document | None:
        """Scoped by project in the query itself: a document in another
        project is indistinguishable from one that does not exist."""
        rows = await self.session.scalars(
            select(Document).where(
                Document.id == document_id, Document.project_id == project_id
            )
        )
        return rows.first()

    async def by_content_hash(
        self, project_id: str, content_hash: str
    ) -> Document | None:
        """Deduplication is per project: the same bytes may live in two."""
        rows = await self.session.scalars(
            select(Document)
            .where(
                Document.project_id == project_id,
                Document.content_hash == content_hash,
            )
            .limit(1)
        )
        return rows.first()

    async def list_for_project(self, project_id: str) -> list[Document]:
        rows = await self.session.scalars(
            select(Document).where(Document.project_id == project_id)
        )
        return list(rows)

    async def page_for_project(
        self,
        project_id: str,
        page: PageRequest,
        *,
        q: str | None = None,
        status: str | None = None,
        tag: str | None = None,
    ) -> Paged[Document]:
        query = select(Document).where(Document.project_id == project_id)
        if q:
            query = query.where(Document.title.icontains(q, autoescape=True))
        if status:
            query = query.where(Document.status == status)
        if tag:
            tagged = select(DocumentTag.document_id).where(
                DocumentTag.tag == tag
            )
            query = query.where(Document.id.in_(tagged))
        return await self._page(
            query.order_by(Document.created_at.desc(), Document.id), page
        )

    async def tag_counts(self, project_id: str) -> list[tuple[str, int]]:
        """Every tag in a project and how many documents carry it."""
        rows = await self.session.execute(
            select(DocumentTag.tag, func.count())
            .join(Document, Document.id == DocumentTag.document_id)
            .where(Document.project_id == project_id)
            .group_by(DocumentTag.tag)
            .order_by(DocumentTag.tag)
        )
        return [(tag, count) for tag, count in rows.tuples()]

    async def titles(self, document_ids: Iterable[str]) -> dict[str, str]:
        rows = await self.session.execute(
            select(Document.id, Document.title).where(
                Document.id.in_(set(document_ids))
            )
        )
        return dict(rows.tuples().all())

    async def requeue_all(self) -> list[str]:
        """Mark every document queued in one statement (a full reindex);
        returns their ids so the caller can enqueue a job for each."""
        ids = list(await self.session.scalars(select(Document.id)))
        await self.session.execute(update(Document).values(status="queued"))
        return ids

    async def sweep_files(
        self, *, older_than: timedelta = timedelta(hours=1)
    ) -> int:
        """Delete stored files no document refers to: left by a request
        that failed after saving its file, or one that never got to delete
        it. ``older_than`` keeps clear of uploads still in progress."""
        keys = await self.session.scalars(select(Document.file_key))
        return await self._files.sweep(keep=keys, before=utcnow() - older_than)
