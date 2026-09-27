"""Managed connector endpoints: CRUD + health check + on-demand sync.

Connectors belong to a project and are managed by its moderators (owner or a
project admin) -- every route is gated by ``ProjectModeratorCtx``. Syncing
pulls a connector's current contents through the same intake as an upload
(queued for background ingestion) and records the outcome. Secrets in
``config`` (e.g. access tokens) are redacted in responses.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from service.api.dependencies import (
    ProjectModeratorCtx,
    get_connector_manager,
    require_ready,
)
from service.core.connector_manager import (
    ConnectorManager,
    InvalidConnectorConfig,
    SyncResult,
    UnknownConnector,
)
from service.models import Connector

router = APIRouter(
    prefix="/projects/{project_id}/connectors", tags=["connectors"]
)

ManagerDep = Annotated[ConnectorManager, Depends(get_connector_manager)]

_SECRET_KEYS = {"access_token"}


def _redact(config: dict[str, Any]) -> dict[str, Any]:
    return {
        key: ("***" if key in _SECRET_KEYS and value else value)
        for key, value in config.items()
    }


class ConnectorCreate(BaseModel):
    type: str = Field(examples=["url", "google_drive"])
    name: str = Field(min_length=1)
    config: dict[str, Any]


class ConnectorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class ConnectorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    name: str
    config: dict[str, Any]
    enabled: bool
    created_at: datetime | None
    updated_at: datetime | None
    last_synced_at: datetime | None
    last_sync_status: str | None
    last_sync_detail: str | None


class HealthResponse(BaseModel):
    healthy: bool
    detail: str


class SyncResponse(BaseModel):
    connector_id: str
    status: str
    imported: int
    errors: int
    detail: str
    results: list[dict[str, Any]]


def _to_response(connector: Connector) -> ConnectorResponse:
    connector.config = _redact(connector.config)
    return ConnectorResponse.model_validate(connector)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_connector(
    ctx: ProjectModeratorCtx, manager: ManagerDep, body: ConnectorCreate
) -> ConnectorResponse:
    try:
        connector = await manager.create(
            project_id=ctx.project.id,
            type=body.type,
            name=body.name,
            config=body.config,
        )
    except InvalidConnectorConfig as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_response(connector)


@router.get("")
async def list_connectors(
    ctx: ProjectModeratorCtx, manager: ManagerDep
) -> list[ConnectorResponse]:
    return [
        _to_response(c)
        for c in await manager.list(project_id=ctx.project.id)
    ]


@router.get("/{connector_id}")
async def get_connector(
    ctx: ProjectModeratorCtx, manager: ManagerDep, connector_id: str
) -> ConnectorResponse:
    try:
        return _to_response(
            await manager.get(connector_id, project_id=ctx.project.id)
        )
    except UnknownConnector as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{connector_id}")
async def update_connector(
    ctx: ProjectModeratorCtx,
    manager: ManagerDep,
    connector_id: str,
    body: ConnectorUpdate,
) -> ConnectorResponse:
    try:
        connector = await manager.update(
            connector_id,
            project_id=ctx.project.id,
            name=body.name,
            config=body.config,
            enabled=body.enabled,
        )
    except UnknownConnector as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidConnectorConfig as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_response(connector)


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connector(
    ctx: ProjectModeratorCtx, manager: ManagerDep, connector_id: str
) -> Response:
    await manager.delete(connector_id, project_id=ctx.project.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{connector_id}/health")
async def health_connector(
    ctx: ProjectModeratorCtx, manager: ManagerDep, connector_id: str
) -> HealthResponse:
    try:
        healthy, detail = await manager.health(
            connector_id, project_id=ctx.project.id
        )
    except UnknownConnector as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return HealthResponse(healthy=healthy, detail=detail)


@router.post("/{connector_id}/sync", dependencies=[Depends(require_ready)])
async def sync_connector(
    ctx: ProjectModeratorCtx, manager: ManagerDep, connector_id: str
) -> SyncResponse:
    try:
        result: SyncResult = await manager.sync(
            connector_id, project_id=ctx.project.id
        )
    except UnknownConnector as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SyncResponse(
        connector_id=result.connector_id,
        status=result.status,
        imported=result.imported,
        errors=result.errors,
        detail=result.detail,
        results=[
            {
                "filename": r.filename,
                "status": r.status,
                "document_id": r.document_id,
                "error": r.error,
            }
            for r in result.results
        ],
    )
