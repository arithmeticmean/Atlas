"""The vector store: LangChain's LanceDB, configured safely for Atlas.

LangChain's object does the work. These helpers only fix what its defaults
get wrong for a shared, multi-project table:

* ``mode="append"``: the default overwrites the table on every add;
* an explicit empty table: searching before the first add otherwise crashes;
* ``prefilter=True``: the default filters after searching, so a small project
  next to a large one gets no results;
* ``metrics="cosine"`` on each search: ``distance="cosine"`` alone only changes
  how scores are computed afterwards, while the search itself still uses L2.

Deleting uses LangChain's API directly::

    await store.adelete(filter=document_filter(document_id))
    await store.adelete(filter=project_filter(project_id))
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterable
from pathlib import Path
from typing import Any

import lancedb  # type: ignore[import-untyped]
import pyarrow as pa
from langchain_community.vectorstores import LanceDB
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStoreRetriever

from atlas.config import Settings

__all__ = [
    "build_vector_store",
    "chunk_count",
    "confirm_embedding_model",
    "document_chunks",
    "document_filter",
    "index_document",
    "project_filter",
    "project_retriever",
    "search",
]

logger = logging.getLogger(__name__)

_MODEL_FILE = "embedding_model.json"


def build_vector_store(
    *, settings: Settings, embeddings: Embeddings
) -> tuple[LanceDB, bool]:
    """The store, and whether every document must be indexed again.

    Vectors from different models cannot be compared, so when the configured
    embedding model is not the one recorded, the table is emptied and the
    second value is ``True``. Queue every document, then call
    :func:`confirm_embedding_model`; a crash in between simply repeats this.

    Calls the embedding model only when a table has to be created, so an
    existing index stays usable (for deleting) while the provider is down. If
    that call fails nothing is emptied. Blocking: use ``asyncio.to_thread``.
    """
    connection = lancedb.connect(settings.vector_path)
    needs_reindex = _recorded_model(settings) != _configured_model(
        settings
    ) or not _has_table(connection, settings.vector_table)
    if needs_reindex:
        connection.create_table(
            settings.vector_table,
            schema=_schema(len(embeddings.embed_query("dimension probe"))),
            mode="overwrite",
        )
    store = LanceDB(
        relevance_score_fn=_relevance,
        connection=connection,
        embedding=embeddings,
        table_name=settings.vector_table,
        mode="append",
        distance="cosine",
    )
    return store, needs_reindex


def confirm_embedding_model(*, settings: Settings) -> None:
    """Record the configured model, once every document has been queued."""
    path = _model_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_configured_model(settings)))


async def index_document(
    store: LanceDB,
    *,
    project_id: str,
    document_id: str,
    batches: AsyncIterable[list[Document]],
) -> int:
    """Replace a document's chunks; returns how many were stored. If anything
    fails, none of its chunks stay searchable."""
    where = document_filter(document_id)
    await store.adelete(filter=where)
    count = 0
    try:
        async for batch in batches:
            ids = [f"{document_id}:{count + n}" for n in range(len(batch))]
            for number, chunk in enumerate(batch, start=count):
                chunk.metadata |= {
                    "project_id": project_id,
                    "document_id": document_id,
                    "chunk_index": number,
                }
            await store.aadd_documents(batch, ids=ids)
            count += len(batch)
    except Exception:
        await store.adelete(filter=where)
        raise
    await asyncio.to_thread(_compact, store)
    return count


def _compact(store: LanceDB) -> None:
    """Merge the small files each batch wrote, so search stays fast as
    documents add up. Only an optimisation: failing here loses nothing."""
    try:
        store.get_table().optimize()
    except Exception:
        logger.warning("could not compact the vector index", exc_info=True)


def _relevance(cosine_distance: float) -> float:
    """Cosine distance (0 to 2) as 1 (same) to 0 (opposite). LangChain logs
    the matched text whenever a score falls outside that range."""
    return 1 - cosine_distance / 2


async def search(
    store: LanceDB, *, project_id: str, query: str, k: int = 5
) -> list[tuple[Document, float]]:
    """The ``k`` most relevant chunks in one project, best first, each with a
    relevance score where higher is better."""
    return await store.asimilarity_search_with_relevance_scores(
        query, k=k, **_search_options(project_id)
    )


def project_retriever(
    store: LanceDB, *, project_id: str, k: int = 5
) -> VectorStoreRetriever:
    """A LangChain retriever that can only see one project, for LCEL."""
    return store.as_retriever(
        search_kwargs={"k": k, **_search_options(project_id)}
    )


async def document_chunks(store: LanceDB, document_id: str) -> list[Document]:
    """A document's stored chunks, in order."""

    def read() -> list[Document]:
        table = store.get_table()
        where = document_filter(document_id)
        count = table.count_rows(where)
        if not count:
            return []
        rows = (
            table.search()
            .where(where)
            .select(["id", "text", "metadata"])
            .limit(count)
            .to_list()
        )
        rows.sort(key=lambda row: row["metadata"]["chunk_index"])
        return [
            Document(
                id=row["id"],
                page_content=row["text"],
                metadata=row["metadata"],
            )
            for row in rows
        ]

    return await asyncio.to_thread(read)


async def chunk_count(store: LanceDB) -> int:
    """Chunks stored across all projects."""
    count = await asyncio.to_thread(store.get_table().count_rows)
    return int(count)


def project_filter(project_id: str) -> str:
    """The filter selecting one project's chunks."""
    return _equals("project_id", project_id)


def document_filter(document_id: str) -> str:
    """The filter selecting one document's chunks."""
    return _equals("document_id", document_id)


def _search_options(project_id: str) -> dict[str, Any]:
    return {
        "filter": project_filter(project_id),
        "prefilter": True,
        "metrics": "cosine",
    }


def _equals(field: str, value: str) -> str:
    escaped = value.replace("'", "''")
    return f"metadata.{field} = '{escaped}'"


def _has_table(connection: Any, name: str) -> bool:
    try:
        connection.open_table(name)
    except ValueError:
        return False
    return True


def _model_path(settings: Settings) -> Path:
    return Path(settings.vector_path) / _MODEL_FILE


def _configured_model(settings: Settings) -> dict[str, str]:
    return {
        "provider": settings.embedding_provider,
        "model": settings.embedding_model,
    }


def _recorded_model(settings: Settings) -> dict[str, str] | None:
    path = _model_path(settings)
    if not path.exists():
        return None
    recorded: dict[str, str] = json.loads(path.read_text())
    return recorded


def _schema(dimensions: int) -> pa.Schema:
    """Stated explicitly so the first chunk stored cannot decide it."""
    metadata = pa.struct(
        [
            ("project_id", pa.string()),
            ("document_id", pa.string()),
            ("chunk_index", pa.int64()),
            ("page", pa.int64()),
            ("file_type", pa.string()),
        ]
    )
    return pa.schema(
        [
            ("vector", pa.list_(pa.float32(), dimensions)),
            ("id", pa.string()),
            ("text", pa.string()),
            ("metadata", metadata),
        ]
    )
