"""Make a stored document searchable.

Each status change is committed on its own, so ``failed`` is saved even
though the work it describes raised.
"""

from atlas.models.base import utcnow
from atlas.repository.uow import UnitOfWorkFactory
from atlas.services.ai import AIRuntime


class IngestionService:
    def __init__(self, *, uow: UnitOfWorkFactory, ai: AIRuntime) -> None:
        self._uow = uow
        self._ai = ai

    async def ingest(self, document_id: str) -> int:
        """Index one document; returns how many chunks were written."""
        async with self._uow() as uow:
            document = await uow.documents.get(document_id)
            if document is None:
                raise LookupError(f"document {document_id!r} not found")
            document.status = "processing"
            reader = uow.documents.open(document)
        try:
            async with reader as content:
                chunks = await self._ai.index(document, content)
        except Exception:
            await self._set_status(document_id, failed=True)
            raise
        await self._set_status(document_id, failed=False)
        return chunks

    async def _set_status(self, document_id: str, *, failed: bool) -> None:
        async with self._uow() as uow:
            document = await uow.documents.get(document_id)
            if document is None:
                return  # deleted while it was being indexed
            if failed:
                document.status = "failed"
            else:
                document.status = "indexed"
                document.indexed_at = utcnow()
