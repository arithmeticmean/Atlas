"""The live AI components, and their health.

Holds the current chat model, vector store and chunker, and is the one place
that rebuilds them when settings change. Atlas starts and serves even when a
provider is down: ``monitor`` keeps checking, and recovers without a restart.
"""

import asyncio
import logging
from typing import BinaryIO, NamedTuple

from langchain_community.vectorstores import LanceDB
from langchain_core.documents import Document as Chunk
from langchain_core.language_models import BaseChatModel

from atlas.config import Settings
from atlas.core.parsing.pipeline import FileChunker, FileInput
from atlas.core.providers.factory import (
    ProviderHealth,
    chat_model_from,
    check_chat_model,
    check_embeddings,
    embeddings_from,
)
from atlas.core.vector_store import (
    build_vector_store,
    chunk_count,
    confirm_embedding_model,
    document_chunks,
    document_filter,
    index_document,
    project_filter,
)
from atlas.models.document import Document
from atlas.repository.uow import UnitOfWorkFactory
from atlas.services.errors import NotReady

logger = logging.getLogger(__name__)

_RETRY_SECONDS = 30
_NOT_CHECKED = ProviderHealth(False, "not checked yet")


class AIHealth(NamedTuple):
    chat: ProviderHealth
    embeddings: ProviderHealth


class AIRuntime:
    def __init__(self, *, uow: UnitOfWorkFactory) -> None:
        self._uow = uow
        self._settings: Settings | None = None
        self._chunker: FileChunker | None = None
        self._llm: BaseChatModel | None = None
        self._store: LanceDB | None = None
        self._health = AIHealth(_NOT_CHECKED, _NOT_CHECKED)
        self._reindexing = False
        # A store swap must not happen in the middle of indexing a document.
        self._index_lock = asyncio.Lock()
        self._check_requested = asyncio.Event()

    # -- lifecycle ---------------------------------------------------------

    def configure(self, settings: Settings) -> None:
        """Take new settings without calling any provider."""
        self._settings = settings
        self._chunker = FileChunker(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )

    async def apply(self, settings: Settings, *, reconnect: bool) -> None:
        self.configure(settings)
        if reconnect:
            await self._connect()

    async def monitor(self) -> None:
        """Connect at startup, retry while anything is down, and recheck when
        a real call fails. A healthy provider is never pinged, because each
        check can cost money."""
        while True:
            if self._check_requested.is_set() or not self._healthy:
                self._check_requested.clear()
                try:
                    await self._connect()
                except Exception:
                    logger.exception("could not connect the AI providers")
            try:
                await asyncio.wait_for(
                    self._check_requested.wait(), _RETRY_SECONDS
                )
            except TimeoutError:
                pass

    def request_check(self) -> None:
        """A provider call just failed: check health now."""
        self._check_requested.set()

    async def check(self, settings: Settings) -> AIHealth:
        chat, embeddings = await asyncio.gather(
            check_chat_model(settings=settings),
            check_embeddings(settings=settings),
        )
        return AIHealth(chat, embeddings)

    # -- state -------------------------------------------------------------

    @property
    def health(self) -> AIHealth:
        return self._health

    @property
    def reindexing(self) -> bool:
        return self._reindexing

    @property
    def can_index(self) -> bool:
        return self._store is not None and self._health.embeddings.ok

    @property
    def ready(self) -> bool:
        return self.can_index and not self._reindexing

    def require_ready(self) -> None:
        if not self.ready:
            detail = (
                "reindexing documents"
                if self._reindexing
                else f"embeddings: {self._health.embeddings.detail}"
            )
            raise NotReady(detail, code="index_not_ready")

    def queue_drained(self) -> None:
        """The worker found nothing left to do."""
        if self._reindexing:
            logger.info("reindex complete")
        self._reindexing = False

    def chat_tools(self) -> tuple[BaseChatModel, LanceDB, Settings]:
        if self._llm is None or self._store is None or self._settings is None:
            raise NotReady("the AI models are not ready", code="ai_not_ready")
        return self._llm, self._store, self._settings

    @property
    def title_model(self) -> BaseChatModel | None:
        return self._llm

    # -- the index ---------------------------------------------------------

    async def index(self, document: Document, content: BinaryIO) -> int:
        async with self._index_lock:
            if self._store is None or self._chunker is None:
                raise NotReady("the vector store is not ready")
            file = FileInput(
                content,
                filename=document.title,
                mime_type=document.mime_type,
            )
            return await index_document(
                self._store,
                project_id=document.project_id,
                document_id=document.id,
                batches=self._chunker.astream(file),
            )

    async def remove_document(self, document_id: str) -> None:
        if self._store is not None:
            await self._store.adelete(filter=document_filter(document_id))

    async def remove_project(self, project_id: str) -> None:
        if self._store is not None:
            await self._store.adelete(filter=project_filter(project_id))

    async def chunks(self, document_id: str) -> list[Chunk]:
        if self._store is None:
            return []
        return await document_chunks(self._store, document_id)

    async def chunk_count(self) -> int | None:
        return None if self._store is None else await chunk_count(self._store)

    # -- internals ---------------------------------------------------------

    @property
    def _healthy(self) -> bool:
        return (
            self._store is not None
            and self._health.chat.ok
            and self._health.embeddings.ok
        )

    async def _connect(self) -> None:
        settings = self._settings
        if settings is None:
            raise RuntimeError("the AI runtime is not configured")
        self._health = await self.check(settings)
        try:
            self._llm = chat_model_from(settings=settings)
        except ValueError:
            self._llm = None  # a key is missing; the health says which
        async with self._index_lock:
            await self._open_store(settings)

    async def _open_store(self, settings: Settings) -> None:
        try:
            store, needs_reindex = await asyncio.to_thread(
                build_vector_store,
                settings=settings,
                embeddings=embeddings_from(settings=settings),
            )
        except Exception as exc:
            self._store = None
            logger.warning("the vector store is unavailable: %s", exc)
            return
        self._store = store
        if needs_reindex:
            async with self._uow() as uow:
                await uow.jobs.clear_pending()
                document_ids = await uow.documents.requeue_all()
                for document_id in document_ids:
                    await uow.jobs.enqueue(document_id)
            await asyncio.to_thread(confirm_embedding_model, settings=settings)
            self._reindexing = bool(document_ids)
