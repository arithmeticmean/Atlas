"""Reranking: reorder retrieved passages by asking the configured chat model.

Two stages of reranking exist in this codebase and they are not the same thing:

1. **RRF**, inside the chunk index, fuses the dense and sparse rankings of a
   hybrid query. It is free, and always on for ``mode="hybrid"``.
2. **This module**, which reorders the fused candidates by reading them. It
   costs one extra model call per query, and it is the stage that fixes the
   case both retrievers get wrong -- a passage that shares the query's words
   and its embedding neighbourhood while answering a different question.

Deliberately built on the chat model already configured rather than a
cross-encoder. A cross-encoder would mean ``sentence-transformers`` and, with
it, torch: hundreds of megabytes of native wheels in an application whose whole
point is to install from one wheel. This reuses whatever provider the instance
already talks to, and costs nothing to install.

The model is asked only to *order* passages it is shown, never to write prose,
and its answer is validated against the candidate list. Anything it returns
that is not a candidate index is discarded; if the reply is unusable the
retrieval order is kept. Reranking must degrade to "no reranking", never to
"no results".
"""

import json
import logging
import re

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from service.models.chunk import ScoredChunk

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You rank retrieved passages by how well each one answers a question. "
    "You never write prose, never summarise, and never invent passages. "
    'Reply with JSON only: {"order": [<passage numbers, best first>]}. '
    "Include only passages that genuinely help answer the question; drop the "
    "rest. If none help, reply {\"order\": []}."
)

# Passages are truncated before being sent: reranking 20 full chunks can cost
# more tokens than the answer itself, and the opening of a passage is enough to
# judge relevance.
_SNIPPET = 600


def _prompt(query: str, candidates: list[ScoredChunk]) -> str:
    passages = "\n\n".join(
        f"[{n}] {c.chunk.text[:_SNIPPET]}"
        for n, c in enumerate(candidates, start=1)
    )
    return f"Question: {query}\n\nPassages:\n{passages}"


def _parse_order(reply: str, count: int) -> list[int]:
    """Pull a validated 0-based ordering out of the model's reply.

    Tolerates a fenced code block or stray prose around the JSON, because
    models add both. Returns ``[]`` when nothing usable is found, which the
    caller treats as "keep the retrieval order".
    """
    match = re.search(r"\{.*\}", reply, re.S)
    if match is None:
        return []
    try:
        payload = json.loads(match.group(0))
    except ValueError:
        return []

    raw = payload.get("order")
    if not isinstance(raw, list):
        return []

    seen: set[int] = set()
    order: list[int] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, int):
            continue
        index = item - 1  # the prompt numbers from 1
        if 0 <= index < count and index not in seen:
            seen.add(index)
            order.append(index)
    return order


async def rerank(
    *,
    chat_model: BaseChatModel,
    query: str,
    candidates: list[ScoredChunk],
    k: int,
) -> list[ScoredChunk]:
    """Reorder ``candidates`` and return at most ``k``.

    Falls back to the retrieval order -- never to an empty list -- if the model
    is unreachable or its reply cannot be validated.
    """
    if len(candidates) <= 1:
        return candidates[:k]

    messages = [
        SystemMessage(_SYSTEM),
        HumanMessage(_prompt(query, candidates)),
    ]
    try:
        reply = await chat_model.ainvoke(messages)
    except Exception as exc:
        logger.warning("rerank failed, keeping retrieval order: %s", exc)
        return candidates[:k]

    order = _parse_order(_as_text(reply.content), len(candidates))
    if not order:
        logger.info("rerank returned no usable order; keeping retrieval order")
        return candidates[:k]

    # Scores come from the retriever and are not comparable to a rank, so the
    # reranked list carries a descending positional score instead. Keeping the
    # old numbers would imply the reranker agreed with them.
    top = order[:k]
    return [
        ScoredChunk(chunk=candidates[i].chunk, score=1.0 - n / len(top))
        for n, i in enumerate(top)
    ]


def _as_text(content: object) -> str:
    """Normalise a reply's content to text (providers differ)."""
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
