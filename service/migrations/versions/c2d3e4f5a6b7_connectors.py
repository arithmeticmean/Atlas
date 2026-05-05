"""connectors

Revision ID: c2d3e4f5a6b7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-12 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "connectors",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_synced_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("last_sync_status", sa.String(), nullable=True),
        sa.Column("last_sync_detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("connectors")
