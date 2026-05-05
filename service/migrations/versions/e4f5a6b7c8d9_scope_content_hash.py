"""drop global content_hash unique (dedup is per-project now)

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-08-13

Documents belong to a project, so identical bytes may legitimately exist in
two projects. The old global ``UNIQUE(content_hash)`` would reject the second
copy (and, worse, dedup could return another tenant's row); drop it. Dedup is
now scoped to the project and enforced in ``DocumentService.store``.

The original constraint was created unnamed (``sa.UniqueConstraint`` on
SQLite/Postgres), so we drop it inside ``batch_alter_table`` with a naming
convention that lets Alembic address it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e4f5a6b7c8d9"
down_revision: str | None = "d3e4f5a6b7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAMING = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
_UQ = "uq_documents_metadata_content_hash"


def upgrade() -> None:
    with op.batch_alter_table(
        "documents_metadata", naming_convention=_NAMING
    ) as batch_op:
        batch_op.drop_constraint(_UQ, type_="unique")


def downgrade() -> None:
    with op.batch_alter_table(
        "documents_metadata", naming_convention=_NAMING
    ) as batch_op:
        batch_op.create_unique_constraint(_UQ, ["content_hash"])
