from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class DocumentMetadata:
    id: str
    title: str
    source_path: str
    project_id: str = ""  # the owning project (set by the intake service)
    mime_type: str | None = None
    file_size_bytes: int | None = None
    content_hash: str | None = None
    status: str = "pending"
    indexed_at: datetime | None = None
