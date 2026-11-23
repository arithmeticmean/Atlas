"""Conversations with a project's documents. A chat is private to whoever
created it. Sending a message streams named events, in this order::

    event: message.created    data: {user_message, assistant_message}
    event: retrieval          data: {rewritten_query, citations}
    event: token              data: {delta}             (repeated)
    event: message.completed  data: {message}           (as saved)
    event: chat.updated       data: {chat}              (first turn: title)
    event: error              data: {code, message}     (instead of completed)

Stopping is the client aborting its request: the server sees the disconnect
and saves the partial answer as ``stopped``.
"""

import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from atlas.controllers._common import (
    CurrentCaller,
    Page,
    PageQuery,
    ResponseModel,
    Services,
    page_request,
    problems,
    require_ready,
    sse_response,
    to_page,
)
from atlas.models.chat import (
    ExportFormat,
    FeedbackRating,
    MessageRole,
    MessageStatus,
)
from atlas.services.chat import ChatEvent

router = APIRouter(prefix="/projects/{project_id}/chats", tags=["chats"])

_SSE_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {
        "content": {"text/event-stream": {}},
        "description": "the answer as named events; see the module docstring",
    }
}


class ChatScope(BaseModel):
    """Stored with the chat; retrieval does not apply it yet."""

    tags: list[str] | None = None
    document_ids: list[str] | None = None


class ChatResponse(ResponseModel):
    id: str
    project_id: str
    title: str | None
    pinned: bool
    archived: bool
    scope: ChatScope | None
    created_at: datetime | None
    updated_at: datetime | None
    last_message_at: datetime | None


class ChatCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    scope: ChatScope | None = None


class ChatUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    pinned: bool | None = None
    archived: bool | None = None
    scope: ChatScope | None = None


class ChatListQuery(PageQuery):
    q: str | None = Field(default=None, description="matches the title")
    archived: bool = False
    pinned: bool | None = None


class Citation(BaseModel):
    n: int
    document_id: str
    document_title: str
    chunk_index: int
    page: int
    # A copy of the passage: re-indexing replaces chunks.
    text: str
    score: float


class Feedback(BaseModel):
    rating: FeedbackRating
    comment: str | None = Field(default=None, max_length=2000)


class MessageError(BaseModel):
    code: str
    message: str


class MessageResponse(ResponseModel):
    id: str
    chat_id: str
    parent_id: str | None
    role: MessageRole
    content: str
    status: MessageStatus
    citations: list[Citation]
    rewritten_query: str | None
    model: str | None
    usage: dict[str, int] | None
    feedback: Feedback | None
    error: MessageError | None
    created_at: datetime | None


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=32_000)
    # Lets a retry after a network blip be recognised, not posted twice.
    client_message_id: str | None = Field(default=None, max_length=100)


class MessageListQuery(BaseModel):
    before: str | None = Field(
        default=None, description="a message id; omit for the newest"
    )
    limit: int = Field(default=50, ge=1, le=200)


class ExportQuery(BaseModel):
    format: ExportFormat = "md"


def _message(message: Any) -> dict[str, Any]:
    return MessageResponse.model_validate(message).model_dump(mode="json")


def _encode(event: ChatEvent) -> tuple[str, str]:
    data: Any = event.data
    if event.type == "message.created":
        question, answer = data
        data = {
            "user_message": _message(question),
            "assistant_message": _message(answer),
        }
    elif event.type == "token":
        data = {"delta": data}
    elif event.type == "message.completed":
        data = {"message": _message(data)}
    elif event.type == "chat.updated":
        data = {
            "chat": ChatResponse.model_validate(data).model_dump(mode="json")
        }
    return event.type, json.dumps(data)


@router.post(
    "", status_code=status.HTTP_201_CREATED, responses=problems(401, 404, 422)
)
async def create_chat(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    body: ChatCreate,
) -> ChatResponse:
    chat = await services.chats.create(
        caller,
        project_id,
        title=body.title,
        scope=body.scope.model_dump() if body.scope else None,
    )
    return ChatResponse.model_validate(chat)


@router.get("", responses=problems(401, 404))
async def list_chats(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    query: Annotated[ChatListQuery, Query()],
) -> Page[ChatResponse]:
    chats = await services.chats.list_chats(
        caller,
        project_id,
        page_request(query),
        q=query.q,
        archived=query.archived,
        pinned=query.pinned,
    )
    return to_page(ChatResponse, chats)


@router.get("/{chat_id}", responses=problems(401, 404))
async def get_chat(
    services: Services, caller: CurrentCaller, project_id: str, chat_id: str
) -> ChatResponse:
    chat = await services.chats.get(caller, project_id, chat_id)
    return ChatResponse.model_validate(chat)


@router.patch("/{chat_id}", responses=problems(401, 404, 422))
async def update_chat(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    chat_id: str,
    body: ChatUpdate,
) -> ChatResponse:
    chat = await services.chats.update(
        caller,
        project_id,
        chat_id,
        title=body.title,
        pinned=body.pinned,
        archived=body.archived,
        scope=body.scope.model_dump() if body.scope else None,
    )
    return ChatResponse.model_validate(chat)


@router.delete(
    "/{chat_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problems(401, 404),
)
async def delete_chat(
    services: Services, caller: CurrentCaller, project_id: str, chat_id: str
) -> None:
    await services.chats.delete(caller, project_id, chat_id)


@router.get(
    "/{chat_id}/export",
    response_class=Response,
    responses={
        200: {
            "content": {"text/markdown": {}, "application/json": {}},
            "description": "the conversation as a file",
        },
        **problems(401, 404),
    },
)
async def export_chat(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    chat_id: str,
    query: Annotated[ExportQuery, Query()],
) -> Response:
    media_type, body = await services.chats.export(
        caller, project_id, chat_id, format=query.format
    )
    return Response(
        body,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="chat-{chat_id}.{query.format}"'
            )
        },
    )


@router.get("/{chat_id}/messages", responses=problems(401, 404))
async def list_messages(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    chat_id: str,
    query: Annotated[MessageListQuery, Query()],
) -> Page[MessageResponse]:
    messages = await services.chats.list_messages(
        caller, project_id, chat_id, before=query.before, limit=query.limit
    )
    has_more = len(messages) == query.limit
    return Page[MessageResponse](
        items=[MessageResponse.model_validate(m) for m in messages],
        next_cursor=messages[-1].id if has_more else None,
    )


@router.post(
    "/{chat_id}/messages",
    response_class=StreamingResponse,
    dependencies=[Depends(require_ready)],
    responses={**_SSE_RESPONSE, **problems(401, 404, 409, 422, 503)},
)
async def send_message(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    chat_id: str,
    body: MessageCreate,
) -> StreamingResponse:
    events = services.chats.send(
        caller,
        project_id,
        chat_id,
        content=body.content,
        client_message_id=body.client_message_id,
    )
    return await sse_response(events, _encode)


@router.post(
    "/{chat_id}/messages/{message_id}/regenerate",
    response_class=StreamingResponse,
    dependencies=[Depends(require_ready)],
    responses={**_SSE_RESPONSE, **problems(401, 404, 409, 422, 503)},
)
async def regenerate_message(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    chat_id: str,
    message_id: str,
) -> StreamingResponse:
    events = services.chats.regenerate(caller, project_id, chat_id, message_id)
    return await sse_response(events, _encode)


@router.put(
    "/{chat_id}/messages/{message_id}/feedback",
    responses=problems(401, 404, 422),
)
async def set_feedback(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    chat_id: str,
    message_id: str,
    body: Feedback,
) -> MessageResponse:
    message = await services.chats.set_feedback(
        caller,
        project_id,
        chat_id,
        message_id,
        rating=body.rating,
        comment=body.comment,
    )
    return MessageResponse.model_validate(message)


@router.delete(
    "/{chat_id}/messages/{message_id}/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problems(401, 404, 422),
)
async def clear_feedback(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    chat_id: str,
    message_id: str,
) -> None:
    await services.chats.clear_feedback(
        caller, project_id, chat_id, message_id
    )
