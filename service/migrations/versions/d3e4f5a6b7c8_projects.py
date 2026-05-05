"""projects, project members, and project scoping

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-08-12 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3e4f5a6b7c8"
down_revision: str | Sequence[str] | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "projects",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "project_members",
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("admin", "member", name="project_role"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("project_id", "user_id"),
    )
    op.create_index(
        op.f("ix_project_members_user_id"),
        "project_members",
        ["user_id"],
        unique=False,
    )

    # Scope documents and connectors to a project.
    op.add_column(
        "documents_metadata",
        sa.Column(
            "project_id", sa.String(), nullable=False, server_default=""
        ),
    )
    op.create_index(
        op.f("ix_documents_metadata_project_id"),
        "documents_metadata",
        ["project_id"],
        unique=False,
    )
    op.add_column(
        "connectors",
        sa.Column(
            "project_id", sa.String(), nullable=False, server_default=""
        ),
    )
    op.create_index(
        op.f("ix_connectors_project_id"),
        "connectors",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_connectors_project_id"), table_name="connectors"
    )
    op.drop_column("connectors", "project_id")
    op.drop_index(
        op.f("ix_documents_metadata_project_id"),
        table_name="documents_metadata",
    )
    op.drop_column("documents_metadata", "project_id")
    op.drop_index(
        op.f("ix_project_members_user_id"), table_name="project_members"
    )
    op.drop_table("project_members")
    op.drop_table("projects")
