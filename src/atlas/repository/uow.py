"""The unit of work: every repository on one database transaction.

Everything written through one ``UnitOfWork`` is saved together or not at
all: a document's row and its ingest job; a signup and the membership it
grants. Entities are updated by changing their attributes -- the session
sees the change and the commit writes it. Files are reached through
``uow.documents`` (see ``repository/files.py`` for the two ordering rules).

A request uses one for its whole lifetime. Work that outlives a request
(the worker, a sync, a streamed answer) takes a ``UnitOfWorkFactory`` and
opens a short one per step, so that -- for example -- a ``failed`` status
commits even though the work it describes raised.
"""

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.repository.chats import ChatRepository, MessageRepository
from atlas.repository.connectors import ConnectorRepository
from atlas.repository.documents import DocumentRepository
from atlas.repository.files import FileStore
from atlas.repository.jobs import JobRepository
from atlas.repository.projects import MembershipRepository, ProjectRepository
from atlas.repository.settings import SettingsRepository
from atlas.repository.users import UserRepository


class UnitOfWork:
    def __init__(self, session: AsyncSession, files: FileStore) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.projects = ProjectRepository(session)
        self.members = MembershipRepository(session)
        self.documents = DocumentRepository(session, files)
        self.connectors = ConnectorRepository(session)
        self.jobs = JobRepository(session)
        self.chats = ChatRepository(session)
        self.messages = MessageRepository(session)
        self.settings = SettingsRepository(session)

    async def commit(self) -> None:
        """Happens on a clean exit anyway; call it earlier when something
        must follow a committed change (deleting a file)."""
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


@asynccontextmanager
async def unit_of_work(
    *, sessions: async_sessionmaker[AsyncSession], files: FileStore
) -> AsyncGenerator[UnitOfWork, None]:
    """Committed when the block exits cleanly, rolled back if it raises --
    including if the commit itself fails."""
    async with sessions() as session:
        uow = UnitOfWork(session, files)
        try:
            yield uow
            await uow.commit()
        except BaseException:
            await uow.rollback()
            raise


# What background code is given: entering opens a unit of work. The
# composition root binds its dependencies:
#   factory = partial(unit_of_work, sessions=sessions, files=store)
UnitOfWorkFactory = Callable[[], AbstractAsyncContextManager[UnitOfWork]]
