"""Application service for semantic search over ingested chunks.

Thin wrapper over the vector store: embed the query (with the same model the
corpus was indexed under -- enforced by the embedding lock file) and return the
nearest chunks. The heavy lifting lives in the injected ``VectorStore``; this
service just shapes the result into a domain type the web layer can render.
"""

from dataclasses import dataclass

from storage.store import VectorStore


@dataclass(slots=True)
class SearchHit:
    document_id: str | None
    chunk_index: int | None
    text: str
    score: float


class SearchService:
    def __init__(self, *, vector_store: VectorStore) -> None:
        self._vector = vector_store

    async def search(
        self, *, query: str, k: int, project_id: str
    ) -> list[SearchHit]:
        """Return the ``k`` chunks nearest to ``query`` within one project.

        ``score`` is the store's raw distance (smaller = closer). An index with
        nothing ingested yet returns no hits. Results are restricted to
        ``project_id`` via a pre-filter on the chunk metadata, so one project
        never sees another's chunks even though they share a vector table.
        """
        if not self._has_index():
            return []
        results = await self._vector.asimilarity_search_with_score(
            query,
            k=k,
            filter=f"metadata.project_id = '{project_id}'",
            prefilter=True,
        )
        return [
            SearchHit(
                document_id=doc.metadata.get("document_id"),
                chunk_index=doc.metadata.get("chunk_index"),
                text=doc.page_content,
                score=float(score),
            )
            for doc, score in results
        ]

    def _has_index(self) -> bool:
        # LanceDB creates the table only on the first successful ingest;
        # querying before then would dereference a missing table. Other
        # backends have no such method, so assume they are queryable.
        get_table = getattr(self._vector, "get_table", None)
        if get_table is None:
            return True
        try:
            return get_table() is not None
        except Exception:
            return False
