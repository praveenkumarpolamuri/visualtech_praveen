import json
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_role
from app.modules.domain import RenderJob

router = APIRouter(prefix="/api/renders", tags=["render worker"])


class RenderControl(BaseModel):
    source_path: str = ""
    output_path: str = ""


def ffmpeg_available() -> bool:
    return subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode == 0


@router.post("/{render_id}/start")
def start_render(render_id: str, control: RenderControl, db: Session = Depends(get_db), _user: dict = Depends(require_role("producer"))):
    job = db.get(RenderJob, render_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Render job not found")
    source = Path(control.source_path)
    if not source.is_file() or not ffmpeg_available():
        raise HTTPException(status_code=422, detail="Source file and FFmpeg must be available")
    output = control.output_path or f"media/render-{render_id}.mp4"
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    job.status = "rendering"
    job.attempts = job.attempts + 1
    job.progress = 0
    job.output_path = output
    db.commit()
    try:
        duration_cmd = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(source)], capture_output=True, text=True, check=True)
        duration = max(float(json.loads(duration_cmd.stdout).get("format", {}).get("duration", 0)), 0.1)
        command = ["ffmpeg", "-y", "-i", str(source), "-vf", "scale='min(1920,iw)':-2", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-movflags", "+faststart", output]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            job.status = "failed"
            db.commit()
            raise HTTPException(status_code=500, detail=result.stderr[-2000:])
        job.status = "completed"
        job.progress = 100
        db.commit()
        db.refresh(job)
        return job
    except HTTPException:
        raise
    except Exception as exc:
        job.status = "failed"
        db.commit()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{render_id}/retry")
def retry_render(render_id: str, db: Session = Depends(get_db), _user: dict = Depends(require_role("producer"))):
    job = db.get(RenderJob, render_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Render job not found")
    job.status = "queued"
    job.progress = 0
    db.commit()
    db.refresh(job)
    return job


@router.post("/{render_id}/cancel")
def cancel_render(render_id: str, db: Session = Depends(get_db), _user: dict = Depends(require_role("producer"))):
    job = db.get(RenderJob, render_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Render job not found")
    job.status = "cancelled"
    db.commit()
    db.refresh(job)
    return job
