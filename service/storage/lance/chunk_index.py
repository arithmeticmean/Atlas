"""LanceDB adapter for the ChunkIndex port, on the native async client.

Native rather than through langchain, because hybrid retrieval needs to hand
LanceDB both the query vector and the query text -- `tbl.query().nearest_to(v)
.nearest_to_text(q)` -- and the langchain wrapper only passes one value down.

Three retrieval modes over one table:

* ``vector`` -- dense ANN on the embedding;
* ``fts``    -- LanceDB's native full-text index on ``text``, which is what
  finds an exact term (an error code, a symbol, a product name) that an
  embedding places nowhere near the query;
* ``hybrid`` -- both, fused by reciprocal rank fusion.

Scores are normalised to "higher is better" before leaving this module: the
three modes report on incompatible scales (`_distance` ascending, `_score` and
`_relevance_score` descending), and a caller cannot render or threshold a
number whose direction depends on a mode flag.
"""

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

import pyarrow as pa
from lancedb.index import FTS  # type: ignore[import-untyped]

from service.models.chunk import Chunk, ScoredChunk
from service.storage.store.chunk_index import ChunkIndex, SearchMode

logger = logging.getLogger(__name__)

_TEXT_COLUMN = "text"
_VECTOR_COLUMN = "vector"


def _schema(dim: int) -> pa.Schema:
    """The table's schema, stated explicitly.

    Never inferred from the first insert: the vector dimension and the
    nullability of every column have to be stable for the life of the index,
    and inference makes them a property of whichever row happened to arrive
    first.
    """
    return pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("document_id", pa.string(), nullable=False),
            pa.field("project_id", pa.string(), nullable=False),
            pa.field("chunk_index", pa.int32(), nullable=False),
            pa.field(_TEXT_COLUMN, pa.string(), nullable=False),
            pa.field(
                _VECTOR_COLUMN,
                pa.list_(pa.float32(), dim),
                nullable=False,
            ),
        ]
    )


def _quote(value: str) -> str:
    """Quote a string for a LanceDB SQL filter."""
    return "'" + value.replace("'", "''") + "'"


class LanceChunkIndex(ChunkIndex):
    def __init__(self, *, uri: str, table_name: str) -> None:
        self._uri = uri
        self._table_name = table_name
        self._db: Any = None
        self._table: Any = None
        # One writer at a time: create-then-add from two requests would race on
        # table creation, and LanceDB has no create-if-absent primitive here.
        self._lock = asyncio.Lock()

    # -- connection -------------------------------------------------------

    async def _connect(self) -> Any:
        if self._db is None:
            import lancedb  # type: ignore[import-untyped]

            self._db = await lancedb.connect_async(self._uri)
        return self._db

    async def _open(self) -> Any | None:
        """The table, or ``None`` when nothing has been indexed yet."""
        if self._table is not None:
            return self._table
        db = await self._connect()
        if self._table_name not in await db.table_names():
            return None
        self._table = await db.open_table(self._table_name)
        return self._table

    async def _open_or_create(self, dim: int) -> Any:
        table = await self._open()
        if table is not None:
            return table
        db = await self._connect()
        self._table = await db.create_table(
            self._table_name, schema=_schema(dim)
        )
        # The FTS index is what makes `mode="fts"` and the sparse half of
        # hybrid possible. Native (no tantivy); it sees rows added later, so it
        # is created once here rather than rebuilt per write.
        await self._table.create_index(_TEXT_COLUMN, config=FTS())
        logger.info(
            "created chunk index %r (dim=%d) with a full-text index on %r",
            self._table_name,
            dim,
            _TEXT_COLUMN,
        )
        return self._table

    def forget(self) -> None:
        """Drop the cached handles.

        Called after the table is wiped for a re-index: the old handle points
        at a table that no longer exists.
        """
        self._table = None
        self._db = None

    # -- writes -----------------------------------------------------------

    async def add(self, chunks: Sequence[Chunk]) -> None:
        if not chunks:
            return
        dim = len(chunks[0].vector)
        if dim == 0:
            raise ValueError("chunks must carry embeddings before indexing")
        rows = [
            {
                "id": c.id,
                "document_id": c.document_id,
                "project_id": c.project_id,
                "chunk_index": c.chunk_index,
                _TEXT_COLUMN: c.text,
                _VECTOR_COLUMN: list(c.vector),
            }
            for c in chunks
        ]
        async with self._lock:
            table = await self._open_or_create(dim)
            await table.add(rows)

    async def delete_document(self, document_id: str) -> None:
        table = await self._open()
        if table is None:
            return
        await table.delete(f"document_id = {_quote(document_id)}")

    async def drop(self) -> None:
        """Drop the table through this adapter's own connection.

        Doing it from a second, independent client -- which is what a separate
        sync `lancedb.connect()` is -- can leave the dataset's manifest
        pointing at data files the drop removed, and every later write then
        fails with a missing-file error. One client owns the table's lifecycle.
        """
        async with self._lock:
            db = await self._connect()
            if self._table_name in await db.table_names():
                await db.drop_table(self._table_name, ignore_missing=True)
                logger.info("dropped chunk index %r", self._table_name)
            self._table = None

    async def count(self) -> int:
        table = await self._open()
        if table is None:
            return 0
        count: int = await table.count_rows()
        return count

    # -- reads ------------------------------------------------------------

    async def search(
        self,
        *,
        project_id: str,
        query_text: str,
        query_vector: Sequence[float],
        k: int,
        mode: SearchMode = "hybrid",
    ) -> list[ScoredChunk]:
        table = await self._open()
        if table is None:
            return []

        where = f"project_id = {_quote(project_id)}"
        query = table.query()

        if mode == "vector":
            query = query.nearest_to(list(query_vector))
        elif mode == "fts":
            query = query.nearest_to_text(query_text, columns=_TEXT_COLUMN)
        else:
            # Order matters: the vector leg first, then the text leg, is what
            # makes this a hybrid query rather than one or the other.
            query = (
                table.query()
                .nearest_to(list(query_vector))
                .nearest_to_text(query_text, columns=_TEXT_COLUMN)
                # Reciprocal rank fusion: combines the two rankings by
                # position, so the legs' incomparable score scales never have
                # to be reconciled. This is the reranking that is free.
                .rerank()
            )

        try:
            # No .postfilter(): LanceDB pre-filters by default, which is what
            # project isolation requires.
            rows = await query.where(where).limit(k).to_list()
        except Exception as exc:
            # An FTS query before the index finished building, or a malformed
            # term, should degrade rather than fail the request.
            logger.warning("chunk search (%s) failed: %s", mode, exc)
            return []

        return [_to_scored(row, mode) for row in rows]


def _to_scored(row: dict[str, Any], mode: SearchMode) -> ScoredChunk:
    """One row to a ScoredChunk, with the score pointed the same way."""
    if mode == "vector":
        # L2 distance, ascending. Map to (0, 1] descending without pretending
        # it is a probability.
        distance = float(row.get("_distance", 0.0))
        score = 1.0 / (1.0 + max(distance, 0.0))
    elif mode == "fts":
        score = float(row.get("_score", 0.0))
    else:
        score = float(row.get("_relevance_score", 0.0))

    return ScoredChunk(
        chunk=Chunk(
            document_id=row["document_id"],
            project_id=row["project_id"],
            chunk_index=int(row["chunk_index"]),
            text=row[_TEXT_COLUMN],
        ),
        score=score,
    )
