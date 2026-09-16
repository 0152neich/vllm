"""Tạo schema ban đầu cho LLM Gateway.

Revision ID: 20260904_0001
Revises: None
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260904_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("allowed_models", sa.JSON(), nullable=False),
        sa.Column("rpm", sa.Integer(), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), nullable=False),
        sa.Column("max_input_characters", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("prefix", sa.String(length=32), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prefix"),
    )
    op.create_index("ix_api_keys_project_id", "api_keys", ["project_id"])
    op.create_index("ix_api_keys_kind", "api_keys", ["kind"])
    op.create_table(
        "usage_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_events_request_id", "usage_events", ["request_id"])
    op.create_index("ix_usage_events_project_id", "usage_events", ["project_id"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("target", sa.String(length=120), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_index("ix_usage_events_project_id", table_name="usage_events")
    op.drop_index("ix_usage_events_request_id", table_name="usage_events")
    op.drop_table("usage_events")
    op.drop_index("ix_api_keys_kind", table_name="api_keys")
    op.drop_index("ix_api_keys_project_id", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_table("projects")
