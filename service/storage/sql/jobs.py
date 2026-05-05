"""SQLAlchemy adapter for the JobQueue port.

A single-worker durable queue over the ``ingestion_jobs`` table. ``claim``
selects the oldest queued row and flips it to ``processing`` in the same unit
of work; the guarded ``WHERE status='queued'`` update means that even if two
workers ever raced, only one would win the row. For multi-instance Postgres
deployments this is where ``FOR UPDATE SKIP LOCKED`` would go.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from storage.sql.models import IngestionJob
from storage.store.jobs import ClaimedJob, JobQueue


class SqlJobQueue(JobQueue):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(self, document_id: str) -> str:
        now = datetime.now(UTC)
        job = IngestionJob(
            id=uuid.uuid4().hex,
            document_id=document_id,
            status="queued",
            attempts=0,
            created_at=now,
            updated_at=now,
        )
        self._session.add(job)
        await self._session.flush()
        return job.id

    async def claim(self) -> ClaimedJob | None:
        row = (
            await self._session.execute(
                select(IngestionJob)
                .where(IngestionJob.status == "queued")
                .order_by(IngestionJob.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return None

        row.status = "processing"
        row.attempts += 1
        row.updated_at = datetime.now(UTC)
        await self._session.flush()
        return ClaimedJob(
            id=row.id, document_id=row.document_id, attempts=row.attempts
        )

    async def mark_done(self, job_id: str) -> None:
        await self._set(job_id, status="done")

    async def mark_failed(
        self, job_id: str, error: str, *, retry: bool
    ) -> None:
        await self._set(
            job_id,
            status="queued" if retry else "failed",
            last_error=error,
        )

    async def reset_stale(self) -> int:
        result = await self._session.execute(
            update(IngestionJob)
            .where(IngestionJob.status == "processing")
            .values(status="queued", updated_at=datetime.now(UTC))
        )
        # execute() returns a CursorResult for UPDATE, but is typed as Result.
        return int(result.rowcount)  # type: ignore[attr-defined]

    async def counts(self) -> dict[str, int]:
        rows = (
            await self._session.execute(
                select(IngestionJob.status, func.count()).group_by(
                    IngestionJob.status
                )
            )
        ).all()
        return {status: count for status, count in rows}

    async def _set(
        self, job_id: str, *, status: str, last_error: str | None = None
    ) -> None:
        row = await self._session.get(IngestionJob, job_id)
        if row is None:
            raise LookupError(f"job {job_id!r} not found")
        row.status = status
        if last_error is not None:
            row.last_error = last_error
        row.updated_at = datetime.now(UTC)
        await self._session.flush()
