"""add YouTube schedule and encrypted credentials

Revision ID: f1b3c9a7d204
Revises: 07edef4aa69a
Create Date: 2026-11-05 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "f1b3c9a7d204"
down_revision = "07edef4aa69a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("youtube_uploads")}
    if "scheduled_at" not in columns:
        op.add_column("youtube_uploads", sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True))
    for name, column in (
        ("upload_attempts", sa.Column("upload_attempts", sa.Integer(), nullable=False, server_default="0")),
        ("retry_after", sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True)),
        ("claimed_at", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True)),
        ("last_error", sa.Column("last_error", sa.Text(), nullable=True)),
        ("resumable_url", sa.Column("resumable_url", sa.Text(), nullable=True)),
    ):
        if name not in columns:
            op.add_column("youtube_uploads", column)
    if "integration_credentials" not in inspector.get_table_names():
        op.create_table(
            "integration_credentials",
            sa.Column("provider", sa.String(length=50), nullable=False),
            sa.Column("encrypted_token", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("provider"),
        )
    if "oauth_states" not in inspector.get_table_names():
        op.create_table(
            "oauth_states",
            sa.Column("state_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("state_hash"),
        )
    media_columns = {column["name"] for column in inspector.get_columns("media_assets")}
    if "project_id" not in media_columns:
        op.add_column("media_assets", sa.Column("project_id", sa.String(length=36), nullable=True))
    if "created_at" not in media_columns:
        op.add_column("media_assets", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    analytics_columns = {column["name"] for column in inspector.get_columns("video_analytics")}
    if "youtube_upload_id" not in analytics_columns:
        op.add_column("video_analytics", sa.Column("youtube_upload_id", sa.String(length=36), nullable=True))
    index_names = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("video_analytics")}
    if "uq_video_analytics_youtube_upload_id" not in index_names:
        op.create_index("uq_video_analytics_youtube_upload_id", "video_analytics", ["youtube_upload_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_video_analytics_youtube_upload_id", table_name="video_analytics")
    op.drop_column("video_analytics", "youtube_upload_id")
    op.drop_column("media_assets", "created_at")
    op.drop_column("media_assets", "project_id")
    op.drop_table("oauth_states")
    op.drop_table("integration_credentials")
    op.drop_column("youtube_uploads", "last_error")
    op.drop_column("youtube_uploads", "claimed_at")
    op.drop_column("youtube_uploads", "retry_after")
    op.drop_column("youtube_uploads", "upload_attempts")
    op.drop_column("youtube_uploads", "resumable_url")
    op.drop_column("youtube_uploads", "scheduled_at")