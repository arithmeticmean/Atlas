"""How a message becomes an answer."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.language_models import FakeListChatModel

from atlas.config import Settings
from atlas.core.chat import _search_query, answer, cited, title
from atlas.core.vector_store import build_vector_store

_CITATIONS = [{"n": n} for n in range(1, 6)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hello, how can I help?", []),
        ("Pets need consent [2].", [2]),
        ("Both agree [1] and [4].", [1, 4]),
        ("Grouped [2, 5].", [2, 5]),
        ("Made up source [9].", []),
    ],
)
def test_only_used_passages_become_sources(
    text: str, expected: list[int]
) -> None:
    assert [c["n"] for c in cited(text, _CITATIONS)] == expected


def test_follow_up_search_includes_the_previous_question() -> None:
    history = [("user", "What about dogs?"), ("assistant", "Allowed.")]
    query = _search_query(history, "and cats?")
    assert query == "What about dogs?\nand cats?"
    assert _search_query([], "first question") == "first question"


def test_model_answers_even_with_no_documents(tmp_path: Path) -> None:
    settings = Settings(
        vector_path=str(tmp_path),
        jwt_secret="test",
        embedding_provider="fake",
        fake_embedding_dim=16,
    )
    store, _ = build_vector_store(
        settings=settings, embeddings=DeterministicFakeEmbedding(size=16)
    )
    question = SimpleNamespace(id="q", content="hello")
    chat: Any = SimpleNamespace(project_id="p", messages=[question])

    async def run() -> list[tuple[str, Any]]:
        events = answer(
            llm=FakeListChatModel(responses=["Hi there"]),
            store=store,
            chat=chat,
            question=question,  # type: ignore[arg-type]
        )
        return [event async for event in events]

    events = asyncio.run(run())

    assert events[0] == (
        "retrieval",
        {"rewritten_query": None, "citations": []},
    )
    assert "".join(text for kind, text in events[1:]) == "Hi there"


def test_title_falls_back_to_the_question() -> None:
    class Broken(FakeListChatModel):
        def _call(self, *args: Any, **kwargs: Any) -> str:
            raise RuntimeError("model down")

    generated = asyncio.run(
        title(
            llm=Broken(responses=["x"]),
            question="What is the pet policy?\nsecond line",
            answer="...",
        )
    )
    assert generated == "What is the pet policy?"
