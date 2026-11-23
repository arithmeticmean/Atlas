"""The composition root: builds every long-lived object, once.

This is the only module that knows how the pieces fit together. Controllers
reach services through it, and it owns the background tasks' lifetime.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import partial

from atlas.config import BootstrapSettings, MasterKey
from atlas.repository.db import create_engine, create_sessionmaker
from atlas.repository.files import ObjectFileStore
from atlas.repository.migrate import upgrade_to_head
from atlas.repository.uow import UnitOfWorkFactory, unit_of_work
from atlas.services.ai import AIRuntime
from atlas.services.auth import AuthService
from atlas.services.chat import ChatService
from atlas.services.connectors import ConnectorService
from atlas.services.documents import DocumentService
from atlas.services.ingestion import IngestionService
from atlas.services.invites import InviteService
from atlas.services.projects import ProjectService
from atlas.services.security import TokenCodec
from atlas.services.settings import SettingsService
from atlas.services.setup import SetupService
from atlas.services.system import SystemService
from atlas.services.users import UserService
from atlas.services.worker import Worker

logger = logging.getLogger(__name__)

_RESTART_DELAY_SECONDS = 5


class Container:
    def __init__(self, bootstrap: BootstrapSettings) -> None:
        bootstrap.create_directories()
        self.bootstrap = bootstrap
        self._engine = create_engine(settings=bootstrap)
        files = ObjectFileStore.from_url(bootstrap.documents_path.as_uri())
        uow: UnitOfWorkFactory = partial(
            unit_of_work,
            sessions=create_sessionmaker(engine=self._engine),
            files=files,
        )
        self.ai = AIRuntime(uow=uow)
        self.settings = SettingsService(
            uow=uow,
            bootstrap=bootstrap,
            master_key=MasterKey.load(bootstrap),
            ai=self.ai,
        )
        tokens = TokenCodec(settings=self.settings)
        self.auth = AuthService(uow=uow, tokens=tokens)
        self.users = UserService(uow=uow, tokens=tokens)
        self.setup = SetupService(uow=uow, users=self.users, tokens=tokens)
        self.invites = InviteService(uow=uow, tokens=tokens)
        self.projects = ProjectService(uow=uow, ai=self.ai)
        self.documents = DocumentService(
            uow=uow, ai=self.ai, settings=self.settings
        )
        self.connectors = ConnectorService(uow=uow, documents=self.documents)
        self.chats = ChatService(uow=uow, ai=self.ai)
        self.system = SystemService(
            uow=uow, bootstrap=bootstrap, settings=self.settings, ai=self.ai
        )
        self._worker = Worker(
            uow=uow,
            ingestion=IngestionService(uow=uow, ai=self.ai),
            ai=self.ai,
            settings=self.settings,
        )
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        await asyncio.to_thread(upgrade_to_head, settings=self.bootstrap)
        self.ai.configure(await self.settings.load())
        if setup_token := await self.setup.start():
            # Printed, not logged: it must reach the operator whatever the
            # logging configuration is.
            print(
                f"\nAtlas needs setting up. Setup token: {setup_token}\n",
                flush=True,
            )
        self._tasks = [
            asyncio.create_task(_keep_running("monitor", self.ai.monitor)),
            asyncio.create_task(_keep_running("worker", self._worker.run)),
        ]

    async def stop(self) -> None:
        self._worker.stop()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._engine.dispose()


async def _keep_running(name: str, run: Callable[[], Awaitable[None]]) -> None:
    """A background task must survive a transient failure."""
    while True:
        try:
            await run()
            return
        except Exception:
            logger.exception("the %s task failed; restarting", name)
            await asyncio.sleep(_RESTART_DELAY_SECONDS)
