"""add editorial content metadata

Revision ID: 82ca51e1d7f0
Revises: f1b3c9a7d204
Create Date: 2026-11-05 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "82ca51e1d7f0"
down_revision = "f1b3c9a7d204"
branch_labels = None
depends_on = None


def add_missing_columns(table: str, columns: list[sa.Column]) -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}
    for column in columns:
        if column.name not in existing:
            op.add_column(table, column)


def upgrade() -> None:
    add_missing_columns("channels", [
        sa.Column("target_audience", sa.Text(), nullable=True),
        sa.Column("tone", sa.String(length=120), nullable=True),
        sa.Column("language", sa.String(length=80), nullable=True),
        sa.Column("format", sa.Text(), nullable=True),
        sa.Column("default_duration_minutes", sa.Integer(), nullable=False, server_default="10"),
    ])
    add_missing_columns("content_topics", [
        sa.Column("angle", sa.Text(), nullable=True),
        sa.Column("audience_value", sa.Text(), nullable=True),
        sa.Column("visual_potential", sa.Text(), nullable=True),
        sa.Column("novelty_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_queries", sa.JSON(), nullable=False, server_default="[]"),
    ])
    add_missing_columns("video_scripts", [
        sa.Column("target_duration_minutes", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("sections", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source_map", sa.JSON(), nullable=False, server_default="[]"),
    ])
    add_missing_columns("video_scenes", [
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_ids", sa.JSON(), nullable=False, server_default="[]"),
    ])


def downgrade() -> None:
    for table, names in (
        ("video_scenes", ("source_ids", "revision")),
        ("video_scripts", ("source_map", "source_ids", "sections", "target_duration_minutes")),
        ("content_topics", ("source_queries", "novelty_score", "visual_potential", "audience_value", "angle")),
        ("channels", ("default_duration_minutes", "format", "language", "tone", "target_audience")),
    ):
        for name in names:
            op.drop_column(table, name)