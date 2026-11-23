from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, String, Text
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column as column

from atlas.models.base import Base, Timestamped, UTCDateTime, new_id


class Connector(Timestamped, Base, kw_only=True, eq=False):
    """A configured source of documents, and the outcome of its last sync.

    ``config`` is type-specific (``{"urls": [...]}``, ``{"access_token",
    "file_ids"}``) and may hold secrets, so it is kept out of ``repr``.
    """

    __tablename__ = "connectors"

    id: Mapped[str] = column(String, primary_key=True, default_factory=new_id)
    project_id: Mapped[str] = column(String, server_default="", index=True)
    type: Mapped[str] = column(String)
    name: Mapped[str] = column(String)
    # MutableDict: an in-place change (config["urls"] = ...) is tracked too,
    # not only replacing the whole dict.
    config: Mapped[dict[str, Any]] = column(
        MutableDict.as_mutable(JSON), repr=False
    )
    enabled: Mapped[bool] = column(Boolean, default=True)
    last_synced_at: Mapped[datetime | None] = column(
        UTCDateTime(), default=None
    )
    last_sync_status: Mapped[str | None] = column(String, default=None)
    last_sync_detail: Mapped[str | None] = column(Text, default=None)
