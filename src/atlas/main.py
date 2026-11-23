"""The application: one process serving the API and the built UI.

Configured entirely by environment variables::

    ATLAS_DATA_PATH   where everything is stored (default ~/.atlas)
    ATLAS_HOST        address to bind (default 127.0.0.1)
    ATLAS_PORT        port to bind (default 8000)
    ATLAS_MASTER_KEY  optional; generated into DATA_PATH/master.key if unset

Everything else is set in the app and stored in the database.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles

from atlas.config import BootstrapSettings
from atlas.container import Container
from atlas.controllers import (
    auth,
    chats,
    connectors,
    documents,
    invites,
    projects,
    settings,
    setup,
    system,
    users,
)
from atlas.controllers.errors import register_error_handlers
from atlas.middlewares.request_id import RequestIdMiddleware
from atlas.services.system import atlas_version

_STATIC_DIRECTORY = Path(__file__).parent / "static"
_CONTROLLERS = (
    setup,
    auth,
    users,
    invites,
    projects,
    documents,
    connectors,
    chats,
    settings,
    system,
)


def create_app(bootstrap: BootstrapSettings | None = None) -> FastAPI:
    container = Container(bootstrap or BootstrapSettings())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await container.start()
        yield
        await container.stop()

    app = FastAPI(
        title="Atlas",
        version=atlas_version(),
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.container = container
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)

    api = APIRouter(prefix="/api/v1")
    for controller in _CONTROLLERS:
        api.include_router(controller.router)
    app.include_router(api)

    # Last: it matches every path the API did not.
    if (_STATIC_DIRECTORY / "index.html").is_file():
        app.mount(
            "/", StaticFiles(directory=_STATIC_DIRECTORY, html=True), "ui"
        )
    return app


def main() -> None:
    bootstrap = BootstrapSettings()
    uvicorn.run(
        create_app(bootstrap), host=bootstrap.host, port=bootstrap.port
    )
