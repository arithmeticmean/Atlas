"""Chunk index port: where passages are stored and retrieved.

Replaces the previous ``VectorStore`` port, which was an alias for langchain's
base class. That alias made hybrid retrieval unreachable: langchain's LanceDB
wrapper embeds the query itself and passes a single value down, while hybrid
needs the query vector *and* its raw text. Owning the port lets the adapter
speak to LanceDB natively and keeps langchain to the two places it earns its
keep -- loaders and embeddings.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Literal

from service.models.chunk import Chunk, ScoredChunk

SearchMode = Literal["hybrid", "vector", "fts"]


class ChunkIndex(ABC):
    @abstractmethod
    async def add(self, chunks: Sequence[Chunk]) -> None:
        """Insert chunks. Empty input is a no-op."""

    @abstractmethod
    async def search(
        self,
        *,
        project_id: str,
        query_text: str,
        query_vector: Sequence[float],
        k: int,
        mode: SearchMode = "hybrid",
    ) -> list[ScoredChunk]:
        """The ``k`` most relevant chunks within one project, best first.

        ``project_id`` must be applied as a **pre**-filter: filtering after the
        fact silently returns fewer than ``k`` rows, and it is the only thing
        separating one project's passages from another's in a shared table.
        """

    @abstractmethod
    async def delete_document(self, document_id: str) -> None:
        """Remove every chunk of one document (no error if absent)."""

    @abstractmethod
    async def count(self) -> int:
        """Total rows, or 0 when the index does not exist yet."""

    @abstractmethod
    async def drop(self) -> None:
        """Delete the whole index, for a re-embed from scratch.

        Belongs on the port rather than being done to the storage directory
        from outside: the adapter holds the live connection, and a second
        client mutating the same dataset can strand the manifest.
        """
