from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Connector:
    """A configured, persistent source of documents.

    ``config`` holds type-specific settings (e.g. ``{"urls": [...]}`` for a
    url connector, ``{"access_token", "file_ids"}`` for google_drive). Sync
    state records the outcome of the last pull from the source.
    """

    id: str
    type: str  # "url" | "google_drive"
    name: str
    config: dict[str, Any]
    project_id: str = ""  # the owning project (set by the manager)
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_synced_at: datetime | None = None
    last_sync_status: str | None = None  # "ok" | "error"
    last_sync_detail: str | None = None
