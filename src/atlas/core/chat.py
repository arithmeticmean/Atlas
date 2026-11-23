"""Chat with a project's documents as the base of the conversation.

Takes the saved chat and question and streams events back. Saving messages,
permissions and turning events into HTTP stay in the service layer. The chat
must have ``chat.messages`` loaded, and is only read.
"""

import logging
import re
from collections.abc import AsyncGenerator
from itertools import takewhile
from typing import Any, Literal

from langchain_community.vectorstores import LanceDB
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser

from atlas.core.prompts import ANSWER_PROMPT, TITLE_PROMPT
from atlas.core.vector_store import search
from atlas.models.chat import Chat, Message

__all__ = ["AnswerEvent", "answer", "cited", "title"]

logger = logging.getLogger(__name__)

AnswerEvent = tuple[Literal["retrieval", "token"], Any]

_NO_EXCERPTS = "(nothing found)"
_CITATION = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")
_PREVIOUS_QUESTION_CHARS = 500
_TITLE_LENGTH = 60


async def answer(
    *,
    llm: BaseChatModel,
    store: LanceDB,
    chat: Chat,
    question: Message,
    k: int = 5,
    history_limit: int = 10,
) -> AsyncGenerator[AnswerEvent, None]:
    """Stream the answer to ``question``, searching only ``chat``'s project.

    Yields ``("retrieval", {"rewritten_query", "citations"})`` once, before
    any text, then ``("token", text)`` pieces. ``citations`` are the passages
    the model was given; :func:`cited` narrows them to the ones it used. Each
    has ``n``, ``document_id``, ``chunk_index``, ``page``, ``text``, ``score``.

    The model always replies, so ordinary conversation works whether or not
    the documents are relevant. A model or search failure raises, for the
    caller to record.
    """
    history = _history(chat, question, history_limit)
    query = _search_query(history, question.content)
    hits = await search(store, project_id=chat.project_id, query=query, k=k)
    yield (
        "retrieval",
        {
            "rewritten_query": None,
            "citations": [
                _citation(n, chunk, score)
                for n, (chunk, score) in enumerate(hits, start=1)
            ],
        },
    )
    context = "\n\n".join(
        f"[{n}] {chunk.page_content}"
        for n, (chunk, _) in enumerate(hits, start=1)
    )
    chain = ANSWER_PROMPT | llm | StrOutputParser()
    async for token in chain.astream(
        {
            "history": history,
            "context": context or _NO_EXCERPTS,
            "question": question.content,
        }
    ):
        if token:
            yield "token", token


async def title(*, llm: BaseChatModel, question: str, answer: str) -> str:
    """A short chat title. Never fails: if the model does, or returns
    nothing usable, the start of the question is used."""
    chain = TITLE_PROMPT | llm | StrOutputParser()
    try:
        generated = await chain.ainvoke(
            {"question": question, "answer": answer}
        )
    except Exception as exc:
        logger.warning("could not generate a title: %s", type(exc).__name__)
        generated = ""
    text = _first_line(generated) or _first_line(question) or "New chat"
    return text[:_TITLE_LENGTH]


def _first_line(text: str) -> str:
    lines = text.strip().splitlines()
    return lines[0].strip(" \"'") if lines else ""


def _history(
    chat: Chat, question: Message, limit: int
) -> list[tuple[str, str]]:
    """The usable messages before ``question``, newest ``limit``, as the
    ``(role, text)`` pairs LangChain prompts accept."""
    earlier = takewhile(lambda m: m.id != question.id, chat.messages)
    usable: list[tuple[str, str]] = [
        (m.role, m.content)
        for m in earlier
        if m.content and m.status in ("complete", "stopped")
    ]
    return usable[-limit:]


def _search_query(history: list[tuple[str, str]], question: str) -> str:
    """Search with the previous question too, so a follow-up like "and for
    cats?" finds the right passages without a slow extra model call."""
    previous = next((t for role, t in reversed(history) if role == "user"), "")
    return f"{previous[-_PREVIOUS_QUESTION_CHARS:]}\n{question}".strip()


def cited(text: str, citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only the citations ``text`` actually refers to."""
    used = {
        int(number)
        for group in _CITATION.findall(text)
        for number in group.split(",")
    }
    return [c for c in citations if c["n"] in used]


def _citation(n: int, chunk: Document, score: float) -> dict[str, Any]:
    return {
        "n": n,
        "document_id": chunk.metadata["document_id"],
        "chunk_index": chunk.metadata["chunk_index"],
        "page": chunk.metadata["page"],
        "text": chunk.page_content,
        "score": score,
    }
