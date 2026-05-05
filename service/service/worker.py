"""Background ingestion worker.

Drains the ``JobQueue`` and runs one document's ingestion per job. Runs as a
single asyncio task started in the app lifespan (see ``api/app.py``); it owns
its own DB sessions (one committed unit of work per queue operation) rather
than any request session.

Failure handling: a job is retried until ``max_attempts``, after which it is
marked ``failed``. Because ``claim`` commits the ``-> processing`` move before
work begins, a crash mid-ingest leaves the job in ``processing``; the next
startup's ``reset_stale`` requeues it (at-least-once semantics).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager

from service.ingestion import IngestionService
from storage.store import ClaimedJob, JobQueue

logger = logging.getLogger(__name__)

JobQueueUoW = Callable[[], AbstractAsyncContextManager[JobQueue]]
OnProgress = Callable[[], Awaitable[None]]


class IngestionWorker:
    def __init__(
        self,
        *,
        jobs: JobQueueUoW,
        ingestion: IngestionService,
        poll_interval: float,
        max_attempts: int,
        on_progress: OnProgress | None = None,
    ) -> None:
        self._jobs = jobs
        self._ingestion = ingestion
        self._poll = poll_interval
        self._max_attempts = max_attempts
        # Called after every processed job; lets the embedding index detect
        # when a reindex has drained. No-op in normal operation.
        self._on_progress = on_progress
        self._stop = asyncio.Event()

    async def run(self) -> None:
        """Loop until :meth:`stop`, processing queued jobs as they arrive."""
        requeued = await self._reset_stale()
        if requeued:
            logger.info("requeued %d stale job(s) at startup", requeued)

        while not self._stop.is_set():
            job = await self._claim()
            if job is None:
                await self._idle()
                continue
            await self._process(job)

    def stop(self) -> None:
        self._stop.set()

    async def _idle(self) -> None:
        # Sleep for the poll interval, but wake immediately on stop.
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=self._poll)
        except TimeoutError:
            pass

    async def _process(self, job: ClaimedJob) -> None:
        try:
            count = await self._ingestion.ingest(job.document_id)
        except Exception as exc:
            retry = job.attempts < self._max_attempts
            async with self._jobs() as q:
                await q.mark_failed(job.id, str(exc), retry=retry)
            logger.warning(
                "ingest failed for %s (attempt %d/%d, retry=%s): %s",
                job.document_id,
                job.attempts,
                self._max_attempts,
                retry,
                exc,
            )
        else:
            async with self._jobs() as q:
                await q.mark_done(job.id)
            logger.info("ingested %s: %d chunk(s)", job.document_id, count)

        if self._on_progress is not None:
            await self._on_progress()

    async def _reset_stale(self) -> int:
        async with self._jobs() as q:
            return await q.reset_stale()

    async def _claim(self) -> ClaimedJob | None:
        async with self._jobs() as q:
            return await q.claim()
