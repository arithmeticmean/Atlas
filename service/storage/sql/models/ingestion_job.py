from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from service.storage.sql.db import Base


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)

    document_id: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )

    # queued | processing | done | failed
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="queued", index=True
    )

    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
