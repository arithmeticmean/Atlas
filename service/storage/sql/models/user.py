from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from service.storage.sql.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)

    email: Mapped[str] = mapped_column(
        String(320), unique=True, nullable=False
    )

    username: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )

    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    role: Mapped[str] = mapped_column(
        SqlEnum(
            "owner",
            "admin",
            "member",
            name="user_role",
        ),
        nullable=False,
        default="member",
    )

    status: Mapped[str] = mapped_column(
        SqlEnum("pending", "active", "disabled", name="user_status"),
        nullable=False,
        default="pending",
    )

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
