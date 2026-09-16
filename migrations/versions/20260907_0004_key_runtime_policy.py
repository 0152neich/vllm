"""Chuyển runtime policy từ project xuống từng API key.

Revision ID: 20260907_0004
Revises: 20260907_0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260907_0004"
down_revision = "20260907_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Backfill policy hiện có trước khi bỏ các cột policy của project."""

    op.add_column("api_keys", sa.Column("allowed_models", sa.JSON(), nullable=True))
    op.add_column("api_keys", sa.Column("max_concurrency", sa.Integer(), nullable=True))
    op.add_column(
        "api_keys", sa.Column("max_input_characters", sa.Integer(), nullable=True)
    )
    op.add_column("api_keys", sa.Column("max_output_tokens", sa.Integer(), nullable=True))
    op.add_column("api_keys", sa.Column("timeout_seconds", sa.Float(), nullable=True))
    op.execute(
        """
        UPDATE api_keys AS api_key
        SET allowed_models = project.allowed_models,
            rpm = project.rpm,
            max_concurrency = project.max_concurrency,
            max_input_characters = project.max_input_characters,
            max_output_tokens = project.max_output_tokens,
            timeout_seconds = project.timeout_seconds
        FROM projects AS project
        WHERE api_key.project_id = project.id
        """
    )
    op.alter_column("api_keys", "rpm", existing_type=sa.Integer(), nullable=False)
    op.alter_column("api_keys", "allowed_models", existing_type=sa.JSON(), nullable=False)
    op.alter_column("api_keys", "max_concurrency", existing_type=sa.Integer(), nullable=False)
    op.alter_column(
        "api_keys", "max_input_characters", existing_type=sa.Integer(), nullable=False
    )
    op.alter_column(
        "api_keys", "max_output_tokens", existing_type=sa.Integer(), nullable=False
    )
    op.alter_column(
        "api_keys", "timeout_seconds", existing_type=sa.Float(), nullable=False
    )
    op.drop_column("projects", "timeout_seconds")
    op.drop_column("projects", "max_output_tokens")
    op.drop_column("projects", "max_input_characters")
    op.drop_column("projects", "max_concurrency")
    op.drop_column("projects", "rpm")
    op.drop_column("projects", "allowed_models")


def downgrade() -> None:
    """Khôi phục schema cũ từ policy của key mới nhất trong mỗi project.

    Rollback làm mất khác biệt policy giữa các key vì schema cũ không biểu diễn được
    chúng. Chỉ sử dụng khi chấp nhận giới hạn này.
    """

    op.add_column("projects", sa.Column("allowed_models", sa.JSON(), nullable=True))
    op.add_column("projects", sa.Column("rpm", sa.Integer(), nullable=True))
    op.add_column("projects", sa.Column("max_concurrency", sa.Integer(), nullable=True))
    op.add_column(
        "projects", sa.Column("max_input_characters", sa.Integer(), nullable=True)
    )
    op.add_column("projects", sa.Column("max_output_tokens", sa.Integer(), nullable=True))
    op.add_column("projects", sa.Column("timeout_seconds", sa.Float(), nullable=True))
    op.execute(
        """
        UPDATE projects AS project
        SET allowed_models = source.allowed_models,
            rpm = source.rpm,
            max_concurrency = source.max_concurrency,
            max_input_characters = source.max_input_characters,
            max_output_tokens = source.max_output_tokens,
            timeout_seconds = source.timeout_seconds
        FROM (
            SELECT DISTINCT ON (project_id) project_id, allowed_models, rpm,
                max_concurrency, max_input_characters, max_output_tokens,
                timeout_seconds
            FROM api_keys
            ORDER BY project_id, created_at DESC
        ) AS source
        WHERE project.id = source.project_id
        """
    )
    op.execute(
        """
        UPDATE projects
        SET allowed_models = COALESCE(allowed_models, '[]'::json),
            rpm = COALESCE(rpm, 60),
            max_concurrency = COALESCE(max_concurrency, 2),
            max_input_characters = COALESCE(max_input_characters, 20000),
            max_output_tokens = COALESCE(max_output_tokens, 1024),
            timeout_seconds = COALESCE(timeout_seconds, 30)
        """
    )
    op.alter_column("projects", "allowed_models", existing_type=sa.JSON(), nullable=False)
    op.alter_column("projects", "rpm", existing_type=sa.Integer(), nullable=False)
    op.alter_column("projects", "max_concurrency", existing_type=sa.Integer(), nullable=False)
    op.alter_column(
        "projects", "max_input_characters", existing_type=sa.Integer(), nullable=False
    )
    op.alter_column(
        "projects", "max_output_tokens", existing_type=sa.Integer(), nullable=False
    )
    op.alter_column(
        "projects", "timeout_seconds", existing_type=sa.Float(), nullable=False
    )
    op.drop_column("api_keys", "timeout_seconds")
    op.drop_column("api_keys", "max_output_tokens")
    op.drop_column("api_keys", "max_input_characters")
    op.drop_column("api_keys", "max_concurrency")
    op.drop_column("api_keys", "allowed_models")
