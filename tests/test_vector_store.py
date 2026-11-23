"""The guarantees Atlas adds on top of LangChain's LanceDB store."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from langchain_community.vectorstores import LanceDB
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

from atlas.config import Settings
from atlas.core.vector_store import (
    build_vector_store,
    chunk_count,
    confirm_embedding_model,
    index_document,
    search,
)


def _settings(path: Path, model: str = "fake-a") -> Settings:
    return Settings(
        vector_path=str(path),
        jwt_secret="test",
        embedding_provider="fake",
        embedding_model=model,
        fake_embedding_dim=16,
    )


def _build(path: Path, model: str = "fake-a") -> tuple[LanceDB, bool]:
    return build_vector_store(
        settings=_settings(path, model),
        embeddings=DeterministicFakeEmbedding(size=16),
    )


def _chunk(text: str) -> Document:
    return Document(
        page_content=text, metadata={"page": 1, "file_type": ".txt"}
    )


async def _batches(*texts: str) -> AsyncIterator[list[Document]]:
    for text in texts:
        yield [_chunk(text)]


def _index(store: LanceDB, project: str, doc: str, *texts: str) -> int:
    return asyncio.run(
        index_document(
            store,
            project_id=project,
            document_id=doc,
            batches=_batches(*texts),
        )
    )


def _search(store: LanceDB, project: str) -> list[Document]:
    hits = asyncio.run(search(store, project_id=project, query="q", k=10))
    return [document for document, _ in hits]


def test_search_never_crosses_projects(tmp_path: Path) -> None:
    store, _ = _build(tmp_path)
    _index(store, "small", "d1", "only in the small project")
    _index(store, "large", "d2", *[f"large chunk {n}" for n in range(30)])

    hits = _search(store, "small")

    assert [d.page_content for d in hits] == ["only in the small project"]
    assert _search(store, "missing") == []


def test_scores_stay_between_zero_and_one(tmp_path: Path) -> None:
    store, _ = _build(tmp_path)
    _index(store, "p", "d", *[f"chunk {n}" for n in range(8)])
    hits = asyncio.run(search(store, project_id="p", query="q", k=8))
    assert hits and all(0 <= score <= 1 for _, score in hits)


def test_indexing_again_replaces_chunks(tmp_path: Path) -> None:
    store, _ = _build(tmp_path)
    _index(store, "p", "d", "old one", "old two", "old three")
    _index(store, "p", "d", "new one")

    assert [d.page_content for d in _search(store, "p")] == ["new one"]
    assert asyncio.run(chunk_count(store)) == 1


def test_failed_indexing_leaves_nothing_searchable(tmp_path: Path) -> None:
    store, _ = _build(tmp_path)

    async def broken() -> AsyncIterator[list[Document]]:
        yield [_chunk("written before the failure")]
        raise RuntimeError("parser died")

    with pytest.raises(RuntimeError):
        asyncio.run(
            index_document(
                store, project_id="p", document_id="d", batches=broken()
            )
        )

    assert _search(store, "p") == []


def test_new_embedding_model_requires_a_reindex(tmp_path: Path) -> None:
    store, first_run = _build(tmp_path)
    assert first_run
    confirm_embedding_model(settings=_settings(tmp_path))
    _index(store, "p", "d", "indexed with model A")

    _, same_model = _build(tmp_path)
    assert not same_model

    changed, needs_reindex = _build(tmp_path, model="fake-b")
    assert needs_reindex
    assert _search(changed, "p") == []  # never mix two models' vectors
