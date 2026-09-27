"""Ingestion job-queue port.

A durable work list for the background embedding step. Producers (upload, any
connector) call :meth:`JobQueue.enqueue` after a document's bytes are in the
file store; the worker (:mod:`service.core.worker`) drains it via
:meth:`claim`, running one document's ingestion per job.

The queue is deliberately tiny and backend-agnostic: the SQL adapter in
``storage/sql/jobs.py`` implements it against a table, but a Redis/broker
adapter could satisfy the same port with no change to callers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(slots=True)
class ClaimedJob:
    """A job the worker has taken ownership of (moved to ``processing``)."""

    id: str
    document_id: str
    attempts: int


class JobQueue(ABC):
    @abstractmethod
    async def enqueue(self, document_id: str) -> str:
        """Add a queued job for ``document_id``; return the new job id."""

    @abstractmethod
    async def claim(self) -> ClaimedJob | None:
        """Atomically take the oldest queued job (``-> processing``).

        Returns ``None`` when the queue is empty. Increments the job's attempt
        counter.
        """

    @abstractmethod
    async def mark_done(self, job_id: str) -> None:
        """Mark a claimed job finished."""

    @abstractmethod
    async def mark_failed(
        self, job_id: str, error: str, *, retry: bool
    ) -> None:
        """Record a failure; requeue the job when ``retry`` is set."""

    @abstractmethod
    async def reset_stale(self) -> int:
        """Requeue jobs stuck in ``processing`` (crash recovery).

        Called once at worker startup; returns how many were requeued.
        """

    @abstractmethod
    async def counts(self) -> dict[str, int]:
        """Return job counts keyed by status (queued/processing/done/failed).

        Backs ``/status`` observability and reindex drain-detection.
        """
