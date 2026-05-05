"""Application service for documents.

The single intake point for the system. Whatever the origin -- an HTTP upload
or a connector fetching from Drive/a URL/a directory -- a document enters the
same way: its bytes go to the ``DocumentStore``, a metadata row to the
``DocumentMetaStore``, and a job onto the ``JobQueue`` for the background
embedding step. ``store`` does all three in one unit of work, so a document is
never recorded without a job to process it (or vice versa).

Ingestion itself is deliberately elsewhere (``service/worker.py`` ->
``IngestionService``): intake is fast and synchronous, embedding is slow and
happens off the request path.
"""

import uuid
from typing import BinaryIO

from models import DocumentMetadata
from storage.store import DocumentMetaStore, DocumentStore, JobQueue


class DocumentService:
    def __init__(
        self,
        *,
        meta_store: DocumentMetaStore,
        document_store: DocumentStore,
        jobs: JobQueue,
    ) -> None:
        self._meta = meta_store
        self._docs = document_store
        self._jobs = jobs

    async def store(
        self,
        *,
        project_id: str,
        filename: str,
        mime_type: str | None,
        source: BinaryIO,
    ) -> DocumentMetadata:
        """Persist a document's bytes + metadata and queue it for ingestion.

        Returns immediately with ``status="queued"``; the worker embeds it
        later. All three writes share the caller's unit of work.

        Idempotent on content *within a project*: if the project already has a
        document with the same bytes (same ``content_hash``), the existing one
        is returned and no new copy, row or job is created. The same bytes may
        still exist independently in another project.
        """
        document_id = uuid.uuid4().hex
        blob = await self._docs.add(document_id, source)

        existing = await self._meta.get_by_content_hash(
            project_id, blob.content_hash
        )
        if existing is not None:
            # Same bytes already ingested in this project; drop the redundant
            # copy we just wrote and hand back the original.
            await self._docs.delete(document_id)
            return existing

        meta = DocumentMetadata(
            id=document_id,
            project_id=project_id,
            title=filename,
            source_path=blob.path,
            mime_type=mime_type,
            file_size_bytes=blob.size_bytes,
            content_hash=blob.content_hash,
            status="queued",
        )
        await self._meta.add(meta)
        await self._jobs.enqueue(document_id)
        return meta

    async def reingest(
        self, document_id: str, *, project_id: str
    ) -> DocumentMetadata:
        """Re-queue an already-stored document (e.g. to retry a failure).

        Returns the metadata with the ``queued`` transition applied. Raises
        :class:`LookupError` if the document is unknown *or belongs to another
        project* -- callers never learn a foreign document exists.
        """
        meta = await self._meta.get(document_id)
        if meta is None or meta.project_id != project_id:
            raise LookupError(f"document {document_id!r} not found")
        await self._meta.set_status(document_id, "queued")
        await self._jobs.enqueue(document_id)
        meta.status = "queued"
        return meta

    async def get(
        self, document_id: str, *, project_id: str
    ) -> DocumentMetadata | None:
        """Return a project's document metadata, or ``None`` if unknown.

        A document owned by another project reads as ``None`` (not found).
        """
        meta = await self._meta.get(document_id)
        if meta is None or meta.project_id != project_id:
            return None
        return meta

    async def list(self, *, project_id: str) -> list[DocumentMetadata]:
        """Return a project's documents' metadata (newest-indexed first)."""
        return await self._meta.list(project_id)
