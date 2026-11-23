"""Invites: the only way into an instance after setup.

Tokens travel in request bodies, never in an API path, so they do not end up
in access logs. Invites are signed tokens for now, so they cannot be listed or
revoked yet: those two routes answer 501.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from atlas.controllers._common import (
    CurrentCaller,
    OptionalCaller,
    ResponseModel,
    Services,
    problems,
)
from atlas.controllers.auth import start_session
from atlas.controllers.users import UserResponse, UserSummary
from atlas.models.project import ProjectRole
from atlas.models.user import AssignableRole, UserRole
from atlas.services.invites import Grant

router = APIRouter(prefix="/invites", tags=["invites"])


class InviteProjectGrant(BaseModel):
    project_id: str
    role: ProjectRole = "member"


class InviteProjectResponse(ResponseModel):
    project_id: str
    project_name: str
    role: ProjectRole


class InviteCreate(BaseModel):
    email: str | None = Field(
        default=None,
        max_length=320,
        description="when set, only this address can accept the invite",
    )
    role: AssignableRole = "member"
    projects: list[InviteProjectGrant] = Field(default_factory=list)
    expires_in_hours: int = Field(default=72, ge=1, le=24 * 30)


class InvitePreviewResponse(ResponseModel):
    invited_by: UserSummary | None
    role: UserRole
    projects: list[InviteProjectResponse]
    email: str | None
    expires_at: datetime


class InviteCreated(BaseModel):
    invite: InvitePreviewResponse
    token: str = Field(description="shown once")
    url: str


class InviteToken(BaseModel):
    token: str = Field(min_length=1)


class InviteAccept(InviteToken):
    # Required when signing up; left out when a signed-in user only joins.
    email: str | None = Field(
        default=None, min_length=3, max_length=320, pattern=r"^.+@.+$"
    )
    username: str | None = Field(default=None, min_length=3, max_length=64)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class InviteAccepted(BaseModel):
    user: UserResponse
    # Only for a newly created account; a signed-in user keeps their session.
    access_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses=problems(401, 403, 404, 422),
)
async def create_invite(
    services: Services, caller: CurrentCaller, body: InviteCreate
) -> InviteCreated:
    token, preview = await services.invites.create(
        caller,
        role=body.role,
        projects=[Grant(p.project_id, p.role) for p in body.projects],
        email=body.email,
        expires_in=timedelta(hours=body.expires_in_hours),
    )
    return InviteCreated(
        invite=InvitePreviewResponse.model_validate(preview),
        token=token,
        url=f"/#/join/{token}",
    )


@router.get("", responses=problems(401, 501))
async def list_invites(
    services: Services, caller: CurrentCaller
) -> list[InvitePreviewResponse]:
    await services.invites.list_invites(caller)
    return []


@router.delete(
    "/{invite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problems(401, 501),
)
async def revoke_invite(
    services: Services, caller: CurrentCaller, invite_id: str
) -> None:
    await services.invites.revoke(caller, invite_id)


@router.post("/resolve", responses=problems(401))
async def resolve_invite(
    services: Services, body: InviteToken
) -> InvitePreviewResponse:
    """Public: lets the signup page say who invited you, and to what."""
    return InvitePreviewResponse.model_validate(
        await services.invites.resolve(body.token)
    )


@router.post(
    "/accept",
    status_code=status.HTTP_201_CREATED,
    responses=problems(401, 403, 409, 422),
)
async def accept_invite(
    services: Services,
    caller: OptionalCaller,
    body: InviteAccept,
    request: Request,
    response: Response,
) -> InviteAccepted:
    """Public. Signed out: creates the account and signs it in. Signed in:
    joins the invite's projects."""
    user, tokens = await services.invites.accept(
        body.token,
        caller,
        email=body.email,
        username=body.username,
        password=body.password,
    )
    if tokens is None:
        return InviteAccepted(user=UserResponse.model_validate(user))
    session = start_session(request, response, services, user, tokens)
    return InviteAccepted(
        user=session.user,
        access_token=session.access_token,
        expires_in=session.expires_in,
    )
