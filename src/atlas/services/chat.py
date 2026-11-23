"""Chats: conversations with a project's documents. Each chat belongs to the
user who started it; nobody else can read it.

Sending a message saves the question and an empty answer first, streams the
answer from ``core.chat``, then saves it. Each save is a short unit of work of
its own, so no transaction stays open while the answer streams.
"""

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any, Literal

from atlas.core.chat import AnswerEvent, answer, cited
from atlas.core.chat import title as generate_title
from atlas.core.providers.factory import describe_error
from atlas.models.base import utcnow
from atlas.models.chat import (
    Chat,
    ExportFormat,
    FeedbackRating,
    Message,
    MessageStatus,
)
from atlas.repository.base import Paged, PageRequest
from atlas.repository.uow import UnitOfWork, UnitOfWorkFactory
from atlas.services.access import Caller, load_project
from atlas.services.ai import AIRuntime
from atlas.services.errors import AlreadyExists, Busy, InvalidInput, NotFound

EventType = Literal[
    "message.created",
    "retrieval",
    "token",
    "message.completed",
    "chat.updated",
    "error",
]


@dataclass(frozen=True, slots=True)
class ChatEvent:
    """One step of a streamed answer; the controller turns it into SSE."""

    type: EventType
    data: Any


async def _chat(
    uow: UnitOfWork,
    caller: Caller,
    project_id: str,
    chat_id: str,
    *,
    with_messages: bool = False,
) -> Chat:
    await load_project(uow, caller, project_id)
    load = (
        uow.chats.get_with_messages if with_messages else uow.chats.get_owned
    )
    chat = await load(project_id, chat_id, caller.user_id)
    if chat is None:
        raise NotFound("chat not found", code="chat_not_found")
    return chat


class ChatService:
    def __init__(self, *, uow: UnitOfWorkFactory, ai: AIRuntime) -> None:
        self._uow = uow
        self._ai = ai

    # -- chats -------------------------------------------------------------

    async def create(
        self,
        caller: Caller,
        project_id: str,
        *,
        title: str | None = None,
        scope: dict[str, Any] | None = None,
    ) -> Chat:
        async with self._uow() as uow:
            await load_project(uow, caller, project_id)
            return await uow.chats.add(
                Chat(
                    project_id=project_id,
                    user_id=caller.user_id,
                    title=title,
                    scope=scope,
                )
            )

    async def list_chats(
        self,
        caller: Caller,
        project_id: str,
        page: PageRequest,
        *,
        q: str | None = None,
        archived: bool = False,
        pinned: bool | None = None,
    ) -> Paged[Chat]:
        async with self._uow() as uow:
            await load_project(uow, caller, project_id)
            return await uow.chats.page_owned(
                project_id,
                caller.user_id,
                page,
                q=q,
                archived=archived,
                pinned=pinned,
            )

    async def get(self, caller: Caller, project_id: str, chat_id: str) -> Chat:
        async with self._uow() as uow:
            return await _chat(uow, caller, project_id, chat_id)

    async def update(
        self,
        caller: Caller,
        project_id: str,
        chat_id: str,
        *,
        title: str | None = None,
        pinned: bool | None = None,
        archived: bool | None = None,
        scope: dict[str, Any] | None = None,
    ) -> Chat:
        async with self._uow() as uow:
            chat = await _chat(uow, caller, project_id, chat_id)
            if title is not None:
                chat.title = title
            if pinned is not None:
                chat.pinned = pinned
            if archived is not None:
                chat.archived = archived
            if scope is not None:
                chat.scope = scope
        return chat

    async def delete(
        self, caller: Caller, project_id: str, chat_id: str
    ) -> None:
        async with self._uow() as uow:
            await uow.chats.delete(
                await _chat(uow, caller, project_id, chat_id)
            )

    # -- messages ----------------------------------------------------------

    async def list_messages(
        self,
        caller: Caller,
        project_id: str,
        chat_id: str,
        *,
        before: str | None = None,
        limit: int = 50,
    ) -> list[Message]:
        """Newest first; page back with ``before``."""
        async with self._uow() as uow:
            chat = await _chat(uow, caller, project_id, chat_id)
            return await uow.messages.page(chat.id, before=before, limit=limit)

    async def send(
        self,
        caller: Caller,
        project_id: str,
        chat_id: str,
        *,
        content: str,
        client_message_id: str | None = None,
    ) -> AsyncGenerator[ChatEvent, None]:
        """Ask a question; the answer streams back as events.

        Checks (busy, duplicate) run when iteration starts, so a controller
        should pull the first event before sending its response headers.
        """
        async with self._uow() as uow:
            chat = await _chat(
                uow, caller, project_id, chat_id, with_messages=True
            )
            if any(m.status == "streaming" for m in chat.messages):
                raise Busy(
                    "this chat is already answering",
                    code="generation_in_progress",
                )
            if client_message_id and await uow.messages.by_client_id(
                chat.id, client_message_id
            ):
                raise AlreadyExists("message already sent", code="duplicate")
            last = chat.messages[-1] if chat.messages else None
            question = await uow.messages.add(
                Message(
                    chat_id=chat.id,
                    role="user",
                    content=content,
                    parent_id=last.id if last else None,
                    client_message_id=client_message_id,
                )
            )
            answer = await uow.messages.add(
                Message(
                    chat_id=chat.id,
                    role="assistant",
                    status="streaming",
                    parent_id=question.id,
                )
            )
            chat.last_message_at = utcnow()
        yield ChatEvent("message.created", (question, answer))
        # aclosing: if the client goes away, close the inner stream now, so
        # its partial answer is saved as "stopped" instead of left hanging.
        async with aclosing(self._stream(chat, question, answer)) as events:
            async for event in events:
                yield event

    async def regenerate(
        self, caller: Caller, project_id: str, chat_id: str, message_id: str
    ) -> AsyncGenerator[ChatEvent, None]:
        """Answer the last question again, replacing the latest answer."""
        async with self._uow() as uow:
            chat = await _chat(
                uow, caller, project_id, chat_id, with_messages=True
            )
            messages = chat.messages
            if not messages or messages[-1].id != message_id:
                raise InvalidInput("only the latest answer can be regenerated")
            if messages[-1].status == "streaming":
                raise Busy("still answering", code="generation_in_progress")
            if len(messages) < 2 or messages[-1].role != "assistant":
                raise InvalidInput("the latest message is not an answer")
            question = messages[-2]
            answer = await uow.messages.get(message_id)
            assert answer is not None
            answer.content, answer.status = "", "streaming"
            answer.citations, answer.error, answer.feedback = [], None, None
        yield ChatEvent("message.created", (question, answer))
        # aclosing: if the client goes away, close the inner stream now, so
        # its partial answer is saved as "stopped" instead of left hanging.
        async with aclosing(self._stream(chat, question, answer)) as events:
            async for event in events:
                yield event

    async def set_feedback(
        self,
        caller: Caller,
        project_id: str,
        chat_id: str,
        message_id: str,
        *,
        rating: FeedbackRating,
        comment: str | None = None,
    ) -> Message:
        async with self._uow() as uow:
            message = await self._assistant_message(
                uow, caller, project_id, chat_id, message_id
            )
            message.feedback = {"rating": rating, "comment": comment}
        return message

    async def clear_feedback(
        self, caller: Caller, project_id: str, chat_id: str, message_id: str
    ) -> None:
        async with self._uow() as uow:
            message = await self._assistant_message(
                uow, caller, project_id, chat_id, message_id
            )
            message.feedback = None

    async def export(
        self,
        caller: Caller,
        project_id: str,
        chat_id: str,
        *,
        format: ExportFormat = "md",
    ) -> tuple[str, str]:
        """``(media_type, body)`` of the whole conversation."""
        async with self._uow() as uow:
            chat = await _chat(
                uow, caller, project_id, chat_id, with_messages=True
            )
        if format == "json":
            body = json.dumps(
                {
                    "title": chat.title,
                    "messages": [
                        {
                            "role": m.role,
                            "content": m.content,
                            "citations": m.citations,
                            "created_at": m.created_at.isoformat()
                            if m.created_at
                            else None,
                        }
                        for m in chat.messages
                    ],
                },
                indent=2,
            )
            return "application/json", body
        lines = [f"# {chat.title or 'Chat'}", ""]
        for m in chat.messages:
            who = "You" if m.role == "user" else "Assistant"
            lines += [f"**{who}:** {m.content}", ""]
        return "text/markdown", "\n".join(lines)

    # -- internals ---------------------------------------------------------

    async def _stream(
        self, chat: Chat, question: Message, answer: Message
    ) -> AsyncGenerator[ChatEvent, None]:
        text = ""
        citations: list[dict[str, Any]] = []
        try:
            async with aclosing(self._answer(chat, question)) as parts:
                async for kind, data in parts:
                    if kind == "token":
                        text += data
                    elif kind == "retrieval":
                        citations = data["citations"]
                    yield ChatEvent(kind, data)
        except (asyncio.CancelledError, GeneratorExit):
            # The client went away (or pressed stop): keep what was written.
            await asyncio.shield(
                self._finish(
                    answer.id, text, cited(text, citations), "stopped"
                )
            )
            raise
        except Exception as exc:
            self._ai.request_check()
            reason = describe_error(exc)
            await self._finish(
                answer.id, text, cited(text, citations), "failed", reason
            )
            yield ChatEvent(
                "error", {"code": "generation_failed", "message": reason}
            )
            return
        saved = await self._finish(
            answer.id, text, cited(text, citations), "complete"
        )
        yield ChatEvent("message.completed", saved)
        if chat.title is None:
            yield ChatEvent(
                "chat.updated", await self._name(chat.id, question, text)
            )

    async def _finish(
        self,
        message_id: str,
        text: str,
        citations: list[dict[str, Any]],
        status: MessageStatus,
        error: str | None = None,
    ) -> Message:
        async with self._uow() as uow:
            message = await uow.messages.get(message_id)
            assert message is not None
            message.content = text
            message.citations = citations
            message.status = status
            if error is not None:
                message.error = {"code": "generation_failed", "message": error}
            if (chat := await uow.chats.get(message.chat_id)) is not None:
                chat.last_message_at = utcnow()
        return message

    async def _answer(
        self, chat: Chat, question: Message
    ) -> AsyncGenerator[AnswerEvent, None]:
        llm, store, settings = self._ai.chat_tools()
        events = answer(
            llm=llm,
            store=store,
            chat=chat,
            question=question,
            k=settings.retrieval_k,
            history_limit=settings.chat_history_messages,
        )
        async with aclosing(events) as parts:
            async for kind, data in parts:
                if kind == "retrieval":
                    await self._add_titles(data["citations"])
                yield kind, data

    async def _add_titles(self, citations: list[dict[str, Any]]) -> None:
        """The engine knows document ids; people read titles."""
        async with self._uow() as uow:
            titles = await uow.documents.titles(
                c["document_id"] for c in citations
            )
        for citation in citations:
            citation["document_title"] = titles.get(
                citation["document_id"], "Deleted document"
            )

    async def _name(
        self, chat_id: str, question: Message, answer_text: str
    ) -> Chat | None:
        llm = self._ai.title_model
        title = (
            await generate_title(
                llm=llm, question=question.content, answer=answer_text
            )
            if llm is not None
            else question.content.strip().splitlines()[0][:60]
        )
        async with self._uow() as uow:
            chat = await uow.chats.get(chat_id)
            if chat is not None and chat.title is None:
                chat.title = title
        return chat

    @staticmethod
    async def _assistant_message(
        uow: UnitOfWork,
        caller: Caller,
        project_id: str,
        chat_id: str,
        message_id: str,
    ) -> Message:
        chat = await _chat(uow, caller, project_id, chat_id)
        message = await uow.messages.get_in_chat(chat.id, message_id)
        if message is None:
            raise NotFound("message not found", code="message_not_found")
        if message.role != "assistant":
            raise InvalidInput("feedback is for answers only")
        return message
