"""Application service for making a stored document searchable.

Kept separate from ``DocumentService``: uploading (store the file) and
ingesting (index it — slower and failure-prone) are distinct concerns, which
also leaves room to run ingestion in the background later. This service owns
the status transitions ``pending -> indexed`` / ``-> failed`` around the run.

Each status write happens in its own committed unit of work, obtained from an
injected factory. That is deliberate: the ``failed`` marker must survive even
though the ingestion request itself errors out, so it cannot share the
transaction that unwinds on failure.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime

from service.ingest import IngestionPipeline
from service.storage.store import DocumentMetaStore

MetaStoreUoW = Callable[[], AbstractAsyncContextManager[DocumentMetaStore]]


class IngestionService:
    def __init__(
        self,
        *,
        meta_store: MetaStoreUoW,
        pipeline: IngestionPipeline,
    ) -> None:
        self._meta = meta_store
        self._pipeline = pipeline

    async def ingest(self, document_id: str) -> int:
        """Index a document's content; return the number of chunks written."""
        async with self._meta() as store:
            meta = await store.get(document_id)
        if meta is None:
            raise LookupError(f"document {document_id!r} not found")

        async with self._meta() as store:
            await store.set_status(document_id, "processing")

        try:
            chunk_count = await self._pipeline.run(
                document_id=document_id,
                project_id=meta.project_id,
                source_path=meta.source_path,
                mime_type=meta.mime_type,
                filename=meta.title,
            )
        except Exception:
            async with self._meta() as store:
                await store.set_status(document_id, "failed")
            raise

        async with self._meta() as store:
            await store.set_status(
                document_id, "indexed", indexed_at=datetime.now(UTC)
            )
        return chunk_count
