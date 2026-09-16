"""Bổ sung quota và metadata tùy chọn theo từng API key.

Revision ID: 20260907_0003
Revises: 20260904_0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260907_0003"
down_revision = "20260904_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("tpm", sa.Integer(), nullable=True))
    op.add_column("api_keys", sa.Column("rpm", sa.Integer(), nullable=True))
    op.add_column(
        "api_keys",
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "api_keys",
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "api_keys",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "updated_at")
    op.drop_column("api_keys", "tags")
    op.drop_column("api_keys", "metadata")
    op.drop_column("api_keys", "rpm")
    op.drop_column("api_keys", "tpm")
