"""The RAG ingestion pipeline: load -> split -> index.

Pure processing. It knows a blob path and a mime type on the way in, and writes
chunks into a vector store on the way out. It has no knowledge of the metadata
store, the database, or the web layer — those are the orchestrator's concern.

With langchain the embed step is not separate: the injected ``VectorStore``
(langchain's ``LanceDB``) holds the ``Embeddings`` and embeds on ``add``.
"""

import asyncio

from langchain_core.documents import Document
from langchain_text_splitters import TextSplitter

from storage.store import VectorStore

from .loaders import resolve_loader
from .splitters import build_splitter


class IngestionPipeline:
    def __init__(
        self,
        *,
        vector_store: VectorStore,
        splitter: TextSplitter | None = None,
    ) -> None:
        self._vector = vector_store
        self._splitter = splitter or build_splitter()

    async def run(
        self,
        *,
        document_id: str,
        project_id: str,
        source_path: str,
        mime_type: str | None,
        filename: str | None = None,
    ) -> int:
        """Load, split, and index a stored document; return the chunk count.

        ``project_id`` is stamped on every chunk's metadata so search can be
        filtered to one project (chunks share a single vector table).
        """
        # Loading and splitting are sync/blocking (and loader resolution may
        # sniff the file); keep the whole CPU/IO-bound part off the loop.
        docs = await asyncio.to_thread(
            self._load_and_split,
            source_path=source_path,
            mime_type=mime_type,
            filename=filename,
        )

        for index, chunk in enumerate(docs):
            chunk.metadata["document_id"] = document_id
            chunk.metadata["project_id"] = project_id
            chunk.metadata["chunk_index"] = index

        if docs:
            await self._vector.aadd_documents(docs)
        return len(docs)

    def _load_and_split(
        self,
        *,
        source_path: str,
        mime_type: str | None,
        filename: str | None,
    ) -> list[Document]:
        loader = resolve_loader(source_path, mime_type, filename=filename)
        return self._splitter.split_documents(loader.load())
