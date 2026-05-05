"""ingestion jobs queue

Revision ID: a1b2c3d4e5f6
Revises: b85eecc6e86b
Create Date: 2026-08-10 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "b85eecc6e86b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ingestion_jobs_document_id"),
        "ingestion_jobs",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ingestion_jobs_status"),
        "ingestion_jobs",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_ingestion_jobs_status"), table_name="ingestion_jobs"
    )
    op.drop_index(
        op.f("ix_ingestion_jobs_document_id"), table_name="ingestion_jobs"
    )
    op.drop_table("ingestion_jobs")
