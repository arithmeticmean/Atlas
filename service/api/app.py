"""FastAPI application factory.

All JSON/stream endpoints live under ``/api``. When a built frontend exists
(``settings.frontend_dir``), the SPA is served at ``/`` with a catch-all that
returns ``index.html`` for client-side routes -- so FastAPI serves both the UI
and the API from one origin, no nginx/static server needed.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.dependencies import (
    bootstrap_owner,
    build_embedding_index,
    build_ingestion_worker,
)
from api.routes import (
    answer_router,
    auth_router,
    connectors_router,
    documents_router,
    health_router,
    projects_router,
    search_router,
)
from config import settings
from service.llm import check_chat_model

_SERVICE_ROOT = Path(__file__).resolve().parents[1]

_API_ROUTERS = (
    health_router,
    auth_router,
    projects_router,
    documents_router,
    search_router,
    answer_router,
    connectors_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Provision the embedding index, then run the background worker.

    ``prepare()`` probes the embedding provider (fail-fast if unreachable) and
    starts an in-place reindex if the configured model changed. The worker is
    built afterwards so its vector store points at the freshly wiped table, and
    it reports progress back so the index can detect when a reindex drains.
    """
    await bootstrap_owner()  # create the configured owner if it's missing

    index = build_embedding_index()
    await index.prepare()
    app.state.embedding_index = index

    # fail-fast on a bad LLM config too (bad key / model / endpoint), so it's
    # visible in the logs at startup rather than only when an answer is asked.
    await check_chat_model()

    worker = build_ingestion_worker(on_progress=index.note_job_processed)
    task = asyncio.create_task(worker.run())
    try:
        yield
    finally:
        worker.stop()
        await task


def _resolve_frontend_dir() -> Path:
    frontend = Path(settings.frontend_dir)
    if not frontend.is_absolute():
        frontend = _SERVICE_ROOT / frontend
    return frontend.resolve()


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built SPA at ``/`` (no-op if it hasn't been built)."""
    frontend = _resolve_frontend_dir()
    if not frontend.is_dir():
        return

    assets = frontend / "assets"
    if assets.is_dir():
        app.mount(
            "/assets", StaticFiles(directory=assets), name="assets"
        )

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        # /api/* is handled by the routers; anything else is the SPA. Serve a
        # real file when one matches (favicon, etc.), else index.html so
        # client-side routes and refreshes resolve.
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        candidate = (frontend / path).resolve()
        if path and candidate.is_file() and frontend in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(frontend / "index.html")


def create_app() -> FastAPI:
    app = FastAPI(title="Atlas", version="0.1.0", lifespan=lifespan)
    for router in _API_ROUTERS:
        app.include_router(router, prefix="/api")
    _mount_frontend(app)
    return app


app = create_app()
