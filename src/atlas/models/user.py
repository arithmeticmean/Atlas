from datetime import datetime
from typing import Literal, get_args

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column as column

from atlas.models.base import Base, Timestamped, UTCDateTime, new_id

UserRole = Literal["owner", "admin", "member"]
UserStatus = Literal["pending", "active", "disabled"]
# What can be granted: the owner role only moves by transferring it.
AssignableRole = Literal["admin", "member"]


class User(Timestamped, Base, kw_only=True, eq=False):
    __tablename__ = "users"

    id: Mapped[str] = column(String, primary_key=True, default_factory=new_id)
    email: Mapped[str] = column(String(320), unique=True)
    username: Mapped[str] = column(String(64), unique=True)
    password_hash: Mapped[str] = column(String(255), repr=False)
    role: Mapped[UserRole] = column(
        Enum(*get_args(UserRole), name="user_role"), default="member"
    )
    status: Mapped[UserStatus] = column(
        Enum(*get_args(UserStatus), name="user_status"), default="active"
    )
    last_login_at: Mapped[datetime | None] = column(
        UTCDateTime(), default=None
    )
