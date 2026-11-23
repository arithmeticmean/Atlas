"""External sources that feed a project's documents.

Secrets are write-only: sent in ``secrets``, never returned. A response says
only which ones are set. Syncs run inside the request for now.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from atlas.controllers._common import (
    CurrentCaller,
    Page,
    PageQuery,
    ResponseModel,
    Services,
    page_request,
    problems,
    require_ready,
    to_page,
)

router = APIRouter(tags=["connectors"])

_PREFIX = "/projects/{project_id}/connectors"


class ConnectorType(BaseModel):
    type: str = Field(examples=["url", "google_drive"])
    name: str
    description: str
    config_schema: dict[str, Any] = Field(description="a JSON Schema")
    secret_fields: list[str]


class SyncItemError(ResponseModel):
    item: str
    message: str


class SyncResponse(ResponseModel):
    status: str
    imported: int
    unchanged: int
    failed: int
    errors: list[SyncItemError]


class ConnectorResponse(ResponseModel):
    id: str
    project_id: str
    type: str
    name: str
    config: dict[str, Any]
    secrets_set: list[str]
    enabled: bool
    last_synced_at: datetime | None
    last_sync_status: str | None
    last_sync_detail: str | None
    created_at: datetime | None
    updated_at: datetime | None


class ConnectorTest(BaseModel):
    type: str
    config: dict[str, Any]
    secrets: dict[str, str] = Field(default_factory=dict)


class ConnectorCreate(ConnectorTest):
    name: str = Field(min_length=1, max_length=200)


class ConnectorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    config: dict[str, Any] | None = None
    # A secret left out keeps its stored value.
    secrets: dict[str, str] | None = None
    enabled: bool | None = None


class ConnectorDeleteQuery(BaseModel):
    delete_documents: bool = False


class TestResult(BaseModel):
    ok: bool
    detail: str


@router.get("/connector-types", responses=problems(401))
async def list_connector_types(
    services: Services, caller: CurrentCaller
) -> list[ConnectorType]:
    return [
        ConnectorType(
            type=source.key,
            name=source.name,
            description=source.description,
            config_schema=source.config_model.model_json_schema(),
            secret_fields=list(source.secret_fields),
        )
        for source in services.connectors.list_types()
    ]


# Declared before /{connector_id} routes so "test" is not taken for an id.
@router.post(f"{_PREFIX}/test", responses=problems(401, 403, 404, 422))
async def test_new_connector(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    body: ConnectorTest,
) -> TestResult:
    ok, detail = await services.connectors.test_config(
        caller,
        project_id,
        type=body.type,
        config=body.config,
        secrets=body.secrets,
    )
    return TestResult(ok=ok, detail=detail)


@router.post(
    _PREFIX,
    status_code=status.HTTP_201_CREATED,
    responses=problems(401, 403, 404, 422),
)
async def create_connector(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    body: ConnectorCreate,
) -> ConnectorResponse:
    view = await services.connectors.create(
        caller,
        project_id,
        type=body.type,
        name=body.name,
        config=body.config,
        secrets=body.secrets,
    )
    return ConnectorResponse.model_validate(view)


@router.get(_PREFIX, responses=problems(401, 403, 404))
async def list_connectors(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    query: Annotated[PageQuery, Query()],
) -> Page[ConnectorResponse]:
    connectors = await services.connectors.list_connectors(
        caller, project_id, page_request(query)
    )
    return to_page(ConnectorResponse, connectors)


@router.get(f"{_PREFIX}/{{connector_id}}", responses=problems(401, 403, 404))
async def get_connector(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    connector_id: str,
) -> ConnectorResponse:
    view = await services.connectors.get(caller, project_id, connector_id)
    return ConnectorResponse.model_validate(view)


@router.patch(
    f"{_PREFIX}/{{connector_id}}", responses=problems(401, 403, 404, 422)
)
async def update_connector(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    connector_id: str,
    body: ConnectorUpdate,
) -> ConnectorResponse:
    view = await services.connectors.update(
        caller,
        project_id,
        connector_id,
        name=body.name,
        config=body.config,
        secrets=body.secrets,
        enabled=body.enabled,
    )
    return ConnectorResponse.model_validate(view)


@router.delete(
    f"{_PREFIX}/{{connector_id}}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problems(401, 403, 404, 501),
)
async def delete_connector(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    connector_id: str,
    query: Annotated[ConnectorDeleteQuery, Query()],
) -> None:
    await services.connectors.delete(
        caller,
        project_id,
        connector_id,
        delete_documents=query.delete_documents,
    )


@router.post(
    f"{_PREFIX}/{{connector_id}}/test", responses=problems(401, 403, 404)
)
async def test_connector(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    connector_id: str,
) -> TestResult:
    ok, detail = await services.connectors.test(
        caller, project_id, connector_id
    )
    return TestResult(ok=ok, detail=detail)


@router.post(
    f"{_PREFIX}/{{connector_id}}/sync",
    dependencies=[Depends(require_ready)],
    responses=problems(401, 403, 404, 409, 503),
)
async def sync_connector(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    connector_id: str,
) -> SyncResponse:
    result = await services.connectors.sync(caller, project_id, connector_id)
    return SyncResponse.model_validate(result)
