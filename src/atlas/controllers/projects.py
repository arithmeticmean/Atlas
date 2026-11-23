"""Projects, and who is in them."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from atlas.controllers._common import (
    CurrentCaller,
    Page,
    PageQuery,
    ResponseModel,
    Services,
    page_request,
    problems,
    to_page,
)
from atlas.controllers.users import UserSummary
from atlas.models.project import ProjectRole, ProjectSort
from atlas.services.access import EffectiveRole

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectResponse(ResponseModel):
    id: str
    name: str
    created_by: str
    created_at: datetime | None
    updated_at: datetime | None
    my_role: EffectiveRole


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectListQuery(PageQuery):
    q: str | None = None
    sort: ProjectSort = "name"


class MemberResponse(ResponseModel):
    user_id: str
    user: UserSummary | None  # None once the account has been deleted
    role: ProjectRole
    created_at: datetime | None


class MemberAdd(BaseModel):
    user_id: str
    role: ProjectRole = "member"


class MemberUpdate(BaseModel):
    role: ProjectRole


class MemberListQuery(PageQuery):
    role: ProjectRole | None = None


@router.post(
    "", status_code=status.HTTP_201_CREATED, responses=problems(401, 403, 422)
)
async def create_project(
    services: Services, caller: CurrentCaller, body: ProjectCreate
) -> ProjectResponse:
    project = await services.projects.create(caller, name=body.name)
    return ProjectResponse.model_validate(project)


@router.get("", responses=problems(401))
async def list_projects(
    services: Services,
    caller: CurrentCaller,
    query: Annotated[ProjectListQuery, Query()],
) -> Page[ProjectResponse]:
    visible = await services.projects.list_visible(
        caller, page_request(query), q=query.q, sort=query.sort
    )
    return to_page(ProjectResponse, visible)


@router.get("/{project_id}", responses=problems(401, 404))
async def get_project(
    services: Services, caller: CurrentCaller, project_id: str
) -> ProjectResponse:
    project = await services.projects.get(caller, project_id)
    return ProjectResponse.model_validate(project)


@router.patch("/{project_id}", responses=problems(401, 403, 404, 422))
async def update_project(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    body: ProjectUpdate,
) -> ProjectResponse:
    project = await services.projects.rename(
        caller, project_id, name=body.name
    )
    return ProjectResponse.model_validate(project)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problems(401, 403, 404),
)
async def delete_project(
    services: Services, caller: CurrentCaller, project_id: str
) -> None:
    await services.projects.delete(caller, project_id)


@router.get("/{project_id}/members", responses=problems(401, 404))
async def list_members(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    query: Annotated[MemberListQuery, Query()],
) -> Page[MemberResponse]:
    members = await services.projects.list_members(
        caller, project_id, page_request(query), role=query.role
    )
    return to_page(MemberResponse, members)


@router.post(
    "/{project_id}/members",
    status_code=status.HTTP_201_CREATED,
    responses=problems(401, 403, 404, 409),
)
async def add_member(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    body: MemberAdd,
) -> MemberResponse:
    member = await services.projects.add_member(
        caller, project_id, user_id=body.user_id, role=body.role
    )
    return MemberResponse.model_validate(member)


@router.patch(
    "/{project_id}/members/{user_id}",
    responses=problems(401, 403, 404, 422),
)
async def update_member(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    user_id: str,
    body: MemberUpdate,
) -> MemberResponse:
    member = await services.projects.change_role(
        caller, project_id, user_id, role=body.role
    )
    return MemberResponse.model_validate(member)


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problems(401, 403, 404, 422),
)
async def remove_member(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    user_id: str,
) -> None:
    """``user_id=me`` leaves the project."""
    await services.projects.remove_member(caller, project_id, user_id)
