"""Document metadata store port."""

from abc import ABC, abstractmethod
from datetime import datetime

from service.models import DocumentMetadata


class DocumentMetaStore(ABC):
    @abstractmethod
    async def add(self, document: DocumentMetadata) -> None:
        """Insert a new document-metadata row."""

    @abstractmethod
    async def get(self, document_id: str) -> DocumentMetadata | None:
        """Return the document, or ``None`` if it does not exist."""

    @abstractmethod
    async def get_by_content_hash(
        self, project_id: str, content_hash: str
    ) -> DocumentMetadata | None:
        """Return the project's document with this content hash, if any.

        Backs content-dedup, scoped to a project: identical bytes map to a
        single document *within* a project, but may exist across projects.
        """

    @abstractmethod
    async def all_ids(self) -> list[str]:
        """Return every document id (used to re-enqueue on reindex).

        Global on purpose: a reindex re-embeds the whole corpus regardless of
        project, so this is not project-scoped.
        """

    @abstractmethod
    async def list(self, project_id: str) -> list[DocumentMetadata]:
        """Return one project's documents' metadata (for the library view)."""

    @abstractmethod
    async def set_status(
        self,
        document_id: str,
        status: str,
        *,
        indexed_at: datetime | None = None,
    ) -> None:
        """Update a document's status, and its indexed time when given."""
