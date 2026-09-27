"""FastAPI application factory.

All JSON/stream endpoints live under ``/api``. When a built frontend exists
(``settings.frontend_dir``), the SPA is served at ``/`` with a catch-all that
returns ``index.html`` for client-side routes -- so FastAPI serves both the UI
and the API from one origin, no nginx/static server needed.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from service.api.dependencies import (
    build_embedding_index,
    build_ingestion_worker,
)
from service.api.routes import (
    answer_router,
    auth_router,
    connectors_router,
    documents_router,
    health_router,
    projects_router,
    search_router,
    users_router,
)
from service.config import settings
from service.core.llm import check_chat_model
from service.storage.sql.migrate import upgrade_to_head


def _require_signing_secret() -> None:
    """Refuse to serve without a token-signing secret.

    An empty secret is the uninitialized state, not a usable default: every
    issued JWT would be forgeable by anyone who guessed it. Failing loudly here
    beats an instance that looks healthy and is not.
    """
    if settings.jwt_secret:
        return
    raise RuntimeError(
        "no jwt_secret is configured, so access tokens cannot be signed "
        "safely. Run `atlas init` to create an instance (it generates one), "
        "or set ATLAS_JWT_SECRET to a long random value."
    )


_API_ROUTERS = (
    health_router,
    auth_router,
    projects_router,
    documents_router,
    search_router,
    answer_router,
    connectors_router,
    users_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Bring the instance up: schema, embedding index, then the worker.

    Migrations run first (an installed Atlas owns its own schema -- see
    storage/sql/migrate.py). ``prepare()`` then probes the embedding provider
    (fail-fast if unreachable) and starts an in-place reindex if the configured
    model changed. The worker is built afterwards so its vector store points at
    the freshly wiped table, and it reports progress back so the index can
    detect when a reindex drains.
    """
    _require_signing_secret()

    if settings.auto_migrate:
        # An installed instance has no `alembic` on PATH, so the application
        # owns its own schema. Idempotent, so this is a no-op once current.
        await asyncio.to_thread(upgrade_to_head)

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


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built SPA at ``/`` (no-op if it hasn't been built)."""
    frontend = settings.resolved_frontend_dir()
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


def _version() -> str:
    """The installed distribution's version, for the OpenAPI document."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("atlas")
    except PackageNotFoundError:
        return "0.0.0+unknown"


def create_app() -> FastAPI:
    app = FastAPI(title="Atlas", version=_version(), lifespan=lifespan)
    for router in _API_ROUTERS:
        app.include_router(router, prefix="/api")
    _mount_frontend(app)
    return app


app = create_app()
