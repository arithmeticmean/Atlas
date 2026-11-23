"""Account administration, and the "add member" picker."""

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
from atlas.models.project import ProjectRole
from atlas.models.user import AssignableRole, UserRole, UserStatus

router = APIRouter(prefix="/users", tags=["users"])


class UserResponse(ResponseModel):
    id: str
    email: str
    username: str
    role: UserRole
    status: UserStatus
    created_at: datetime | None
    last_login_at: datetime | None


class UserSummary(ResponseModel):
    """Enough to recognise a person; nothing about status or credentials."""

    id: str
    username: str
    email: str


class UserMembership(ResponseModel):
    project_id: str
    project_name: str
    role: ProjectRole


class UserDetailResponse(UserResponse):
    memberships: list[UserMembership]


class UserListQuery(PageQuery):
    q: str | None = Field(default=None, description="email or username")
    role: UserRole | None = None
    status: UserStatus | None = None


class UserLookupQuery(BaseModel):
    q: str = Field(min_length=2, max_length=320)


class UserUpdate(BaseModel):
    role: AssignableRole | None = None
    status: UserStatus | None = None


class PasswordResetLink(BaseModel):
    token: str
    url: str
    expires_at: datetime


@router.get("", responses=problems(401, 403))
async def list_users(
    services: Services,
    caller: CurrentCaller,
    query: Annotated[UserListQuery, Query()],
) -> Page[UserResponse]:
    users = await services.users.list_users(
        caller,
        page_request(query),
        q=query.q,
        role=query.role,
        status=query.status,
    )
    return to_page(UserResponse, users)


# Declared before /{user_id} so "lookup" is not taken for an id.
@router.get("/lookup", responses=problems(401, 403))
async def lookup_users(
    services: Services,
    caller: CurrentCaller,
    query: Annotated[UserLookupQuery, Query()],
) -> list[UserSummary]:
    users = await services.users.lookup(caller, query.q)
    return [UserSummary.model_validate(user) for user in users]


@router.get("/{user_id}", responses=problems(401, 403, 404))
async def get_user(
    services: Services, caller: CurrentCaller, user_id: str
) -> UserDetailResponse:
    return UserDetailResponse.model_validate(
        await services.users.get(caller, user_id)
    )


@router.patch("/{user_id}", responses=problems(401, 403, 404, 422))
async def update_user(
    services: Services,
    caller: CurrentCaller,
    user_id: str,
    body: UserUpdate,
) -> UserResponse:
    user = await services.users.update(
        caller, user_id, role=body.role, status=body.status
    )
    return UserResponse.model_validate(user)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problems(401, 403, 404),
)
async def delete_user(
    services: Services, caller: CurrentCaller, user_id: str
) -> None:
    await services.users.delete(caller, user_id)


@router.post(
    "/{user_id}/password-reset",
    status_code=status.HTTP_201_CREATED,
    responses=problems(401, 403, 404),
)
async def create_password_reset(
    services: Services, caller: CurrentCaller, user_id: str
) -> PasswordResetLink:
    """No mail server is assumed: the admin passes the link on."""
    token, expires_at = await services.users.create_password_reset(
        caller, user_id
    )
    return PasswordResetLink(
        token=token, url=f"/#/reset/{token}", expires_at=expires_at
    )


@router.post(
    "/{user_id}/transfer-ownership",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problems(401, 403, 404, 422),
)
async def transfer_ownership(
    services: Services, caller: CurrentCaller, user_id: str
) -> None:
    await services.users.transfer_ownership(caller, user_id)
