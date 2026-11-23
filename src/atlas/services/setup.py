"""First-run setup: create the owner, with no command line involved.

A fresh instance is reachable before it has an owner, so claiming it needs a
one-time token that only someone who can see the server's output has.
"""

import asyncio
import secrets

from atlas.models.user import User
from atlas.repository.uow import UnitOfWorkFactory
from atlas.services.auth import TokenPair, issue_tokens
from atlas.services.errors import AlreadyExists, PermissionDenied
from atlas.services.security import TokenCodec
from atlas.services.users import UserService


class SetupService:
    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        users: UserService,
        tokens: TokenCodec,
    ) -> None:
        self._uow = uow
        self._users = users
        self._tokens = tokens
        self._setup_token: str | None = None
        self._lock = asyncio.Lock()

    async def needs_setup(self) -> bool:
        async with self._uow() as uow:
            return await uow.users.owner() is None

    async def start(self) -> str | None:
        """A new setup token if the instance has no owner yet."""
        if not await self.needs_setup():
            return None
        self._setup_token = secrets.token_urlsafe(32)
        return self._setup_token

    async def complete(
        self, *, token: str, email: str, password: str
    ) -> tuple[User, TokenPair]:
        async with self._lock:
            if not await self.needs_setup():
                raise AlreadyExists(
                    "this instance is already set up", code="already_set_up"
                )
            if self._setup_token is None or not secrets.compare_digest(
                token.encode(), self._setup_token.encode()
            ):
                raise PermissionDenied(
                    "invalid setup token", code="invalid_setup_token"
                )
            owner = await self._users.create_owner(
                email=email, password=password
            )
            self._setup_token = None
        return owner, issue_tokens(self._tokens, owner)
