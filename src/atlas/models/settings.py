from typing import Any

from sqlalchemy import JSON, Integer
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column as column

from atlas.models.base import Base, Timestamped

SETTINGS_ROW_ID = 1


class StoredSettings(Timestamped, Base, kw_only=True, eq=False):
    """The instance's settings: always a single row."""

    __tablename__ = "instance_settings"

    id: Mapped[int] = column(
        Integer, primary_key=True, default=SETTINGS_ROW_ID
    )
    values: Mapped[dict[str, Any]] = column(JSON, default_factory=dict)
    # Field name -> encrypted value. Never holds plain text.
    secrets: Mapped[dict[str, str]] = column(
        JSON, default_factory=dict, repr=False
    )
