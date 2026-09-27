"""Streaming RAG answer endpoint (Server-Sent Events).

``POST /answer`` retrieves context and streams the LLM's answer to the client
as ``text/event-stream`` rather than a single JSON blob. Events:

    event: sources\n data: [{n, document_id, chunk_index, score, text}, ...]
    event: token\n   data: "partial text"
    event: done\n    data: {"finish_reason": "stop"}
    event: error\n   data: {"message": "..."}

The query is in the POST body, so a browser consumes this with a ``fetch``
stream reader (not ``EventSource``, which is GET-only).
"""

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from service.api.dependencies import (
    ProjectMemberCtx,
    get_answer_service,
    require_ready,
)
from service.core.answer import AnswerService

router = APIRouter(prefix="/projects/{project_id}/answer", tags=["answer"])

ServiceDep = Annotated[AnswerService, Depends(get_answer_service)]


class AnswerRequest(BaseModel):
    query: str = Field(min_length=1)
    k: int = Field(default=5, ge=1, le=50)


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("", dependencies=[Depends(require_ready)])
async def answer(
    ctx: ProjectMemberCtx, service: ServiceDep, r: AnswerRequest
) -> StreamingResponse:
    project_id = ctx.project.id

    async def stream() -> AsyncIterator[str]:
        async for event in service.answer(
            query=r.query, k=r.k, project_id=project_id
        ):
            yield _sse(event.type, event.data)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # don't let nginx buffer the stream
        },
    )
