"""Embedding-index lifecycle: lock file, dimension probe, auto reindex.

The embedding model is bound to the vector index (its dimension is baked into
the table), so it is a provisioning decision, not a runtime setting. This
component enforces that at startup:

* probe the configured model's dimension (fail-fast if the provider is
  unreachable -- you cannot ingest or search without embeddings),
* compare the configured ``(provider, model)`` against the **lock file**
  recorded next to the index,
* if they differ (or a previous reindex was interrupted), run an **in-place
  reindex**: wipe the vector table, rewrite the lock, and re-enqueue every
  document onto the existing job queue so the worker re-embeds them.

Only ``(provider, model)`` drift triggers a reindex -- nothing else lives in
the lock file, so changing the LLM, chunking, keys, etc. never does.

Crash-safety comes for free from the durable queue: a ``.reindexing`` sentinel
marks the window; if the process dies mid-reindex the sentinel survives and the
next startup re-wipes and re-enqueues from scratch (so no duplicate vectors),
draining through the same queue.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path

from langchain_core.embeddings import Embeddings

from storage.store import DocumentMetaStore, JobQueue

logger = logging.getLogger(__name__)

LOCK_VERSION = 1
_LOCK_NAME = "embedding.lock"
_SENTINEL_NAME = ".reindexing"
_PROBE_TEXT = "dimension probe"

ReindexUoW = Callable[
    [], AbstractAsyncContextManager[tuple[DocumentMetaStore, JobQueue]]
]
JobQueueUoW = Callable[[], AbstractAsyncContextManager[JobQueue]]
WipeTable = Callable[[], Awaitable[None]]


@dataclass(slots=True)
class LockInfo:
    provider: str
    model: str
    dim: int
    version: int


class EmbeddingIndex:
    def __init__(
        self,
        *,
        vector_path: str,
        provider: str,
        model: str,
        embeddings: Embeddings,
        reindex_uow: ReindexUoW,
        jobs_uow: JobQueueUoW,
        wipe_table: WipeTable,
    ) -> None:
        self._dir = Path(vector_path)
        self._provider = provider
        self._model = model
        self._embeddings = embeddings
        self._reindex_uow = reindex_uow
        self._jobs_uow = jobs_uow
        self._wipe_table = wipe_table
        self._ready = asyncio.Event()
        self._dim: int | None = None

    @property
    def _lock_path(self) -> Path:
        return self._dir / _LOCK_NAME

    @property
    def _sentinel_path(self) -> Path:
        return self._dir / _SENTINEL_NAME

    def is_ready(self) -> bool:
        return self._ready.is_set()

    def diagnostics(self) -> dict[str, object]:
        return {
            "provider": self._provider,
            "model": self._model,
            "dim": self._dim,
            "reindexing": not self.is_ready(),
        }

    async def prepare(self) -> None:
        """Startup check. Fail-fast on an unreachable embedding provider;
        otherwise mark ready or kick off an in-place reindex."""
        self._dim = await self._probe_dim()

        lock = self._read_lock()
        interrupted = self._sentinel_path.exists()
        drift = (
            lock is None
            or lock.provider != self._provider
            or lock.model != self._model
        )

        if interrupted or drift:
            reason = "resuming interrupted reindex" if interrupted else (
                "first run" if lock is None else "embedding model changed"
            )
            await self._start_reindex(reason)
        else:
            assert lock is not None  # drift is False => lock matched
            self._dim = lock.dim  # trust the index's recorded dimension
            self._ready.set()

    async def note_job_processed(self) -> None:
        """Called by the worker after each job; finishes a reindex once the
        queue has drained. A no-op outside a reindex window."""
        if self._ready.is_set() or not self._sentinel_path.exists():
            return
        async with self._jobs_uow() as queue:
            counts = await queue.counts()
        if counts.get("queued", 0) + counts.get("processing", 0) == 0:
            self._finish_reindex()

    # -- internals --------------------------------------------------------

    async def _probe_dim(self) -> int:
        try:
            vector = await self._embeddings.aembed_query(_PROBE_TEXT)
        except Exception as exc:
            hint = ""
            if self._provider == "ollama":
                hint = (
                    " Ollama must be reachable from *this* process: if Atlas "
                    "runs in a container/VM/WSL, localhost is not the host -- "
                    "set OLLAMA_BASE_URL (e.g. "
                    "http://host.docker.internal:11434) and start Ollama with "
                    "OLLAMA_HOST=0.0.0.0."
                )
            raise RuntimeError(
                f"embedding provider {self._provider!r} "
                f"(model {self._model!r}) is unreachable: {exc}.{hint}"
            ) from exc
        return len(vector)

    async def _start_reindex(self, reason: str) -> None:
        assert self._dim is not None
        logger.warning(
            "embedding reindex (%s): provider=%s model=%s dim=%d",
            reason,
            self._provider,
            self._model,
            self._dim,
        )
        self._ready.clear()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._sentinel_path.touch()
        await self._wipe_table()
        self._write_lock()

        enqueued = await self._enqueue_all()
        logger.warning("embedding reindex enqueued %d document(s)", enqueued)
        if enqueued == 0:
            self._finish_reindex()

    async def _enqueue_all(self) -> int:
        async with self._reindex_uow() as (meta, jobs):
            ids = await meta.all_ids()
            for document_id in ids:
                await meta.set_status(document_id, "queued")
                await jobs.enqueue(document_id)
        return len(ids)

    def _finish_reindex(self) -> None:
        self._sentinel_path.unlink(missing_ok=True)
        self._ready.set()
        logger.info("embedding reindex complete; instance ready")

    def _read_lock(self) -> LockInfo | None:
        if not self._lock_path.exists():
            return None
        data = json.loads(self._lock_path.read_text())
        return LockInfo(
            provider=data["provider"],
            model=data["model"],
            dim=data["dim"],
            version=data.get("version", 1),
        )

    def _write_lock(self) -> None:
        assert self._dim is not None
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock_path.write_text(
            json.dumps(
                {
                    "provider": self._provider,
                    "model": self._model,
                    "dim": self._dim,
                    "version": LOCK_VERSION,
                },
                indent=2,
            )
        )
