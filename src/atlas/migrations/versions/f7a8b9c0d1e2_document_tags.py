"""document tags

Revision ID: f7a8b9c0d1e2
Revises: d93042a3f9b0
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: str | Sequence[str] | None = "d93042a3f9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_tags",
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("tag", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents_metadata.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("document_id", "tag"),
    )
    op.create_index(
        op.f("ix_document_tags_tag"), "document_tags", ["tag"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_document_tags_tag"), table_name="document_tags")
    op.drop_table("document_tags")
