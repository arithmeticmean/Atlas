from typing import Literal

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column as column

from atlas.models.base import Base, Timestamped, new_id

JobStatus = Literal["queued", "processing", "done", "failed"]


class IngestionJob(Timestamped, Base, kw_only=True, eq=False):
    """One document's turn through ingestion, as a durable queue row."""

    __tablename__ = "ingestion_jobs"

    id: Mapped[str] = column(String, primary_key=True, default_factory=new_id)
    document_id: Mapped[str] = column(String, index=True)
    status: Mapped[JobStatus] = column(String, default="queued", index=True)
    attempts: Mapped[int] = column(Integer, default=0)
    last_error: Mapped[str | None] = column(Text, default=None)

    def start(self) -> None:
        self.status = "processing"
        self.attempts += 1

    def finish(self) -> None:
        self.status = "done"

    def fail(self, error: str, *, retry: bool) -> None:
        self.status = "queued" if retry else "failed"
        self.last_error = error
