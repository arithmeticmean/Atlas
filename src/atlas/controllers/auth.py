"""The caller's own session and account.

The access token goes in the JSON body and lives in the client's memory; the
refresh token only ever travels in an httpOnly cookie scoped to these routes.
Signup is not here: it is accepting an invite (``controllers/invites.py``).
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response, status
from pydantic import BaseModel, Field

from atlas.controllers._common import (
    REFRESH_COOKIE,
    REFRESH_COOKIE_PATH,
    CurrentCaller,
    Services,
    problems,
)
from atlas.controllers.users import UserResponse
from atlas.models.user import User
from atlas.services.auth import TokenPair
from atlas.services.errors import InvalidToken

router = APIRouter(prefix="/auth", tags=["auth"])

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


class LoginRequest(BaseModel):
    # Accepted exactly as the account was created: strict email validation
    # rejects the internal domains a self-hosted instance uses (*.local).
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="seconds until the access token ends")


class LoginResponse(AccessTokenResponse):
    user: UserResponse


class ProfileUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=64)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class PasswordReset(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


class SessionResponse(BaseModel):
    id: str
    user_agent: str | None
    ip: str | None
    created_at: datetime
    last_used_at: datetime
    current: bool


def set_refresh_cookie(
    request: Request, response: Response, services: Services, token: str
) -> None:
    minutes = services.settings.current.refresh_token_ttl_minutes
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=minutes * 60,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        samesite="strict",
        # Atlas is often reached over plain HTTP on a LAN, where browsers
        # would drop a Secure cookie.
        secure=request.url.scheme == "https",
    )


def start_session(
    request: Request,
    response: Response,
    services: Services,
    user: User,
    tokens: TokenPair,
) -> LoginResponse:
    set_refresh_cookie(request, response, services, tokens.refresh_token)
    return LoginResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        user=UserResponse.model_validate(user),
    )


@router.post("/login", responses=problems(401, 403))
async def login(
    services: Services,
    body: LoginRequest,
    request: Request,
    response: Response,
) -> LoginResponse:
    user, tokens = await services.auth.login(
        email=body.email, password=body.password
    )
    return start_session(request, response, services, user, tokens)


@router.post("/refresh", responses=problems(401, 403))
async def refresh(
    services: Services,
    request: Request,
    response: Response,
    refresh_token: RefreshCookie = None,
) -> AccessTokenResponse:
    if refresh_token is None:
        raise InvalidToken("missing refresh cookie", code="not_authenticated")
    tokens = await services.auth.refresh(refresh_token)
    set_refresh_cookie(request, response, services, tokens.refresh_token)
    return AccessTokenResponse(
        access_token=tokens.access_token, expires_in=tokens.expires_in
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    services: Services, response: Response, refresh_token: RefreshCookie = None
) -> None:
    """Works with an expired access token: only the cookie is needed."""
    await services.auth.logout(refresh_token)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


@router.get("/me", responses=problems(401, 404))
async def get_me(services: Services, caller: CurrentCaller) -> UserResponse:
    user = await services.users.get_profile(caller)
    return UserResponse.model_validate(user)


@router.patch("/me", responses=problems(401, 404, 409, 422))
async def update_me(
    services: Services, caller: CurrentCaller, body: ProfileUpdate
) -> UserResponse:
    user = await services.users.update_profile(caller, username=body.username)
    return UserResponse.model_validate(user)


@router.post(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problems(401, 422),
)
async def change_password(
    services: Services, caller: CurrentCaller, body: PasswordChange
) -> None:
    await services.auth.change_password(
        caller,
        current_password=body.current_password,
        new_password=body.new_password,
    )


@router.get("/sessions", responses=problems(401, 501))
async def list_sessions(
    services: Services, caller: CurrentCaller
) -> list[SessionResponse]:
    sessions = await services.auth.list_sessions(caller)
    return [SessionResponse.model_validate(s) for s in sessions]


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problems(401, 404, 501),
)
async def revoke_session(
    services: Services, caller: CurrentCaller, session_id: str
) -> None:
    await services.auth.revoke_session(caller, session_id)


@router.post(
    "/password-reset",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problems(401, 422),
)
async def reset_password(services: Services, body: PasswordReset) -> None:
    """Public: the token itself is the authorization."""
    await services.auth.reset_password(
        token=body.token, new_password=body.new_password
    )
