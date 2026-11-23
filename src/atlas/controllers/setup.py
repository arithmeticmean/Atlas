"""First-run setup: claim a fresh instance with the token it printed."""

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from atlas.controllers._common import Services, problems
from atlas.controllers.auth import LoginResponse, start_session

router = APIRouter(prefix="/setup", tags=["setup"])


class SetupStatus(BaseModel):
    needs_setup: bool


class SetupRequest(BaseModel):
    token: str = Field(min_length=1)
    email: str = Field(min_length=3, max_length=320, pattern=r"^.+@.+$")
    password: str = Field(min_length=8, max_length=128)


@router.get("/status")
async def setup_status(services: Services) -> SetupStatus:
    return SetupStatus(needs_setup=await services.setup.needs_setup())


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses=problems(403, 409, 422),
)
async def complete_setup(
    services: Services,
    body: SetupRequest,
    request: Request,
    response: Response,
) -> LoginResponse:
    owner, tokens = await services.setup.complete(
        token=body.token, email=body.email, password=body.password
    )
    return start_session(request, response, services, owner, tokens)
