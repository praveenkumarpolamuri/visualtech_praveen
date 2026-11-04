"""create visualtech schema

Revision ID: 07edef4aa69a
Revises: 
Create Date: 2026-11-03 10:48:02.304407
"""
from alembic import op
import sqlalchemy as sa


revision = '07edef4aa69a'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.core.database import Base, engine
    import app.modules.dashboard.models  # noqa: F401
    import app.modules.domain  # noqa: F401

    Base.metadata.create_all(bind=engine)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS video_analytics CASCADE")
    op.execute("DROP TABLE IF EXISTS youtube_uploads CASCADE")
    op.execute("DROP TABLE IF EXISTS render_jobs CASCADE")
    op.execute("DROP TABLE IF EXISTS approvals CASCADE")
    op.execute("DROP TABLE IF EXISTS media_assets CASCADE")
    op.execute("DROP TABLE IF EXISTS video_scenes CASCADE")
    op.execute("DROP TABLE IF EXISTS script_versions CASCADE")
    op.execute("DROP TABLE IF EXISTS video_scripts CASCADE")
    op.execute("DROP TABLE IF EXISTS research_sources CASCADE")
    op.execute("DROP TABLE IF EXISTS video_projects CASCADE")
    op.execute("DROP TABLE IF EXISTS content_topics CASCADE")
    op.execute("DROP TABLE IF EXISTS content_pillars CASCADE")
    op.execute("DROP TABLE IF EXISTS channels CASCADE")
    op.execute("DROP TABLE IF EXISTS projects CASCADE")
