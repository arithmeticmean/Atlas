"""A project's documents.

Every way a document arrives -- an upload, a connector sync -- goes through
``upload``: the bytes and the row are saved together (see
``repository/documents.py``) and a job is queued; the worker indexes it
later (``services/ingestion.py``).
"""

import asyncio
import logging
from collections.abc import Iterable
from contextlib import AbstractAsyncContextManager
from typing import BinaryIO

from langchain_core.documents import Document as Chunk

from atlas.core.parsing.pipeline import FileInput, ensure_supported
from atlas.models.document import Document, DocumentStatus
from atlas.repository.base import Paged, PageRequest
from atlas.repository.uow import UnitOfWork, UnitOfWorkFactory
from atlas.services.access import Caller, load_project
from atlas.services.ai import AIRuntime
from atlas.services.errors import FileTooLarge, InvalidInput, NotFound
from atlas.services.settings import SettingsService

logger = logging.getLogger(__name__)

_MAX_TAGS = 20
_MAX_TAG_LENGTH = 64


async def _document(
    uow: UnitOfWork, caller: Caller, project_id: str, document_id: str
) -> Document:
    await load_project(uow, caller, project_id)
    document = await uow.documents.get_in_project(project_id, document_id)
    if document is None:
        raise NotFound("document not found", code="document_not_found")
    return document


def _clean_tags(tags: Iterable[str]) -> set[str]:
    cleaned = {tag.strip().lower() for tag in tags} - {""}
    if len(cleaned) > _MAX_TAGS:
        raise InvalidInput(f"a document can have {_MAX_TAGS} tags at most")
    if any(len(tag) > _MAX_TAG_LENGTH for tag in cleaned):
        raise InvalidInput(f"tags are limited to {_MAX_TAG_LENGTH} characters")
    return cleaned


class DocumentService:
    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        ai: AIRuntime,
        settings: SettingsService,
    ) -> None:
        self._uow = uow
        self._ai = ai
        self._settings = settings

    async def upload(
        self,
        caller: Caller,
        project_id: str,
        *,
        filename: str,
        mime_type: str | None,
        content: BinaryIO,
        title: str | None = None,
        tags: Iterable[str] = (),
    ) -> tuple[Document, bool]:
        """Store a file and queue it for indexing. Returns the document and
        whether it is new: identical bytes already in the project return the
        existing document instead."""
        cleaned_tags = _clean_tags(tags)
        limit = self._settings.current.max_upload_mb * 1024 * 1024
        if content.seek(0, 2) > limit:
            raise FileTooLarge(f"files are limited to {limit} bytes")
        content.seek(0)
        await asyncio.to_thread(
            ensure_supported,
            FileInput(content, filename=filename, mime_type=mime_type),
        )
        async with self._uow() as uow:
            await load_project(uow, caller, project_id)
            new = Document(
                project_id=project_id,
                title=title or filename,
                mime_type=mime_type,
            )
            document = await uow.documents.add(new, content=content)
            created = document is new
            if created:
                document.set_tags(cleaned_tags)
                await uow.jobs.enqueue(document.id)
        return document, created

    async def list_documents(
        self,
        caller: Caller,
        project_id: str,
        page: PageRequest,
        *,
        q: str | None = None,
        status: DocumentStatus | None = None,
        tag: str | None = None,
    ) -> Paged[Document]:
        async with self._uow() as uow:
            await load_project(uow, caller, project_id)
            return await uow.documents.page_for_project(
                project_id,
                page,
                q=q,
                status=status,
                tag=tag.strip().lower() if tag else None,
            )

    async def get(
        self, caller: Caller, project_id: str, document_id: str
    ) -> Document:
        async with self._uow() as uow:
            return await _document(uow, caller, project_id, document_id)

    async def update(
        self,
        caller: Caller,
        project_id: str,
        document_id: str,
        *,
        title: str | None = None,
        tags: Iterable[str] | None = None,
    ) -> Document:
        """Fields left as ``None`` stay as they are."""
        cleaned_tags = None if tags is None else _clean_tags(tags)
        async with self._uow() as uow:
            document = await _document(uow, caller, project_id, document_id)
            if title is not None:
                document.title = title
            if cleaned_tags is not None:
                document.set_tags(cleaned_tags)
        return document

    async def delete(
        self, caller: Caller, project_id: str, document_id: str
    ) -> None:
        async with self._uow() as uow:
            document = await _document(uow, caller, project_id, document_id)
            await uow.documents.delete(document)
            await uow.commit()
            await uow.documents.delete_file(document)
        try:
            await self._ai.remove_document(document_id)
        except Exception:
            logger.warning(
                "could not remove the chunks of document %s",
                document_id,
                exc_info=True,
            )

    async def open_content(
        self, caller: Caller, project_id: str, document_id: str
    ) -> tuple[Document, AbstractAsyncContextManager[BinaryIO]]:
        """The document (for its name and type) and its bytes. The stream
        does not depend on the database, so it can be read after this
        returns."""
        async with self._uow() as uow:
            document = await _document(uow, caller, project_id, document_id)
            return document, uow.documents.open(document)

    async def list_chunks(
        self, caller: Caller, project_id: str, document_id: str
    ) -> list[Chunk]:
        async with self._uow() as uow:
            await _document(uow, caller, project_id, document_id)
        return await self._ai.chunks(document_id)

    async def reindex(
        self, caller: Caller, project_id: str, document_id: str
    ) -> Document:
        async with self._uow() as uow:
            document = await _document(uow, caller, project_id, document_id)
            document.status = "queued"
            await uow.jobs.enqueue(document.id)
        return document

    async def list_tags(
        self, caller: Caller, project_id: str
    ) -> list[tuple[str, int]]:
        """Every tag in the project, with how many documents carry it."""
        async with self._uow() as uow:
            await load_project(uow, caller, project_id)
            return await uow.documents.tag_counts(project_id)
