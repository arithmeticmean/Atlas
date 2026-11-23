"""The master key: encrypts stored API keys and signs login tokens.

It comes from ``ATLAS_MASTER_KEY``, or is generated once into
``DATA_PATH/master.key``. Losing it does not lose documents or accounts:
stored API keys must be entered again, and everyone signs in again.
"""

import hmac
import os
import secrets
from base64 import urlsafe_b64encode
from pathlib import Path
from typing import Self

from cryptography.fernet import Fernet, InvalidToken

from atlas.config.settings import BootstrapSettings

_MINIMUM_LENGTH = 32


class MasterKey:
    def __init__(self, value: str) -> None:
        if len(value) < _MINIMUM_LENGTH:
            raise ValueError(
                f"the master key needs at least {_MINIMUM_LENGTH} characters"
            )
        self._value = value.encode()
        self._fernet = Fernet(urlsafe_b64encode(self._derive("settings")))

    @classmethod
    def load(cls, bootstrap: BootstrapSettings) -> Self:
        if bootstrap.master_key is not None:
            return cls(bootstrap.master_key.get_secret_value())
        return cls(_read_or_create(bootstrap.master_key_path))

    @property
    def jwt_secret(self) -> str:
        return self._derive("jwt").hex()

    def encrypt(self, text: str) -> str:
        return self._fernet.encrypt(text.encode()).decode()

    def decrypt(self, token: str) -> str | None:
        """The text, or ``None`` if it was encrypted with a different key."""
        try:
            return self._fernet.decrypt(token).decode()
        except InvalidToken:
            return None

    def _derive(self, purpose: str) -> bytes:
        # One key per purpose, so token signing and encryption never share.
        return hmac.digest(self._value, purpose.encode(), "sha256")


def _read_or_create(path: Path) -> str:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text().strip()
    value = secrets.token_urlsafe(48)
    with os.fdopen(descriptor, "w") as file:
        file.write(value)
    return value
