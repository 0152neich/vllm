"""Thêm index phục vụ dashboard và bộ lọc Admin Console.

Revision ID: 20260904_0002
Revises: 20260904_0001
"""

from __future__ import annotations

from alembic import op

revision = "20260904_0002"
down_revision = "20260904_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_usage_events_created_at", "usage_events", ["created_at"]
    )
    op.create_index(
        "ix_usage_events_project_created",
        "usage_events",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_api_keys_project_status_created",
        "api_keys",
        ["project_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_api_keys_project_status_created", table_name="api_keys")
    op.drop_index("ix_usage_events_project_created", table_name="usage_events")
    op.drop_index("ix_usage_events_created_at", table_name="usage_events")
