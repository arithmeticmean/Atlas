"""The ingestion pipeline: load -> split -> embed -> index.

The embed step is now explicit. It used to be implicit inside langchain's
vector store, which embedded on ``add`` and hid the vectors; the chunk index
takes ``Chunk`` objects that already carry their embedding, so the same model
is demonstrably used for indexing and for querying, and hybrid retrieval can
hand LanceDB the query vector separately from the query text.
"""

import asyncio
import logging

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import TextSplitter

from service.models.chunk import Chunk
from service.storage.store.chunk_index import ChunkIndex

from .loaders import resolve_loader
from .splitters import build_splitter

logger = logging.getLogger(__name__)


class IngestionPipeline:
    def __init__(
        self,
        *,
        index: ChunkIndex,
        embeddings: Embeddings,
        splitter: TextSplitter | None = None,
    ) -> None:
        self._index = index
        self._embeddings = embeddings
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
        """Load, split, embed and index one stored document.

        Returns the number of chunks written. Re-ingesting replaces: every
        chunk of this document is deleted first, so a document that shrank does
        not leave orphaned passages behind to be retrieved later.
        """
        # Loading and splitting are blocking (and loader resolution sniffs the
        # file), so keep that whole part off the event loop.
        docs = await asyncio.to_thread(
            self._load_and_split,
            source_path=source_path,
            mime_type=mime_type,
            filename=filename,
        )
        texts = [d.page_content for d in docs if d.page_content.strip()]

        await self._index.delete_document(document_id)
        if not texts:
            logger.info("document %s produced no text to index", document_id)
            return 0

        vectors = await self._embeddings.aembed_documents(texts)
        if len(vectors) != len(texts):
            raise RuntimeError(
                f"embedding returned {len(vectors)} vectors for "
                f"{len(texts)} chunks"
            )

        await self._index.add(
            [
                Chunk(
                    document_id=document_id,
                    project_id=project_id,
                    chunk_index=i,
                    text=text,
                    vector=vector,
                )
                for i, (text, vector) in enumerate(
                    zip(texts, vectors, strict=True)
                )
            ]
        )
        return len(texts)

    def _load_and_split(
        self,
        *,
        source_path: str,
        mime_type: str | None,
        filename: str | None,
    ) -> list[Document]:
        loader = resolve_loader(source_path, mime_type, filename=filename)
        return self._splitter.split_documents(loader.load())
