from datetime import datetime
from typing import Any, Literal

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, relationship
from sqlalchemy.orm import mapped_column as column

from atlas.models.base import Base, Timestamped, UTCDateTime, new_id

MessageRole = Literal["user", "assistant"]
MessageStatus = Literal["complete", "streaming", "stopped", "failed"]
FeedbackRating = Literal["up", "down"]
ExportFormat = Literal["md", "json"]


class Chat(Timestamped, Base, kw_only=True, eq=False):
    """One conversation, private to the user who started it."""

    __tablename__ = "chats"

    id: Mapped[str] = column(String, primary_key=True, default_factory=new_id)
    project_id: Mapped[str] = column(String, index=True)
    user_id: Mapped[str] = column(String, index=True)
    title: Mapped[str | None] = column(String, default=None)
    pinned: Mapped[bool] = column(Boolean, default=False)
    archived: Mapped[bool] = column(Boolean, default=False)
    # Limits retrieval: {"tags": [...], "document_ids": [...]}.
    scope: Mapped[dict[str, Any] | None] = column(JSON, default=None)
    last_message_at: Mapped[datetime | None] = column(
        UTCDateTime(), default=None
    )

    # Read-only, and never loaded by accident: the repository loads it on
    # purpose (ChatRepository.get_with_messages); touching it otherwise
    # raises instead of quietly querying. viewonly means appending to it
    # saves nothing -- messages are added through the repository.
    messages: Mapped[list["Message"]] = relationship(
        order_by="Message.created_at",
        lazy="raise",
        viewonly=True,
        init=False,
        default_factory=list,
    )


class Message(Timestamped, Base, kw_only=True, eq=False):
    __tablename__ = "messages"

    id: Mapped[str] = column(String, primary_key=True, default_factory=new_id)
    chat_id: Mapped[str] = column(ForeignKey("chats.id"), index=True)
    role: Mapped[MessageRole] = column(String)
    content: Mapped[str] = column(Text, default="")
    status: Mapped[MessageStatus] = column(String, default="complete")
    # The message this one answers or follows; kept so edit-and-branch can
    # come later without a migration.
    parent_id: Mapped[str | None] = column(String, default=None)
    # Copies of the cited passages: re-indexing replaces chunks, so an id
    # alone would stop resolving.
    citations: Mapped[list[dict[str, Any]]] = column(
        JSON, default_factory=list
    )
    rewritten_query: Mapped[str | None] = column(Text, default=None)
    model: Mapped[str | None] = column(String, default=None)
    usage: Mapped[dict[str, int] | None] = column(JSON, default=None)
    feedback: Mapped[dict[str, Any] | None] = column(JSON, default=None)
    error: Mapped[dict[str, str] | None] = column(JSON, default=None)
    # Lets a retried send be recognised instead of stored twice.
    client_message_id: Mapped[str | None] = column(String, default=None)
