"""Accounts: your own profile, administration, and the first owner."""

from dataclasses import dataclass
from datetime import datetime

from atlas.models.base import utcnow
from atlas.models.project import ProjectRole
from atlas.models.user import User, UserRole, UserStatus
from atlas.repository.base import Conflict, Paged, PageRequest
from atlas.repository.uow import UnitOfWorkFactory
from atlas.services.access import Caller, require_instance_admin, require_owner
from atlas.services.errors import (
    AlreadyExists,
    InvalidInput,
    NotFound,
    PermissionDenied,
)
from atlas.services.security import (
    TokenCodec,
    hash_password,
    password_fingerprint,
)

_LOOKUP_LIMIT = 20


@dataclass(frozen=True, slots=True)
class UserMembership:
    project_id: str
    project_name: str
    role: ProjectRole


@dataclass(frozen=True, slots=True)
class UserDetail:
    id: str
    email: str
    username: str
    role: UserRole
    status: UserStatus
    created_at: datetime | None
    last_login_at: datetime | None
    memberships: list[UserMembership]


def _user_not_found() -> NotFound:
    return NotFound("user not found", code="user_not_found")


class UserService:
    def __init__(self, *, uow: UnitOfWorkFactory, tokens: TokenCodec) -> None:
        self._uow = uow
        self._tokens = tokens

    # -- your own account --------------------------------------------------

    async def get_profile(self, caller: Caller) -> User:
        async with self._uow() as uow:
            user = await uow.users.get(caller.user_id)
        if user is None:
            raise _user_not_found()
        return user

    async def update_profile(
        self, caller: Caller, *, username: str | None = None
    ) -> User:
        async with self._uow() as uow:
            user = await uow.users.get(caller.user_id)
            if user is None:
                raise _user_not_found()
            if username is not None and username != user.username:
                if await uow.users.by_username(username) is not None:
                    raise AlreadyExists(
                        "username taken", code="username_taken"
                    )
                user.username = username
        return user

    # -- administration ----------------------------------------------------

    async def list_users(
        self,
        caller: Caller,
        page: PageRequest,
        *,
        q: str | None = None,
        role: UserRole | None = None,
        status: UserStatus | None = None,
    ) -> Paged[User]:
        require_instance_admin(caller)
        async with self._uow() as uow:
            return await uow.users.page(page, q=q, role=role, status=status)

    async def lookup(self, caller: Caller, q: str) -> list[User]:
        """For the "add member" picker. Instance admins search everyone; a
        project admin only people in projects they manage, which they can
        already see. Anyone else joins through an invite."""
        async with self._uow() as uow:
            among = None
            if not caller.is_instance_admin:
                if not await uow.members.administers_any(caller.user_id):
                    raise PermissionDenied("requires managing a project")
                among = await uow.members.user_ids_moderated_by(caller.user_id)
            return await uow.users.search_active(
                q, limit=_LOOKUP_LIMIT, among=among
            )

    async def get(self, caller: Caller, user_id: str) -> UserDetail:
        """The account and the projects it belongs to."""
        require_instance_admin(caller)
        async with self._uow() as uow:
            user = await uow.users.get(user_id)
            if user is None:
                raise _user_not_found()
            projects = await uow.projects.list_for_member(user_id)
        return UserDetail(
            id=user.id,
            email=user.email,
            username=user.username,
            role=user.role,
            status=user.status,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
            memberships=[
                UserMembership(project.id, project.name, role)
                for project, role in projects
            ],
        )

    async def update(
        self,
        caller: Caller,
        user_id: str,
        *,
        role: UserRole | None = None,
        status: UserStatus | None = None,
    ) -> User:
        require_instance_admin(caller)
        async with self._uow() as uow:
            user = await uow.users.get(user_id)
            if user is None:
                raise _user_not_found()
            if user.role == "owner":
                raise PermissionDenied("the owner cannot be changed")
            if role is not None and role != user.role:
                if role == "owner":
                    raise InvalidInput("use transfer-ownership instead")
                # Making or unmaking admins is the owner's call.
                require_owner(caller)
                user.role = role
            if status is not None:
                if user.id == caller.user_id:
                    raise PermissionDenied("cannot change your own status")
                user.status = status
        return user

    async def delete(self, caller: Caller, user_id: str) -> None:
        """The account, its memberships and its chats."""
        require_instance_admin(caller)
        if user_id == caller.user_id:
            raise PermissionDenied("cannot delete yourself")
        async with self._uow() as uow:
            user = await uow.users.get(user_id)
            if user is None:
                raise _user_not_found()
            if user.role == "owner":
                raise PermissionDenied("the owner cannot be deleted")
            await uow.members.delete_for_user(user_id)
            await uow.chats.delete_for_user(user_id)
            await uow.users.delete(user)

    async def create_password_reset(
        self, caller: Caller, user_id: str
    ) -> tuple[str, datetime]:
        """A one-time reset token for an admin to hand over (no mail
        server is assumed)."""
        require_instance_admin(caller)
        async with self._uow() as uow:
            user = await uow.users.get(user_id)
        if user is None:
            raise _user_not_found()
        token = self._tokens.issue(
            "reset",
            {"sub": user.id, "pwd": password_fingerprint(user.password_hash)},
        )
        return token, utcnow() + self._tokens.lifetime("reset")

    async def transfer_ownership(self, caller: Caller, user_id: str) -> None:
        require_owner(caller)
        async with self._uow() as uow:
            new_owner = await uow.users.get(user_id)
            current = await uow.users.get(caller.user_id)
            if new_owner is None or current is None:
                raise _user_not_found()
            if new_owner.status != "active":
                raise InvalidInput("the new owner's account is not active")
            current.role = "admin"
            new_owner.role = "owner"

    # -- first run ---------------------------------------------------------

    async def create_owner(self, *, email: str, password: str) -> User:
        """Called by first-run setup. Idempotent: an existing owner is
        returned unchanged."""
        async with self._uow() as uow:
            if (existing := await uow.users.owner()) is not None:
                return existing
            try:
                return await uow.users.add(
                    User(
                        email=email,
                        username=email.split("@", 1)[0][:64],
                        password_hash=hash_password(password),
                        role="owner",
                    )
                )
            except Conflict as exc:
                raise AlreadyExists("email already registered") from exc
