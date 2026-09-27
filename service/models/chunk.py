"""A chunk of a document, as stored in and returned from the chunk index."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Chunk:
    """One indexed passage.

    ``id`` is derived from the document and the position within it
    (``<document_id>:<chunk_index>``) rather than random, so re-ingesting a
    document produces the same ids and a delete-then-add replaces cleanly
    instead of accumulating duplicates.
    """

    document_id: str
    project_id: str
    chunk_index: int
    text: str
    vector: list[float] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.document_id}:{self.chunk_index}"


@dataclass(frozen=True, slots=True)
class ScoredChunk:
    """A chunk the index returned, with its score.

    ``score`` is a **relevance** score: higher is better, always. That is a
    deliberate break from the raw vector distance the old langchain path
    returned (where lower was better), because a single index can now answer
    with dense, sparse or fused results whose natural scales disagree. One
    direction across all of them is the only thing a caller can render
    honestly.
    """

    chunk: Chunk
    score: float
