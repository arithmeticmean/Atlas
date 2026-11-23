"""Invites: the only way into an instance.

For now an invite is a signed token carrying what it grants, with nothing
stored. So it can be created, previewed and accepted, but not listed or
revoked, and ``max_uses`` cannot be enforced -- all of that needs an invites
table, and says so until there is one.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast, get_args

from atlas.models.project import Project, ProjectMember, ProjectRole
from atlas.models.user import AssignableRole, User, UserRole
from atlas.repository.base import Conflict
from atlas.repository.uow import UnitOfWork, UnitOfWorkFactory
from atlas.services.access import Caller, load_project
from atlas.services.auth import TokenPair, issue_tokens
from atlas.services.errors import (
    AlreadyExists,
    InvalidInput,
    InvalidToken,
    PermissionDenied,
)
from atlas.services.security import TokenCodec, hash_password


@dataclass(frozen=True, slots=True)
class Grant:
    project_id: str
    role: ProjectRole


@dataclass(frozen=True, slots=True)
class InviteProject:
    project_id: str
    project_name: str
    role: ProjectRole


@dataclass(frozen=True, slots=True)
class InvitePreview:
    role: UserRole
    projects: list[InviteProject]
    email: str | None
    invited_by: User | None
    expires_at: datetime


class InviteService:
    def __init__(self, *, uow: UnitOfWorkFactory, tokens: TokenCodec) -> None:
        self._uow = uow
        self._tokens = tokens

    async def create(
        self,
        caller: Caller,
        *,
        role: UserRole = "member",
        projects: list[Grant] | None = None,
        email: str | None = None,
        expires_in: timedelta | None = None,
    ) -> tuple[str, InvitePreview]:
        """Instance admins may invite at any role below owner. A project
        admin may invite members, into projects they manage."""
        grants = projects or []
        if role == "owner":
            raise InvalidInput("nobody can be invited as owner")
        if role != "member" and not caller.is_instance_admin:
            raise PermissionDenied("only instance admins invite admins")
        async with self._uow() as uow:
            for grant in grants:
                await load_project(uow, caller, grant.project_id, admin=True)
        token = self._tokens.issue(
            "invite",
            {
                "by": caller.user_id,
                "role": role,
                "email": email,
                "projects": [[g.project_id, g.role] for g in grants],
            },
            lifetime=expires_in,
        )
        return token, await self.resolve(token)

    async def resolve(self, token: str) -> InvitePreview:
        """What accepting would grant. Public: the token is the key."""
        claims = self._tokens.read(token, "invite")
        async with self._uow() as uow:
            inviter = await uow.users.get(claims["by"])
            projects = await self._projects(uow, claims)
        return InvitePreview(
            role=claims["role"],
            projects=[
                InviteProject(project.id, project.name, role)
                for project, role in projects
            ],
            email=claims.get("email"),
            invited_by=inviter,
            expires_at=datetime.fromtimestamp(claims["exp"], UTC),
        )

    async def accept(
        self,
        token: str,
        caller: Caller | None,
        *,
        email: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> tuple[User, TokenPair | None]:
        """Signed out: create the account (and sign it in). Signed in: just
        join the invite's projects. Tokens are only returned for a new
        account."""
        claims = self._tokens.read(token, "invite")
        async with self._uow() as uow:
            if caller is None:
                user = await self._create_account(
                    uow,
                    claims,
                    email=email,
                    username=username,
                    password=password,
                )
            else:
                existing = await uow.users.get(caller.user_id)
                if existing is None:
                    raise InvalidToken("account no longer exists")
                user = existing
            for project, role in await self._projects(uow, claims):
                if await uow.members.find(project.id, user.id) is None:
                    await uow.members.add(
                        ProjectMember(
                            project_id=project.id, user_id=user.id, role=role
                        )
                    )
        tokens = issue_tokens(self._tokens, user) if caller is None else None
        return user, tokens

    async def list_invites(self, caller: Caller) -> list[object]:
        raise NotImplementedError("listing invites needs an invites table")

    async def revoke(self, caller: Caller, invite_id: str) -> None:
        raise NotImplementedError("revoking invites needs an invites table")

    @staticmethod
    async def _create_account(
        uow: UnitOfWork,
        claims: dict[str, object],
        *,
        email: str | None,
        username: str | None,
        password: str | None,
    ) -> User:
        if not (email and username and password):
            raise InvalidInput("email, username and password are required")
        invited = claims.get("email")
        if invited and str(invited).lower() != email.lower():
            raise PermissionDenied("this invite is for another address")
        role = cast(AssignableRole, claims["role"])  # from a signed token
        assert role in get_args(AssignableRole)
        try:
            return await uow.users.add(
                User(
                    email=email,
                    username=username,
                    password_hash=hash_password(password),
                    role=role,
                )
            )
        except Conflict as exc:
            raise AlreadyExists(
                "email or username already registered", code="account_exists"
            ) from exc

    @staticmethod
    async def _projects(
        uow: UnitOfWork, claims: dict[str, object]
    ) -> list[tuple[Project, ProjectRole]]:
        """The invite's projects that still exist."""
        found: list[tuple[Project, ProjectRole]] = []
        grants = claims.get("projects") or []
        assert isinstance(grants, list)
        for project_id, role in grants:
            if (project := await uow.projects.get(project_id)) is not None:
                found.append((project, role))
        return found
