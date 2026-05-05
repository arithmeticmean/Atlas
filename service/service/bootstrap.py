"""First-run bootstrap: create the single global owner account.

Runs at startup. If ``OWNER_EMAIL``/``OWNER_PASSWORD`` are configured (written
by configure.py) and no user with that email exists yet, create it with the
global ``owner`` role. Idempotent — safe to run on every start.
"""

import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime

from models import User
from service.auth import password_hasher
from storage.store import UserStore

UserStoreUoW = Callable[[], AbstractAsyncContextManager[UserStore]]


async def ensure_owner(
    *,
    user_store_uow: UserStoreUoW,
    email: str | None,
    password: str | None,
) -> None:
    if not email or not password:
        return
    async with user_store_uow() as store:
        if await store.get(email) is not None:
            return
        now = datetime.now(UTC)
        await store.add(
            User(
                id=uuid.uuid4().hex,
                email=email,
                username=email.split("@", 1)[0][:64],
                password_hash=password_hasher.hash(password),
                role="owner",
                status="active",
                created_at=now,
                updated_at=now,
                last_login_at=None,
            )
        )
