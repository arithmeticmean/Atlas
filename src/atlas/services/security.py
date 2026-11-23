"""Passwords and signed tokens.

Tokens are self-contained JWTs, so checking one needs no database. Four
kinds, each only accepted where it belongs: ``access`` (every request),
``refresh`` (new access tokens), ``invite`` (sign up / join projects) and
``reset`` (set a new password once).
"""

import hashlib
import uuid
from datetime import timedelta
from typing import Any, Literal

from jwt import JWT
from jwt.exceptions import JWTDecodeError
from jwt.jwk import OctetJWK
from jwt.utils import get_int_from_datetime
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from atlas.models.base import utcnow
from atlas.services.errors import InvalidToken
from atlas.services.settings import SettingsService

TokenKind = Literal["access", "refresh", "invite", "reset"]

_hasher = PasswordHash((Argon2Hasher(),))
# Verified against when an account does not exist, so a missing user takes
# as long as a wrong password and response times reveal nothing.
_DUMMY_HASH = _hasher.hash(uuid.uuid4().hex)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Always does the full work, even for an unknown account."""
    ok = _hasher.verify(password, password_hash or _DUMMY_HASH)
    return ok and password_hash is not None


def password_fingerprint(password_hash: str) -> str:
    """Put in a reset token: once the password changes, the fingerprint no
    longer matches, so each reset link works exactly once."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


class TokenCodec:
    """Reads settings on every use, so a changed token lifetime applies to
    the next token without a restart."""

    def __init__(self, *, settings: SettingsService) -> None:
        self._jwt = JWT()  # type: ignore[no-untyped-call]
        self._settings = settings

    def lifetime(self, kind: TokenKind) -> timedelta:
        current = self._settings.current
        minutes = {
            "access": current.access_token_ttl_minutes,
            "refresh": current.refresh_token_ttl_minutes,
            "invite": current.invite_token_ttl_minutes,
            "reset": 60,
        }
        return timedelta(minutes=minutes[kind])

    @property
    def _key(self) -> OctetJWK:
        return OctetJWK(self._settings.current.jwt_secret.encode())

    @property
    def _algorithm(self) -> str:
        return self._settings.current.jwt_algorithm

    def issue(
        self,
        kind: TokenKind,
        claims: dict[str, Any],
        *,
        lifetime: timedelta | None = None,
    ) -> str:
        now = utcnow()
        payload = {
            **claims,
            "kind": kind,
            "iat": get_int_from_datetime(now),
            "exp": get_int_from_datetime(
                now + (lifetime or self.lifetime(kind))
            ),
        }
        token: str = self._jwt.encode(payload, self._key, alg=self._algorithm)
        return token

    def read(self, token: str, kind: TokenKind) -> dict[str, Any]:
        """The token's claims, if it is genuine, unexpired and of ``kind``;
        otherwise :class:`InvalidToken`."""
        try:
            claims: dict[str, Any] = self._jwt.decode(
                token,
                self._key,
                algorithms={self._algorithm},
                do_time_check=True,
            )
        except JWTDecodeError as exc:
            raise InvalidToken(str(exc)) from exc
        if claims.get("kind") != kind:
            raise InvalidToken(f"expected a {kind} token")
        return claims
