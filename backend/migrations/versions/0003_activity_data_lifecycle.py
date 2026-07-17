"""Add user data lifecycle state to FIT imports.

Revision ID: 0003_activity_data_lifecycle
Revises: 0002_activity_import
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_activity_data_lifecycle"
down_revision: str | None = "0002_activity_import"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "activity_imports", sa.Column("title_override", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "activity_imports",
        sa.Column("delete_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "activity_imports",
        sa.Column("last_delete_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "activity_imports",
        sa.Column("delete_attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "activity_imports", sa.Column("delete_error_code", sa.String(length=80), nullable=True)
    )
    op.add_column(
        "activity_imports",
        sa.Column("processing_token", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_activity_imports_user_status_created",
        "activity_imports",
        ["user_id", "status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_activity_imports_user_status_created", table_name="activity_imports")
    op.drop_column("activity_imports", "processing_token")
    op.drop_column("activity_imports", "delete_error_code")
    op.drop_column("activity_imports", "delete_attempt_count")
    op.drop_column("activity_imports", "last_delete_attempt_at")
    op.drop_column("activity_imports", "delete_requested_at")
    op.drop_column("activity_imports", "title_override")
