"""Operations, split by audience.

* ``GET /health``          public: the process is up
* ``GET /health/ready``    public: 503 until Atlas can serve; for probes
* ``GET /system/info``     public: what the login page needs
* ``GET /system/status``   instance admins: providers, queue, index
* ``GET /system/network``  any signed-in caller: how to reach this instance
"""

from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from atlas.controllers._common import (
    CurrentCaller,
    ResponseModel,
    Services,
    problems,
)
from atlas.services.system import atlas_version

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class ReadinessResponse(ResponseModel):
    ready: bool
    reindexing: bool
    database: bool
    index: bool


class InfoResponse(BaseModel):
    name: str = "Atlas"
    version: str
    signup: Literal["invite_only"] = "invite_only"
    needs_setup: bool


class ProviderStatusResponse(ResponseModel):
    provider: str
    model: str
    ok: bool
    detail: str


class StatusResponse(ResponseModel):
    version: str
    schema_version: str | None
    readiness: ReadinessResponse
    embedding: ProviderStatusResponse
    llm: ProviderStatusResponse
    queue: dict[str, int]
    index_chunks: int | None


class FileTypesResponse(BaseModel):
    extractable: list[str]
    plain_text: list[str]


class NetworkResponse(ResponseModel):
    bound_host: str
    port: int
    loopback_only: bool
    addresses: list[str]


@router.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(version=atlas_version())


@router.get(
    "/health/ready",
    responses={503: {"model": ReadinessResponse, "description": "not ready"}},
)
async def ready(services: Services, response: Response) -> ReadinessResponse:
    """The same body either way; only the status code changes."""
    readiness = await services.system.readiness()
    if not readiness.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse.model_validate(readiness)


@router.get("/system/info")
async def info(services: Services) -> InfoResponse:
    return InfoResponse(
        version=atlas_version(),
        needs_setup=await services.setup.needs_setup(),
    )


@router.get("/system/status", responses=problems(401, 403))
async def status_report(
    services: Services, caller: CurrentCaller
) -> StatusResponse:
    report = await services.system.status(caller)
    return StatusResponse.model_validate(report)


@router.get("/system/file-types", responses=problems(401))
async def file_types(
    services: Services, caller: CurrentCaller
) -> FileTypesResponse:
    """What can be uploaded, for the upload screen."""
    return FileTypesResponse.model_validate(services.system.file_types())


@router.get("/system/network", responses=problems(401))
async def network(
    services: Services, caller: CurrentCaller
) -> NetworkResponse:
    return NetworkResponse.model_validate(services.system.network())
