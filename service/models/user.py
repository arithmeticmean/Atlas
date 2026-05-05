from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class User:
    id: str
    email: str
    username: str
    password_hash: str
    role: str
    status: str
    created_at: datetime | None
    updated_at: datetime | None
    last_login_at: datetime | None
