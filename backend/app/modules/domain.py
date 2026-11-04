from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, Session
from app.core.database import Base, get_db
from app.core.security import require_role


def utcnow(): return datetime.now(timezone.utc)
def uid(): return str(uuid.uuid4())

class Channel(Base):
    __tablename__="channels"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    name: Mapped[str]=mapped_column(String(120)); youtube_channel_id: Mapped[Optional[str]]=mapped_column(String(120),nullable=True)

class ContentPillar(Base):
    __tablename__="content_pillars"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    name: Mapped[str]=mapped_column(String(120)); description: Mapped[Optional[str]]=mapped_column(Text,nullable=True)

class ContentTopic(Base):
    __tablename__="content_topics"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    title: Mapped[str]=mapped_column(String(255)); description: Mapped[Optional[str]]=mapped_column(Text,nullable=True)
    pillar: Mapped[str]=mapped_column(String(100)); status: Mapped[str]=mapped_column(String(50),default="idea")
    priority: Mapped[str]=mapped_column(String(20),default="medium"); source_estimate: Mapped[str]=mapped_column(String(50),default="unverified")
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class VideoProject(Base):
    __tablename__="video_projects"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    title: Mapped[str]=mapped_column(String(255)); pillar: Mapped[str]=mapped_column(String(100)); status: Mapped[str]=mapped_column(String(50),default="idea")
    progress: Mapped[int]=mapped_column(default=0); topic_id: Mapped[Optional[str]]=mapped_column(String(36),nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class ResearchSource(Base):
    __tablename__="research_sources"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    project_id: Mapped[str]=mapped_column(String(36)); title: Mapped[str]=mapped_column(String(255)); url: Mapped[str]=mapped_column(Text)
    publisher: Mapped[Optional[str]]=mapped_column(String(255),nullable=True); verified: Mapped[str]=mapped_column(String(30),default="unverified")
    notes: Mapped[Optional[str]]=mapped_column(Text,nullable=True); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class VideoScript(Base):
    __tablename__="video_scripts"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    project_id: Mapped[str]=mapped_column(String(36)); title: Mapped[str]=mapped_column(String(255)); hook: Mapped[Optional[str]]=mapped_column(Text,nullable=True)
    intro: Mapped[Optional[str]]=mapped_column(Text,nullable=True); narration: Mapped[Optional[str]]=mapped_column(Text,nullable=True); conclusion: Mapped[Optional[str]]=mapped_column(Text,nullable=True)
    status: Mapped[str]=mapped_column(String(30),default="draft"); word_count: Mapped[int]=mapped_column(default=0); updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class ScriptVersion(Base):
    __tablename__="script_versions"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    script_id: Mapped[str]=mapped_column(String(36)); content: Mapped[str]=mapped_column(Text); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class VideoScene(Base):
    __tablename__="video_scenes"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    project_id: Mapped[str]=mapped_column(String(36)); number: Mapped[int]=mapped_column(default=1); title: Mapped[str]=mapped_column(String(255))
    narration: Mapped[Optional[str]]=mapped_column(Text,nullable=True); visual: Mapped[Optional[str]]=mapped_column(Text,nullable=True); asset_type: Mapped[str]=mapped_column(String(50),default="AI-generated visual")
    duration: Mapped[int]=mapped_column(default=8); transition: Mapped[str]=mapped_column(String(50),default="Cut")

class MediaAsset(Base):
    __tablename__="media_assets"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    name: Mapped[str]=mapped_column(String(255)); asset_type: Mapped[str]=mapped_column(String(50)); file_location: Mapped[Optional[str]]=mapped_column(Text,nullable=True)
    mime_type: Mapped[Optional[str]]=mapped_column(String(100),nullable=True); size_bytes: Mapped[int]=mapped_column(default=0); source: Mapped[Optional[str]]=mapped_column(String(255),nullable=True)
    license: Mapped[str]=mapped_column(String(100),default="Unverified"); ai_generated: Mapped[str]=mapped_column(String(10),default="false")

class Approval(Base):
    __tablename__="approvals"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    project_id: Mapped[str]=mapped_column(String(36)); stage: Mapped[str]=mapped_column(String(50)); action: Mapped[str]=mapped_column(String(30))
    comments: Mapped[Optional[str]]=mapped_column(Text,nullable=True); reviewer: Mapped[str]=mapped_column(String(120),default="Current user")
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class RenderJob(Base):
    __tablename__="render_jobs"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    project_id: Mapped[str]=mapped_column(String(36)); preset: Mapped[str]=mapped_column(String(50)); status: Mapped[str]=mapped_column(String(30),default="queued")
    progress: Mapped[int]=mapped_column(default=0); attempts: Mapped[int]=mapped_column(default=0); output_path: Mapped[Optional[str]]=mapped_column(Text,nullable=True)

class YouTubeUpload(Base):
    __tablename__="youtube_uploads"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    project_id: Mapped[str]=mapped_column(String(36)); title: Mapped[str]=mapped_column(String(255)); visibility: Mapped[str]=mapped_column(String(30),default="private")
    status: Mapped[str]=mapped_column(String(30),default="not_started"); youtube_id: Mapped[Optional[str]]=mapped_column(String(100),nullable=True); approved: Mapped[str]=mapped_column(String(10),default="false")

class VideoAnalytics(Base):
    __tablename__="video_analytics"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    project_id: Mapped[str]=mapped_column(String(36)); views: Mapped[int]=mapped_column(default=0); watch_time_minutes: Mapped[int]=mapped_column(default=0)
    average_view_duration: Mapped[int]=mapped_column(default=0); subscribers: Mapped[int]=mapped_column(default=0); revenue: Mapped[str]=mapped_column(String(20),default="0.00")

router = APIRouter()

def create_crud(name: str, model: type[Base]):
    r = APIRouter(prefix=f"/api/{name}", tags=[name])
    @r.get("")
    def list_items(db: Session=Depends(get_db)):
        return [{column.name: getattr(row,column.name) for column in model.__table__.columns} for row in db.query(model).all()]
    @r.post("", status_code=201)
    def create_item(payload: dict[str, Any], db: Session=Depends(get_db), _user: dict=Depends(require_role("producer"))):
        allowed={column.name for column in model.__table__.columns}
        item=model(**{k:v for k,v in payload.items() if k in allowed and k not in ("id","created_at","updated_at")})
        db.add(item); db.commit(); db.refresh(item)
        return {column.name: getattr(item,column.name) for column in model.__table__.columns}
    @r.delete("/{item_id}", status_code=204)
    def delete_item(item_id: str, db: Session=Depends(get_db), _user: dict=Depends(require_role("admin"))):
        item=db.get(model,item_id)
        if not item: raise HTTPException(404,"Item not found")
        db.delete(item); db.commit()
        return None
    @r.patch("/{item_id}")
    def update_item(item_id: str, payload: dict[str, Any], db: Session=Depends(get_db), _user: dict=Depends(require_role("producer"))):
        item=db.get(model,item_id)
        if not item: raise HTTPException(404,"Item not found")
        allowed={column.name for column in model.__table__.columns}
        for key,value in payload.items():
            if key in allowed and key not in ("id","created_at","updated_at"): setattr(item,key,value)
        db.commit(); db.refresh(item)
        return {column.name: getattr(item,column.name) for column in model.__table__.columns}
    return r

for resource, model in (("channels",Channel),("pillars",ContentPillar),("topics",ContentTopic),("projects",VideoProject),("sources",ResearchSource),("scripts",VideoScript),("script-versions",ScriptVersion),("scenes",VideoScene),("media",MediaAsset),("approvals",Approval),("renders",RenderJob),("youtube",YouTubeUpload),("analytics",VideoAnalytics)):
    router.include_router(create_crud(resource,model))

@router.post("/api/approvals/{approval_id}/publish")
def approve_publish(approval_id: str, db: Session=Depends(get_db), _user: dict=Depends(require_role("reviewer"))):
    approval=db.get(Approval,approval_id)
    if not approval: raise HTTPException(404,"Approval not found")
    if approval.stage != "publishing": raise HTTPException(400,"Only publishing approvals can authorize a publication")
    return {"approved": True,"approval_id": approval_id,"publish_authorized": True}
