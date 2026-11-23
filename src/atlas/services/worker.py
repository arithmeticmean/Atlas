"""The background worker: drains the ingestion queue, and now and then
sweeps stored files no document refers to.

One asyncio task, started with the app. Each queue operation is its own short
unit of work. A job is retried until ``ingest_max_attempts``, then left
failed; a file that cannot be parsed is not retried at all. A crash mid-job
leaves it ``processing``, and the next start requeues it.
"""

import asyncio
import logging
import time

from atlas.core.parsing.errors import ParsingError
from atlas.models.job import IngestionJob
from atlas.repository.uow import UnitOfWorkFactory
from atlas.services.ai import AIRuntime
from atlas.services.ingestion import IngestionService
from atlas.services.settings import SettingsService

logger = logging.getLogger(__name__)


class Worker:
    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        ingestion: IngestionService,
        ai: AIRuntime,
        settings: SettingsService,
        sweep_every: float = 3600.0,
    ) -> None:
        self._uow = uow
        self._ingestion = ingestion
        self._ai = ai
        self._settings = settings
        self._sweep_every = sweep_every
        self._stopping = asyncio.Event()

    async def run(self) -> None:
        async with self._uow() as uow:
            requeued = await uow.jobs.reset_stale()
        if requeued:
            logger.info("requeued %d interrupted job(s)", requeued)
        next_sweep = time.monotonic()
        while not self._stopping.is_set():
            if time.monotonic() >= next_sweep:
                await self._sweep()
                next_sweep = time.monotonic() + self._sweep_every
            # While embeddings are down, wait: running a job now would only
            # burn its retries.
            job = await self._claim() if self._ai.can_index else None
            if job is not None:
                await self._process(job)
            else:
                await self._idle()

    def stop(self) -> None:
        self._stopping.set()

    async def _claim(self) -> IngestionJob | None:
        async with self._uow() as uow:
            job = await uow.jobs.claim()
        if job is None:
            self._ai.queue_drained()
        return job

    async def _process(self, job: IngestionJob) -> None:
        try:
            chunks = await self._ingestion.ingest(job.document_id)
        except Exception as exc:
            attempts = self._settings.current.ingest_max_attempts
            unparsable = isinstance(exc, ParsingError)
            retry = job.attempts < attempts and not unparsable
            if not unparsable:
                self._ai.request_check()
            async with self._uow() as uow:
                if (current := await uow.jobs.get(job.id)) is not None:
                    current.fail(str(exc), retry=retry)
            logger.warning(
                "indexing %s failed (attempt %d/%d): %s",
                job.document_id,
                job.attempts,
                attempts,
                exc,
            )
            return
        async with self._uow() as uow:
            if (current := await uow.jobs.get(job.id)) is not None:
                current.finish()
        logger.info("indexed %s: %d chunk(s)", job.document_id, chunks)

    async def _sweep(self) -> None:
        try:
            async with self._uow() as uow:
                removed = await uow.documents.sweep_files()
        except Exception:
            logger.warning("file sweep failed", exc_info=True)
            return
        if removed:
            logger.info("removed %d unused file(s)", removed)

    async def _idle(self) -> None:
        poll = self._settings.current.ingest_poll_interval_seconds
        try:
            await asyncio.wait_for(self._stopping.wait(), timeout=poll)
        except TimeoutError:
            pass
