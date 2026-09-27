"""authentication and authorization service

This module owns everything identity related

* password hashing / verification
* JWT minting and verification
* the account flows: ``signup`` / ``login`` / ``refresh``
* the checks used from middleware and route dependencies:
  ``authenticate``  and ``authorize``

Tokens are self-contained: the access token carries the caller's id, email
and role, so middleware can authenticate and authorize a request without a
database round trip.
Only the flows that must touch persistent state hit the ``UserStore``.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from jwt import JWT
from jwt.exceptions import JWTDecodeError
from jwt.jwk import OctetJWK
from jwt.utils import get_int_from_datetime
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy.exc import IntegrityError

from service.models import User
from service.storage.store import UserStore

password_hasher = PasswordHash((Argon2Hasher(),))

# A pre-computed argon2 hash of a random string. ``login`` verifies against it
# when the account does not exist so that a missing user costs the same time
# as a wrong password, closing the timing side-channel that would otherwise
# reveal which emails are registered.
_DUMMY_HASH = password_hasher.hash(uuid.uuid4().hex)


# Role hierarchy, most privileged last. ``authorize`` treats a higherranked
# role as satisfying any requirement at or below it
_ROLE_ORDER: tuple[str, ...] = ("member", "admin", "owner")


TokenType = Literal["access", "refresh", "invite"]
_VALID_TOKEN_TYPES: frozenset[str] = frozenset(
    ("access", "refresh", "invite")
)


class AuthError(Exception):
    """Base class for auth failures the web layer maps to HTTP responses."""


class InvalidCredentials(AuthError):
    """Wrong email/password, or the account cannot log in."""


class EmailTaken(AuthError):
    """Signup with an email that already exists."""


class InvalidToken(AuthError):
    """The presented token is missing, malformed, expired or forged."""


class InactiveUser(AuthError):
    """The account exists but is not in a state that may authenticate."""


class PermissionDenied(AuthError):
    """The caller is authenticated but lacks the required role."""


@dataclass(slots=True)
class Principal:
    """The verified identity carried by a token.

    This is what ``authenticate`` returns and what ``authorize`` consumes:
    the request-scoped "who is calling", derived entirely from the token in a
    stateless manner (no store lookup on the hot path).
    """

    user_id: str
    email: str
    role: str
    token_type: TokenType
    # Set only on project invites: the project the invite joins, and the role
    # to grant there. Empty on access/refresh tokens and on plain invites.
    project_id: str = ""
    project_role: str = ""


@dataclass(slots=True)
class LoginResult:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenCodec:
    """Small helper of ``AuthService`` so the signing key and TTLs are
    configured once, in one place."""

    def __init__(
        self,
        *,
        secret: str,
        algorithm: str = "HS256",
        access_ttl: timedelta = timedelta(minutes=15),
        refresh_ttl: timedelta = timedelta(days=7),
        invite_ttl: timedelta = timedelta(minutes=5),
    ) -> None:
        self._jwt = JWT()  # type: ignore[no-untyped-call]  # lib ships no stubs
        self._key = OctetJWK(secret.encode("utf-8"))
        self._alg = algorithm
        self._access_ttl = access_ttl
        self._refresh_ttl = refresh_ttl
        self._invite_ttl = invite_ttl

    def access_for(self, user: User) -> str:
        return self._encode(
            sub=user.id,
            email=user.email,
            role=user.role,
            token_type="access",
            ttl=self._access_ttl,
        )

    def refresh_for(self, user: User) -> str:
        return self._encode(
            sub=user.id,
            email=user.email,
            role=user.role,
            token_type="refresh",
            ttl=self._refresh_ttl,
        )

    def invite_for(
        self, *, role: str, project_id: str = "", project_role: str = ""
    ) -> str:
        # An invite carries only a role -- no identity yet -- so sub/email are
        # empty. Signup fills those in from what the invitee provides. A
        # *project* invite additionally carries the project + role to grant
        # there, so accepting it both creates the account and joins the
        # project.
        return self._encode(
            sub="",
            email="",
            role=role,
            token_type="invite",
            ttl=self._invite_ttl,
            project_id=project_id,
            project_role=project_role,
        )

    def _encode(
        self,
        *,
        sub: str,
        email: str,
        role: str,
        token_type: TokenType,
        ttl: timedelta,
        project_id: str = "",
        project_role: str = "",
    ) -> str:
        now = datetime.now(UTC)
        payload = {
            "sub": sub,
            "email": email,
            "role": role,
            "type": token_type,
            "project_id": project_id,
            "project_role": project_role,
            "iat": get_int_from_datetime(now),
            "exp": get_int_from_datetime(now + ttl),
        }
        return self._jwt.encode(payload, self._key, alg=self._alg)

    def verify(self, token: str) -> Principal:
        """Decode and validate a token, returning its ``Principal``.

        Raises :class:`InvalidToken` for anything untrustworthy: bad
        signature, expiry, or a payload missing the claims that is required
        """
        try:
            claims = self._jwt.decode(
                token, self._key, algorithms={self._alg}, do_time_check=True
            )
        except JWTDecodeError as exc:
            raise InvalidToken(str(exc)) from exc

        try:
            token_type = claims["type"]
            if token_type not in _VALID_TOKEN_TYPES:
                raise InvalidToken(f"unexpected token type: {token_type!r}")
            return Principal(
                user_id=claims["sub"],
                email=claims["email"],
                role=claims["role"],
                token_type=token_type,
                project_id=claims.get("project_id", ""),
                project_role=claims.get("project_role", ""),
            )
        except KeyError as exc:
            raise InvalidToken(f"missing claim: {exc}") from exc


class AuthService:
    """Authentication and authorization for the application.

    The account flows (``signup``/``login``/``refresh``) need the user_store
    and raise a runtime error if it was not provided.

    ``authorize`` features are stateless they read the token only so they work
    with ``user_store=None`` and intended to be used in middleware
    """

    def __init__(
        self,
        *,
        token_codec: TokenCodec,
        user_store: UserStore | None = None,
    ) -> None:
        self._store = user_store
        self._tokens = token_codec

    def _store_or_raise(self) -> UserStore:
        if self._store is None:
            raise RuntimeError(
                "this AuthService was built without a user store; account "
                "flows (signup/login/refresh) are unavailable"
            )
        return self._store

    async def signup(
        self, *, email: str, username: str, password: str, invite_token: str
    ) -> LoginResult:
        """Register a new account from an invite and return a token pair.

        The invite is a signed, role-carrying link (see ``create_invite``):
        anyone holding a live one may self-register at the role it names, with
        whatever email/username they supply.

        Raises :class:`InvalidToken` if the invite is missing, expired, forged
        or not an invite; :class:`EmailTaken` if the email/username is in use.
        """
        invite = self._tokens.verify(invite_token)
        if invite.token_type != "invite":
            raise InvalidToken("expected an invite token")
        if invite.role not in _ROLE_ORDER:
            raise InvalidToken(f"invite carries unknown role: {invite.role!r}")

        if await self._store_or_raise().get(email) is not None:
            raise EmailTaken("email already registered")

        now = datetime.now(UTC)
        user = User(
            id=uuid.uuid4().hex,
            email=email,
            username=username,
            password_hash=password_hasher.hash(password),
            role=invite.role,
            status="active",
            created_at=now,
            updated_at=now,
            last_login_at=now,
        )
        try:
            await self._store_or_raise().add(user)
        except IntegrityError as exc:
            raise EmailTaken("email or username already registered") from exc

        return self._issue(user)

    async def login(self, *, email: str, password: str) -> LoginResult:
        """Verify credentials and return a fresh token pair.

        Raises :class:`InvalidCredentials` on a bad email/password, and
        :class:`InactiveUser` if the account is disabled or not yet activated.
        """
        user = await self._store_or_raise().get(email)

        # Always run a verify -- against a dummy hash when the user is unknown
        # -- so response time does not reveal whether the email exists.
        expected_hash = user.password_hash if user else _DUMMY_HASH
        verified = password_hasher.verify(password, expected_hash)

        if user is None or not verified:
            raise InvalidCredentials("incorrect email or password")
        if user.status != "active":
            raise InactiveUser(f"account is {user.status}")

        return self._issue(user)

    async def refresh(self, *, refresh_token: str) -> LoginResult:
        """Exchange a valid refresh token for a new token pair.

        Raises :class:`InvalidToken` if the token is not a live refresh token,
        and :class:`InvalidCredentials`/:class:`InactiveUser` if the account
        has since vanished or been deactivated.
        """
        principal = self._tokens.verify(refresh_token)
        if principal.token_type != "refresh":
            raise InvalidToken("expected a refresh token")

        user = await self._store_or_raise().get(principal.email)
        if user is None:
            raise InvalidCredentials("account no longer exists")
        if user.status != "active":
            raise InactiveUser(f"account is {user.status}")

        return self._issue(user)

    def authenticate(self, token: str) -> Principal:
        """Authenticate a request from its bearer token.

        Returns the caller's :class:`Principal`, or raises
        :class:`InvalidToken`. Rejects refresh tokens: only access tokens may
        authenticate a request. Pure and synchronous so it is cheap to call
        from middleware on every request.
        """
        principal = self._tokens.verify(token)
        if principal.token_type != "access":
            raise InvalidToken("expected an access token")
        return principal

    def authorize(self, principal: Principal, *, require_role: str) -> None:
        """Assert ``principal`` holds at least ``require_role``.

        Roles are hierarchical (see ``_ROLE_ORDER``): a higher role satisfies a
        lower requirement. Raises :class:`PermissionDenied` otherwise.
        """
        try:
            have = _ROLE_ORDER.index(principal.role)
            need = _ROLE_ORDER.index(require_role)
        except ValueError as exc:
            raise PermissionDenied(f"unknown role: {exc}") from exc

        if have < need:
            raise PermissionDenied(
                f"requires role {require_role!r}, "
                f"caller has {principal.role!r}"
            )

    def create_invite(self, inviter: Principal, *, role: str) -> str:
        """Mint a shareable invite link granting a global ``role``.

        Stateless (token-only), so it runs on a store-less service. The
        ``inviter`` must be at least an admin and cannot grant a role above
        their own. Raises :class:`PermissionDenied` otherwise.
        """
        self.authorize(inviter, require_role="admin")
        if role not in _ROLE_ORDER:
            raise PermissionDenied(f"unknown role: {role!r}")
        if _ROLE_ORDER.index(role) > _ROLE_ORDER.index(inviter.role):
            raise PermissionDenied("cannot invite at a role above your own")
        return self._tokens.invite_for(role=role)

    def mint_project_invite(
        self, *, project_id: str, project_role: str
    ) -> str:
        """Mint an invite that creates an account and joins it to a project.

        The caller's *project* authorization is enforced by the route (via
        :class:`~service.core.projects.ProjectService`) before this is
        called, so this is a pure token mint. The account is created at the
        base global role ``"member"``; project powers come from
        ``project_role``.
        """
        if project_role not in ("admin", "member"):
            raise PermissionDenied(f"invalid project role: {project_role!r}")
        return self._tokens.invite_for(
            role="member",
            project_id=project_id,
            project_role=project_role,
        )

    def read_invite(self, token: str) -> Principal:
        """Verify an invite token and return its claims (for the signup flow).

        Raises :class:`InvalidToken` if it is not a live invite token.
        """
        principal = self._tokens.verify(token)
        if principal.token_type != "invite":
            raise InvalidToken("expected an invite token")
        return principal

    def _issue(self, user: User) -> LoginResult:
        return LoginResult(
            access_token=self._tokens.access_for(user),
            refresh_token=self._tokens.refresh_for(user),
        )
