"""Signing in and staying signed in.

Tokens are self-contained, so there is no sessions table yet: logging out
cannot revoke anything server-side, and "where am I logged in" cannot be
listed. Both need a sessions table; until then they say so.
"""

from dataclasses import dataclass

from atlas.models.base import utcnow
from atlas.models.user import User
from atlas.repository.uow import UnitOfWorkFactory
from atlas.services.access import Caller
from atlas.services.errors import (
    AccountDisabled,
    InvalidCredentials,
    InvalidToken,
)
from atlas.services.security import (
    TokenCodec,
    hash_password,
    password_fingerprint,
    verify_password,
)


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int  # seconds until the access token ends


def issue_tokens(tokens: TokenCodec, user: User) -> TokenPair:
    claims = {"sub": user.id, "role": user.role}
    return TokenPair(
        access_token=tokens.issue("access", claims),
        refresh_token=tokens.issue("refresh", {"sub": user.id}),
        expires_in=int(tokens.lifetime("access").total_seconds()),
    )


class AuthService:
    def __init__(self, *, uow: UnitOfWorkFactory, tokens: TokenCodec) -> None:
        self._uow = uow
        self._tokens = tokens

    def authenticate(self, access_token: str) -> Caller:
        """The caller behind an access token. Pure: no database."""
        claims = self._tokens.read(access_token, "access")
        return Caller(user_id=claims["sub"], role=claims["role"])

    async def login(
        self, *, email: str, password: str
    ) -> tuple[User, TokenPair]:
        async with self._uow() as uow:
            user = await uow.users.by_email(email)
            valid = verify_password(
                password, user.password_hash if user else None
            )
            if user is None or not valid:
                raise InvalidCredentials("incorrect email or password")
            if user.status != "active":
                raise AccountDisabled(f"account is {user.status}")
            user.last_login_at = utcnow()
        return user, issue_tokens(self._tokens, user)

    async def refresh(self, refresh_token: str) -> TokenPair:
        """A new pair; the role in it is re-read, so a changed role applies
        from the next refresh."""
        claims = self._tokens.read(refresh_token, "refresh")
        async with self._uow() as uow:
            user = await uow.users.get(claims["sub"])
        if user is None:
            raise InvalidToken("account no longer exists")
        if user.status != "active":
            raise AccountDisabled(f"account is {user.status}")
        return issue_tokens(self._tokens, user)

    async def logout(self, refresh_token: str | None) -> None:
        """Nothing to revoke while tokens are self-contained; the caller
        drops the refresh cookie. A sessions table makes this real."""

    async def change_password(
        self, caller: Caller, *, current_password: str, new_password: str
    ) -> None:
        async with self._uow() as uow:
            user = await uow.users.get(caller.user_id)
            if user is None or not verify_password(
                current_password, user.password_hash
            ):
                raise InvalidCredentials("current password is incorrect")
            user.password_hash = hash_password(new_password)

    async def reset_password(self, *, token: str, new_password: str) -> None:
        """Redeem a link minted by ``UserService.create_password_reset``.
        Works once: the new password no longer matches the token."""
        claims = self._tokens.read(token, "reset")
        async with self._uow() as uow:
            user = await uow.users.get(claims["sub"])
            if user is None or claims.get("pwd") != password_fingerprint(
                user.password_hash
            ):
                raise InvalidToken("reset link already used or invalid")
            user.password_hash = hash_password(new_password)

    async def list_sessions(self, caller: Caller) -> list[object]:
        raise NotImplementedError("listing sessions needs a sessions table")

    async def revoke_session(self, caller: Caller, session_id: str) -> None:
        raise NotImplementedError("revoking a session needs a sessions table")
