from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.dependencies import (
    CurrentPrincipal,
    get_auth_service,
    get_signup_services,
)
from service import (
    AuthService,
    EmailTaken,
    InactiveUser,
    InvalidCredentials,
    InvalidToken,
    LoginResult,
    PermissionDenied,
    ProjectService,
)

router = APIRouter(prefix="/auth", tags=["auth"])

ServiceDep = Annotated[AuthService, Depends(get_auth_service)]
SignupServices = Annotated[
    tuple[AuthService, ProjectService], Depends(get_signup_services)
]

class LoginRequest(BaseModel):
    # Login is a pure lookup + hash check, so it must accept the identifier and
    # password EXACTLY as the account was created with. Validating them here
    # (RFC-email via EmailStr, or a password charset) locks out legitimate
    # accounts -- notably the bootstrap owner, whose default address
    # ``owner@atlas.local`` EmailStr rejects (``.local`` is a reserved domain).
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class SignupRequest(BaseModel):
    # A light shape check (must contain "@") rather than full RFC validation:
    # Atlas is self-hosted and its default domain is internal (``*.local``),
    # which strict validators reject.
    email: str = Field(min_length=3, max_length=320, pattern=r"^.+@.+$")
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class PrincipalResponse(BaseModel):
    user_id: str
    email: str
    role: str


class InviteRequest(BaseModel):
    role: Literal["member", "admin", "owner"]


class InviteResponse(BaseModel):
    invite_token: str


def _to_response(result: LoginResult) -> TokenResponse:
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        token_type=result.token_type,
    )


@router.post("/signup/{invite_token}", status_code=status.HTTP_201_CREATED)
async def signup(
    services: SignupServices,
    r: SignupRequest,
    invite_token: str,
) -> TokenResponse:
    # Account creation and (for a project invite) the project join share one
    # session/transaction -- atomic onboarding, and no SQLite writer deadlock.
    service, projects = services
    # Peek at the invite first so we know, before creating anything, whether
    # this is a plain account invite or a project invite (which also joins).
    try:
        invite = service.read_invite(invite_token)
        result = await service.signup(
            email=r.email,
            username=r.username,
            password=r.password,
            invite_token=invite_token,
        )
    except InvalidToken as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    except EmailTaken as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    # A project invite additionally joins the new account to the project. The
    # signed invite is the authorization (accept_invite does no actor check).
    if invite.project_id:
        new_user_id = service.authenticate(result.access_token).user_id
        await projects.accept_invite(
            project_id=invite.project_id,
            user_id=new_user_id,
            role=invite.project_role or "member",
        )
    return _to_response(result)


@router.post("/invite", status_code=status.HTTP_201_CREATED)
async def create_invite(
    service: ServiceDep, principal: CurrentPrincipal, r: InviteRequest
) -> InviteResponse:
    """Mint a shareable invite link. Requires an admin (or owner) caller."""
    try:
        token = service.create_invite(principal, role=r.role)
    except PermissionDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return InviteResponse(invite_token=token)


@router.post("/login", status_code=status.HTTP_200_OK)
async def login(service: ServiceDep, r: LoginRequest) -> TokenResponse:
    try:
        result = await service.login(email=r.email, password=r.password)
    except InvalidCredentials as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    except InactiveUser as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return _to_response(result)


@router.post("/refresh", status_code=status.HTTP_200_OK)
async def refresh(service: ServiceDep, r: RefreshRequest) -> TokenResponse:
    try:
        result = await service.refresh(refresh_token=r.refresh_token)
    except (InvalidToken, InvalidCredentials) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    except InactiveUser as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return _to_response(result)


@router.get("/me")
async def me(principal: CurrentPrincipal) -> PrincipalResponse:
    """Return the caller's identity -- a minimal authenticated route."""
    return PrincipalResponse(
        user_id=principal.user_id,
        email=principal.email,
        role=principal.role,
    )
