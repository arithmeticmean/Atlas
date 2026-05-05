"""Health & observability endpoints, split by audience.

* ``GET /health``       -- public liveness (process is up).
* ``GET /health/ready`` -- public, minimal readiness booleans (503 until the
  embedding index is ready / not reindexing). Safe for orchestrator probes.
* ``GET /status``       -- owner/admin only; full diagnostics (providers,
  queue depth, reindex state). Gated because it reveals infra detail.
"""

from fastapi import APIRouter, Depends, Request, Response, status

from api.dependencies import _job_queue_uow, require_role
from config import settings
from service import EmbeddingIndex

router = APIRouter(tags=["health"])


def _index(request: Request) -> EmbeddingIndex | None:
    return getattr(request.app.state, "embedding_index", None)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(request: Request, response: Response) -> dict[str, bool]:
    index = _index(request)
    is_ready = index is not None and index.is_ready()
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "ready": is_ready,
        "reindexing": index is not None and not index.is_ready(),
    }


@router.get("/status", dependencies=[Depends(require_role("admin"))])
async def status_report(
    request: Request,
) -> dict[str, object]:
    index = _index(request)
    async with _job_queue_uow() as queue:
        queue_counts = await queue.counts()
    return {
        "ready": index.is_ready() if index else False,
        "embedding": index.diagnostics() if index else None,
        "llm": {
            "provider": settings.llm_provider,
            "model": settings.llm_model,
        },
        "queue": queue_counts,
    }
