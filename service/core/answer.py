"""RAG answer generation: retrieve -> stuff context -> stream the LLM.

Yields a sequence of :class:`AnswerEvent`s the web layer serializes as
Server-Sent Events:

* ``sources`` -- the retrieved passages (once, first), so the UI can show
  citations before any tokens arrive;
* ``token``   -- answer text deltas as the model streams them;
* ``done``    -- terminal marker;
* ``error``   -- the LLM call failed mid-stream (headers are already sent, so
  a failure surfaces as an event rather than an HTTP status).

The embedding side must be ready (enforced by the route). The LLM is called
lazily here, so an unreachable LLM degrades to an ``error`` event without
affecting ingestion or search.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from service.core.search import SearchHit, SearchService

_SYSTEM_PROMPT = (
    "You are a retrieval-augmented assistant. Answer the question using ONLY "
    "the numbered context passages provided. Cite the passages you rely on by "
    "their bracketed number, e.g. [1]. If the context does not contain the "
    "answer, say you don't know instead of guessing."
)

_NO_CONTEXT_REPLY = (
    "I couldn't find anything relevant in the indexed documents."
)


@dataclass(slots=True)
class AnswerEvent:
    type: str  # "sources" | "token" | "done" | "error"
    data: object


class AnswerService:
    def __init__(
        self,
        *,
        search: SearchService,
        chat_model: BaseChatModel,
    ) -> None:
        self._search = search
        self._chat = chat_model

    async def answer(
        self, *, query: str, k: int, project_id: str
    ) -> AsyncIterator[AnswerEvent]:
        hits = await self._search.search(
            query=query, k=k, project_id=project_id
        )
        yield AnswerEvent(
            "sources",
            [_hit_dict(n, hit) for n, hit in enumerate(hits, start=1)],
        )

        if not hits:
            # No context: don't spend an LLM call to say "I don't know".
            yield AnswerEvent("token", _NO_CONTEXT_REPLY)
            yield AnswerEvent("done", {"finish_reason": "no_context"})
            return

        messages = [
            SystemMessage(_SYSTEM_PROMPT),
            HumanMessage(_build_prompt(query, hits)),
        ]
        try:
            async for chunk in self._chat.astream(messages):
                text = _chunk_text(chunk.content)
                if text:
                    yield AnswerEvent("token", text)
        except Exception as exc:
            yield AnswerEvent("error", {"message": str(exc)})
            return

        yield AnswerEvent("done", {"finish_reason": "stop"})


def _build_prompt(query: str, hits: list[SearchHit]) -> str:
    context = "\n\n".join(
        f"[{n}] {hit.text}" for n, hit in enumerate(hits, start=1)
    )
    return f"Context:\n{context}\n\nQuestion: {query}"


def _hit_dict(n: int, hit: SearchHit) -> dict[str, object]:
    return {
        "n": n,
        "document_id": hit.document_id,
        "chunk_index": hit.chunk_index,
        "score": hit.score,
        "text": hit.text,
    }


def _chunk_text(content: object) -> str:
    """Normalize a message chunk's content to text.

    Most providers stream ``content`` as a ``str``; some (e.g. Anthropic) may
    stream a list of typed blocks -- keep only their text.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return ""
