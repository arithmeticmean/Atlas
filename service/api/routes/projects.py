"""Project + membership endpoints -- the tenancy control plane.

* ``/projects``                     create (owner) / list (scoped to caller)
* ``/projects/{id}``                read (member) / delete (owner)
* ``/projects/{id}/members``        list (member) / add existing user (mod) /
                                    remove (mod)
* ``/projects/{id}/invites``        mint an invite that creates an account and
                                    joins it to the project (mod)

Authorization comes from :class:`~service.core.projects.ProjectService`: the
global owner may act on every project; a project admin moderates their own; a
member
may read. The ``ProjectMemberCtx`` / ``ProjectModeratorCtx`` dependencies apply
those checks (and 404 an unknown project) before the handler runs.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from service.api.dependencies import (
    CurrentPrincipal,
    ProjectMemberCtx,
    ProjectModeratorCtx,
    get_auth_service,
    get_membership_services,
    get_project_service,
)
from service.core.auth import AuthService, PermissionDenied
from service.core.projects import ProjectError, ProjectService
from service.storage.store import UserStore

router = APIRouter(prefix="/projects", tags=["projects"])

ProjectSvc = Annotated[ProjectService, Depends(get_project_service)]
# Project + user store on one session (see get_membership_services).
MembershipSvcs = Annotated[
    tuple[ProjectService, UserStore], Depends(get_membership_services)
]
AuthSvc = Annotated[AuthService, Depends(get_auth_service)]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectResponse(BaseModel):
    id: str
    name: str
    created_by: str
    created_at: datetime | None
    role: str | None = None  # the caller's role, when known


class MemberResponse(BaseModel):
    user_id: str
    email: str | None
    username: str | None
    role: str
    created_at: datetime | None


class MemberAdd(BaseModel):
    email: str
    role: Literal["admin", "member"] = "member"


class InviteCreate(BaseModel):
    role: Literal["admin", "member"] = "member"


class InviteResponse(BaseModel):
    invite_token: str
    project_role: str


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(
    principal: CurrentPrincipal, service: ProjectSvc, body: ProjectCreate
) -> ProjectResponse:
    """Create a project. Owner only."""
    try:
        project = await service.create(name=body.name, creator=principal)
    except PermissionDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return ProjectResponse(
        id=project.id,
        name=project.name,
        created_by=project.created_by,
        created_at=project.created_at,
        role="owner",
    )


@router.get("")
async def list_projects(
    principal: CurrentPrincipal, service: ProjectSvc
) -> list[ProjectResponse]:
    """List the projects visible to the caller (owner sees all)."""
    projects = await service.list_visible(principal)
    out: list[ProjectResponse] = []
    for p in projects:
        out.append(
            ProjectResponse(
                id=p.id,
                name=p.name,
                created_by=p.created_by,
                created_at=p.created_at,
                role=await service.project_role(principal, p.id),
            )
        )
    return out


@router.get("/{project_id}")
async def get_project(ctx: ProjectMemberCtx) -> ProjectResponse:
    return ProjectResponse(
        id=ctx.project.id,
        name=ctx.project.name,
        created_by=ctx.project.created_by,
        created_at=ctx.project.created_at,
        role=ctx.role,
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    ctx: ProjectMemberCtx, service: ProjectSvc
) -> Response:
    """Delete a project (and its memberships). Owner only."""
    try:
        await service.delete(ctx.project.id, ctx.principal)
    except PermissionDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/members")
async def list_members(
    ctx: ProjectMemberCtx, services: MembershipSvcs
) -> list[MemberResponse]:
    service, users = services
    members = await service.list_members(ctx.project.id)
    out: list[MemberResponse] = []
    for m in members:
        user = await users.get_by_id(m.user_id)
        out.append(
            MemberResponse(
                user_id=m.user_id,
                email=user.email if user else None,
                username=user.username if user else None,
                role=m.role,
                created_at=m.created_at,
            )
        )
    return out


@router.post(
    "/{project_id}/members", status_code=status.HTTP_201_CREATED
)
async def add_member(
    ctx: ProjectModeratorCtx,
    services: MembershipSvcs,
    body: MemberAdd,
) -> MemberResponse:
    """Add an existing user to the project by email (moderator).

    Granting ``admin`` is owner-only (enforced by the service). To onboard a
    brand-new user, mint an invite instead (``POST .../invites``).
    """
    service, users = services
    user = await users.get(body.email)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no user with that email (invite them instead)",
        )
    try:
        member = await service.add_member(
            project_id=ctx.project.id,
            user_id=user.id,
            role=body.role,
            actor=ctx.principal,
        )
    except PermissionDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except ProjectError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return MemberResponse(
        user_id=member.user_id,
        email=user.email,
        username=user.username,
        role=member.role,
        created_at=member.created_at,
    )


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(
    ctx: ProjectModeratorCtx, service: ProjectSvc, user_id: str
) -> Response:
    try:
        await service.remove_member(
            project_id=ctx.project.id, user_id=user_id, actor=ctx.principal
        )
    except PermissionDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{project_id}/invites", status_code=status.HTTP_201_CREATED
)
async def create_invite(
    ctx: ProjectModeratorCtx, auth: AuthSvc, body: InviteCreate
) -> InviteResponse:
    """Mint an invite link that creates an account and joins this project.

    A project admin may invite members; only the owner may invite admins
    (mirrors ``add_member``).
    """
    if body.role == "admin" and ctx.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only the owner can invite project admins",
        )
    token = auth.mint_project_invite(
        project_id=ctx.project.id, project_role=body.role
    )
    return InviteResponse(invite_token=token, project_role=body.role)
