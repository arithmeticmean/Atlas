"""Retrieval: embed the query, search the chunk index, optionally rerank.

The pipeline is deliberately explicit about the two independent decisions a
caller makes:

* **mode** -- how candidates are found. ``hybrid`` runs dense and full-text
  retrieval and fuses them with reciprocal rank fusion, which is what lets an
  exact term win when the embedding is unhelpful and vice versa. ``vector`` and
  ``fts`` isolate one leg, which is mostly useful for seeing what each
  contributes.
* **rerank** -- whether a model then reads the candidates and reorders them.
  This costs one extra call, so it is on for answering (quality matters, the
  answer already costs a call) and off by default for raw search (a lookup
  should be fast).

When reranking is on the index is asked for more candidates than were
requested, since reranking can only reorder what it is given.
"""

import logging
from dataclasses import dataclass

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from service.core.rerank import rerank as rerank_candidates
from service.storage.store.chunk_index import ChunkIndex, SearchMode

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SearchHit:
    document_id: str | None
    chunk_index: int | None
    text: str
    # Relevance: higher is better, whatever the mode. See ScoredChunk.
    score: float


class SearchService:
    def __init__(
        self,
        *,
        index: ChunkIndex,
        embeddings: Embeddings,
        chat_model: BaseChatModel | None = None,
        mode: SearchMode = "hybrid",
        rerank: bool = False,
        rerank_candidates: int = 20,
    ) -> None:
        self._index = index
        self._embeddings = embeddings
        self._chat_model = chat_model
        self._mode = mode
        self._rerank = rerank
        self._rerank_candidates = rerank_candidates

    async def search(
        self,
        *,
        query: str,
        k: int,
        project_id: str,
        mode: SearchMode | None = None,
        rerank: bool | None = None,
    ) -> list[SearchHit]:
        """The ``k`` most relevant chunks for ``query`` within one project."""
        chosen_mode = mode or self._mode
        do_rerank = self._rerank if rerank is None else rerank
        # Reranking can only reorder what it is handed, so widen the net first.
        fetch = max(k, self._rerank_candidates) if do_rerank else k

        # The full-text leg needs no embedding, so skip the call entirely.
        vector: list[float] = []
        if chosen_mode != "fts":
            vector = await self._embeddings.aembed_query(query)

        found = await self._index.search(
            project_id=project_id,
            query_text=query,
            query_vector=vector,
            k=fetch,
            mode=chosen_mode,
        )

        if do_rerank and found:
            if self._chat_model is None:
                logger.warning(
                    "rerank requested but no chat model is wired; "
                    "keeping retrieval order"
                )
            else:
                found = await rerank_candidates(
                    chat_model=self._chat_model,
                    query=query,
                    candidates=found,
                    k=k,
                )

        return [
            SearchHit(
                document_id=s.chunk.document_id,
                chunk_index=s.chunk.chunk_index,
                text=s.chunk.text,
                score=s.score,
            )
            for s in found[:k]
        ]
