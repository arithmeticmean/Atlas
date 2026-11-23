"""Health, readiness and diagnostics."""

import asyncio
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

from sqlalchemy import text

from atlas.config import BootstrapSettings
from atlas.core.parsing.pipeline import FileKind, supported_file_types
from atlas.repository.migrate import current_revision
from atlas.repository.uow import UnitOfWorkFactory
from atlas.services import network
from atlas.services.access import Caller, require_instance_admin
from atlas.services.ai import AIRuntime
from atlas.services.settings import SettingsService


@dataclass(frozen=True, slots=True)
class Readiness:
    ready: bool
    reindexing: bool
    database: bool
    index: bool


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    provider: str
    model: str
    ok: bool
    detail: str


@dataclass(frozen=True, slots=True)
class StatusReport:
    version: str
    schema_version: str | None
    readiness: Readiness
    embedding: ProviderStatus
    llm: ProviderStatus
    queue: dict[str, int]
    index_chunks: int | None


def atlas_version() -> str:
    try:
        return version("atlas")
    except PackageNotFoundError:
        return "unknown"


class SystemService:
    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        bootstrap: BootstrapSettings,
        settings: SettingsService,
        ai: AIRuntime,
    ) -> None:
        self._uow = uow
        self._bootstrap = bootstrap
        self._settings = settings
        self._ai = ai

    async def readiness(self) -> Readiness:
        try:
            async with self._uow() as uow:
                await uow.session.execute(text("SELECT 1"))
            database = True
        except Exception:
            database = False
        return Readiness(
            ready=database and self._ai.ready,
            reindexing=self._ai.reindexing,
            database=database,
            index=self._ai.can_index,
        )

    async def status(self, caller: Caller) -> StatusReport:
        require_instance_admin(caller)
        async with self._uow() as uow:
            queue = await uow.jobs.counts()
        settings = self._settings.current
        health = self._ai.health
        return StatusReport(
            version=atlas_version(),
            schema_version=await asyncio.to_thread(
                current_revision, settings=self._bootstrap
            ),
            readiness=await self.readiness(),
            embedding=ProviderStatus(
                settings.embedding_provider,
                settings.embedding_model,
                *health.embeddings,
            ),
            llm=ProviderStatus(
                settings.llm_provider, settings.llm_model, *health.chat
            ),
            queue=queue,
            index_chunks=await self._ai.chunk_count(),
        )

    @staticmethod
    def file_types() -> dict[FileKind, list[str]]:
        return supported_file_types()

    def network(self) -> network.Reachability:
        settings = self._settings.current
        return network.describe(settings.host, settings.port)
