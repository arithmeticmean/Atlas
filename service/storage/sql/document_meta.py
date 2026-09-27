"""SQLAlchemy adapter for the DocumentMetaStore port.

The only place that knows both the ``DocumentMetadata`` domain object and the
ORM ``DocumentMeta`` table; it maps between them so the port stays free of any
SQLAlchemy detail.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from service.models import DocumentMetadata
from service.storage.sql.models import DocumentMeta
from service.storage.store.document_meta import DocumentMetaStore


class SqlDocumentMetaStore(DocumentMetaStore):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, document: DocumentMetadata) -> None:
        self._session.add(_to_orm(document))
        await self._session.flush()

    async def get(self, document_id: str) -> DocumentMetadata | None:
        row = await self._session.get(DocumentMeta, document_id)
        return _to_domain(row) if row is not None else None

    async def get_by_content_hash(
        self, project_id: str, content_hash: str
    ) -> DocumentMetadata | None:
        row = (
            await self._session.execute(
                select(DocumentMeta).where(
                    DocumentMeta.project_id == project_id,
                    DocumentMeta.content_hash == content_hash,
                )
            )
        ).scalar_one_or_none()
        return _to_domain(row) if row is not None else None

    async def all_ids(self) -> list[str]:
        rows = (
            await self._session.execute(select(DocumentMeta.id))
        ).scalars().all()
        return list(rows)

    async def list(self, project_id: str) -> list[DocumentMetadata]:
        rows = (
            await self._session.execute(
                select(DocumentMeta)
                .where(DocumentMeta.project_id == project_id)
                .order_by(DocumentMeta.indexed_at.desc().nullslast())
            )
        ).scalars().all()
        return [_to_domain(row) for row in rows]

    async def set_status(
        self,
        document_id: str,
        status: str,
        *,
        indexed_at: datetime | None = None,
    ) -> None:
        row = await self._session.get(DocumentMeta, document_id)
        if row is None:
            raise LookupError(f"document {document_id!r} not found")
        row.status = status
        if indexed_at is not None:
            row.indexed_at = indexed_at
        await self._session.flush()


def _to_orm(meta: DocumentMetadata) -> DocumentMeta:
    return DocumentMeta(
        id=meta.id,
        project_id=meta.project_id,
        title=meta.title,
        source_path=meta.source_path,
        mime_type=meta.mime_type,
        file_size_bytes=meta.file_size_bytes,
        content_hash=meta.content_hash,
        status=meta.status,
        indexed_at=meta.indexed_at,
    )


def _to_domain(row: DocumentMeta) -> DocumentMetadata:
    return DocumentMetadata(
        id=row.id,
        project_id=row.project_id,
        title=row.title,
        source_path=row.source_path,
        mime_type=row.mime_type,
        file_size_bytes=row.file_size_bytes,
        content_hash=row.content_hash,
        status=row.status,
        indexed_at=row.indexed_at,
    )
