"""Chats and their messages. A chat is only ever looked up together with the
user who owns it: there is no query that can return someone else's chat."""

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from atlas.models.chat import Chat, Message
from atlas.repository.base import CrudRepository, Paged, PageRequest


class ChatRepository(CrudRepository[Chat]):
    model = Chat

    async def get_owned(
        self, project_id: str, chat_id: str, user_id: str
    ) -> Chat | None:
        rows = await self.session.scalars(
            select(Chat).where(
                Chat.id == chat_id,
                Chat.project_id == project_id,
                Chat.user_id == user_id,
            )
        )
        return rows.first()

    async def get_with_messages(
        self, project_id: str, chat_id: str, user_id: str
    ) -> Chat | None:
        """The chat with ``chat.messages`` loaded, oldest first."""
        rows = await self.session.scalars(
            select(Chat)
            .where(
                Chat.id == chat_id,
                Chat.project_id == project_id,
                Chat.user_id == user_id,
            )
            .options(selectinload(Chat.messages))
        )
        return rows.first()

    async def page_owned(
        self,
        project_id: str,
        user_id: str,
        page: PageRequest,
        *,
        q: str | None = None,
        archived: bool = False,
        pinned: bool | None = None,
    ) -> Paged[Chat]:
        query = select(Chat).where(
            Chat.project_id == project_id,
            Chat.user_id == user_id,
            Chat.archived == archived,
        )
        if pinned is not None:
            query = query.where(Chat.pinned == pinned)
        if q:
            query = query.where(Chat.title.icontains(q, autoescape=True))
        return await self._page(
            query.order_by(
                Chat.last_message_at.desc().nulls_last(),
                Chat.created_at.desc(),
                Chat.id,
            ),
            page,
        )

    async def delete(self, entity: Chat) -> None:
        await self.session.execute(
            delete(Message).where(Message.chat_id == entity.id)
        )
        await super().delete(entity)

    async def delete_for_user(self, user_id: str) -> None:
        """Every chat of an account being deleted, with its messages."""
        owned = select(Chat.id).where(Chat.user_id == user_id)
        await self.session.execute(
            delete(Message).where(Message.chat_id.in_(owned))
        )
        await self.session.execute(delete(Chat).where(Chat.user_id == user_id))


class MessageRepository(CrudRepository[Message]):
    model = Message

    async def get_in_chat(
        self, chat_id: str, message_id: str
    ) -> Message | None:
        rows = await self.session.scalars(
            select(Message).where(
                Message.id == message_id, Message.chat_id == chat_id
            )
        )
        return rows.first()

    async def by_client_id(
        self, chat_id: str, client_message_id: str
    ) -> Message | None:
        rows = await self.session.scalars(
            select(Message).where(
                Message.chat_id == chat_id,
                Message.client_message_id == client_message_id,
            )
        )
        return rows.first()

    async def page(
        self, chat_id: str, *, before: str | None, limit: int
    ) -> list[Message]:
        """Newest first, ``limit`` at a time, older than message
        ``before``."""
        query = select(Message).where(Message.chat_id == chat_id)
        if before is not None:
            anchor = select(Message.created_at).where(
                Message.id == before, Message.chat_id == chat_id
            )
            query = query.where(Message.created_at < anchor.scalar_subquery())
        rows = await self.session.scalars(
            query.order_by(Message.created_at.desc()).limit(limit)
        )
        return list(rows)
