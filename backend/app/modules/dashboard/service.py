from sqlalchemy import func
from sqlalchemy.orm import Session
from app.modules.domain import Approval, RenderJob, VideoAnalytics, VideoProject, YouTubeUpload

PIPELINE_STAGES = (
    ("Ideas", "idea", "#64748b"),
    ("Research", "research", "#38bdf8"),
    ("Script", "script", "#818cf8"),
    ("Production", "production", "#a78bfa"),
    ("Review", "review", "#f59e0b"),
    ("Approved", "approved", "#10b981"),
    ("Published", "published", "#3b82f6"),
)


def _count(db: Session, status: str) -> int:
    return db.query(VideoProject).filter(func.lower(VideoProject.status) == status).count()


def get_dashboard(db: Session) -> dict:
    projects = db.query(VideoProject).order_by(VideoProject.created_at.desc()).limit(10).all()
    total = db.query(VideoProject).count()
    published = _count(db, "published")
    in_production = db.query(VideoProject).filter(func.lower(VideoProject.status).in_(("production", "rendering"))).count()
    awaiting = db.query(Approval).filter(func.lower(Approval.action).in_(("pending", "changes_requested"))).count()
    views = db.query(func.coalesce(func.sum(VideoAnalytics.views), 0)).scalar() or 0

    pipeline = [
        {"stage": label, "count": _count(db, status), "color": color}
        for label, status, color in PIPELINE_STAGES
    ]

    recent_projects = [
        {
            "id": project.id,
            "title": project.title,
            "pillar": project.pillar,
            "status": project.status.title(),
            "progress": project.progress,
            "updated": project.created_at.isoformat() if project.created_at else "",
            "thumbnail": project.pillar.lower(),
        }
        for project in projects
    ]

    approvals = db.query(Approval).order_by(Approval.created_at.desc()).limit(5).all()
    activities = [
        {
            "icon": "check",
            "text": f"{approval.stage.title()} {approval.action.replace('_', ' ')}",
            "detail": approval.project_id,
            "time": approval.created_at.isoformat() if approval.created_at else "",
        }
        for approval in approvals
    ]

    render_jobs = db.query(RenderJob).order_by(RenderJob.id.desc()).limit(5).all()
    automation = [
        {
            "name": f"Render job · {job.preset}",
            "status": job.status.title(),
            "ran": "" if job.status == "queued" else job.output_path or "Job status updated",
            "duration": f"{job.progress}% complete",
        }
        for job in render_jobs
    ]

    uploads = db.query(YouTubeUpload).all()

    return {
        "metrics": [
            {"key": "total_videos", "label": "Total videos", "value": total, "trend": "", "tone": "blue"},
            {"key": "in_production", "label": "In production", "value": in_production, "trend": "", "tone": "violet"},
            {"key": "awaiting_approval", "label": "Awaiting approval", "value": awaiting, "trend": "", "tone": "amber"},
            {"key": "published", "label": "Published videos", "value": published, "trend": "", "tone": "green"},
            {"key": "views", "label": "YouTube views", "value": views, "trend": "", "tone": "blue"},
        ],
        "pipeline": pipeline,
        "recentProjects": recent_projects,
        "schedule": [],
        "activities": activities,
        "automation": automation,
        "youtube_connected": any(upload.youtube_id for upload in uploads),
        "source": "database",
        "note": "Live database data. Analytics are zero until an integration records them.",
    }
