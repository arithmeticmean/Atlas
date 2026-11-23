"""The ingestion queue: a durable work list over the ``ingestion_jobs`` table.

Single worker. ``claim`` takes the oldest queued row and starts it in the
caller's unit of work, which commits the move to ``processing`` before any
work begins; a crash mid-ingest leaves it there, and ``reset_stale`` at the
next startup requeues it. For several workers on Postgres, ``claim`` is
where ``FOR UPDATE SKIP LOCKED`` would go.
"""

from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select, update

from atlas.models.base import utcnow
from atlas.models.job import IngestionJob
from atlas.repository.base import CrudRepository


class JobRepository(CrudRepository[IngestionJob]):
    model = IngestionJob

    async def enqueue(self, document_id: str) -> IngestionJob:
        return await self.add(IngestionJob(document_id=document_id))

    async def claim(self) -> IngestionJob | None:
        """The oldest queued job, started (``processing``, one more attempt);
        ``None`` when the queue is empty. Finish it with ``job.finish()`` or
        ``job.fail(...)`` in a later unit of work."""
        job = await self.session.scalar(
            select(IngestionJob)
            .where(IngestionJob.status == "queued")
            .order_by(IngestionJob.created_at)
            .limit(1)
        )
        if job is not None:
            job.start()
            await self.session.flush()
        return job

    async def clear_pending(self) -> None:
        """Forget queued work, before a reindex queues everything again."""
        await self.session.execute(
            delete(IngestionJob).where(
                IngestionJob.status.in_(("queued", "processing"))
            )
        )

    async def reset_stale(self) -> int:
        """Requeue jobs left ``processing`` by a crash; returns how many."""
        result = cast(
            CursorResult[Any],
            await self.session.execute(
                update(IngestionJob)
                .where(IngestionJob.status == "processing")
                .values(status="queued", updated_at=utcnow())
            ),
        )
        return result.rowcount

    async def counts(self) -> dict[str, int]:
        """Jobs per status, for ``/status`` and reindex drain detection."""
        rows = await self.session.execute(
            select(IngestionJob.status, func.count()).group_by(
                IngestionJob.status
            )
        )
        return {status: count for status, count in rows.tuples()}
