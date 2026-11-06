import hashlib
import json
import subprocess
import urllib.parse
from pathlib import Path

import boto3
import httpx

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import require_role
from app.modules.domain import MediaAsset, RenderJob, VideoScene

router = APIRouter(prefix="/api/renders", tags=["render worker"])


class RenderControl(BaseModel):
    source_path: str = ""
    output_path: str = ""


def commons_visual(query: str, media_type: str = "image") -> Path | None:
    mime_filter = "video/webm|video/mp4" if media_type == "video" else "image/jpeg|image/png"
    searches = [query, "photography camera smartphone"]
    words = query.split()
    if len(words) > 6:
        searches.insert(1, " ".join(words[:6]))
    for search in dict.fromkeys(searches):
        params = {
            "action": "query", "generator": "search", "gsrsearch": search,
            "gsrnamespace": 6, "gsrlimit": 12, "prop": "imageinfo",
            "iiprop": "url|mime|size", "iiurlwidth": 1280, "format": "json",
        }
        try:
            response = httpx.get(
                "https://commons.wikimedia.org/w/api.php",
                params=params,
                headers={"User-Agent": "VisualTechAI/1.0 (local documentary renderer; contact: local-admin@example.com)"},
                timeout=30,
            )
            response.raise_for_status()
            pages = response.json().get("query", {}).get("pages", {}).values()
            for page in pages:
                info = (page.get("imageinfo") or [{}])[0]
                mime = info.get("mime", "")
                if media_type == "video" and mime not in ("video/webm", "video/mp4"):
                    continue
                if media_type == "image" and mime not in ("image/jpeg", "image/png"):
                    continue
                url = info.get("thumburl") or info.get("url")
                filename = str(page.get("title", "")).removeprefix("File:")
                if media_type == "image" and filename:
                    url = "https://commons.wikimedia.org/wiki/Special:Redirect/file/" + urllib.parse.quote(filename, safe="") + "?width=1280"
                if not url:
                    continue
                visual = download_visual(url, media_type)
                if visual:
                    return visual
        except Exception:
            pass
    return None


def download_visual(url: str, media_type: str) -> Path | None:
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": "VisualTechAI/1.0 (local documentary renderer; contact: local-admin@example.com)"},
            follow_redirects=True,
        )
        response.raise_for_status()
        suffix = ".mp4" if media_type == "video" else (".jpg" if response.headers.get("content-type", "").startswith("image/jpeg") else ".png")
        target = Path("media") / "visual-cache" / (str(abs(hash(url))) + suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        return target
    except Exception:
        return None


def resolve_media_location(location: str | None) -> Path | None:
    if not location:
        return None
    path = Path(location)
    media_root = Path("media").resolve()
    try:
        resolved = path.resolve()
        resolved.relative_to(media_root)
        if resolved.is_file():
            return resolved
    except (OSError, ValueError):
        pass
    if not location.startswith("s3://"):
        return None
    settings = get_settings()
    parts = location.removeprefix("s3://").split("/", 1)
    if len(parts) != 2 or parts[0] != settings.s3_bucket or not (settings.s3_endpoint and settings.s3_access_key and settings.s3_secret_key):
        return None
    target = Path("media") / "render-cache" / (hashlib.sha256(location.encode()).hexdigest() + Path(parts[1]).suffix)
    if target.is_file():
        return target
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        boto3.client("s3", endpoint_url=settings.s3_endpoint, aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key).download_file(parts[0], parts[1], str(target))
        return target
    except Exception:
        return None


def ffmpeg_available() -> bool:
    return subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode == 0


@router.post("/{render_id}/compose/{project_id}")
def compose_storyboard(render_id: str, project_id: str, db: Session = Depends(get_db), _user: dict = Depends(require_role("producer"))):
    job = db.get(RenderJob, render_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Render job not found")
    latest_revision = db.query(func.max(VideoScene.revision)).filter(VideoScene.project_id == project_id).scalar()
    scenes = db.query(VideoScene).filter(
        VideoScene.project_id == project_id,
        VideoScene.revision == latest_revision,
    ).order_by(VideoScene.number).all()
    if not scenes:
        raise HTTPException(status_code=404, detail="No storyboard scenes found for this project")

    output = Path("media") / "public" / f"{project_id}.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    work = Path("media") / "render-work" / project_id
    work.mkdir(parents=True, exist_ok=True)
    voice_asset = db.query(MediaAsset).filter(
        MediaAsset.project_id == project_id,
        MediaAsset.asset_type == "audio",
    ).order_by(MediaAsset.created_at.desc()).first()
    voiceover = resolve_media_location(voice_asset.file_location) if voice_asset else None
    if voice_asset and not voiceover:
        raise HTTPException(status_code=422, detail="The project's voiceover asset is not available to the renderer")
    clips = []
    for scene in scenes:
        duration = max(3, int(scene.duration or 8))
        clip = work / f"scene-{scene.number}.mp4"
        query = " ".join(part for part in (scene.title, scene.visual) if part)
        visual = resolve_media_location(scene.visual) or commons_visual(query, "video") or commons_visual(query, "image")
        if visual and visual.suffix.lower() in (".mp4", ".webm"):
            command = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(visual), "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", str(duration), "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-shortest", str(clip)]
        elif visual:
            command = ["ffmpeg", "-y", "-loop", "1", "-i", str(visual), "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", str(duration), "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,zoompan=z='min(zoom+0.0015,1.12)':d=" + str(duration * 25) + ":s=1280x720:fps=25,fade=t=in:st=0:d=0.5,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-shortest", str(clip)]
        else:
            command = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x10203a:s=1280x720:r=25:d={duration}", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", str(duration), "-vf", "drawbox=x='0':y='0':w='iw':h='ih':color=0x172a4d@1:t=fill", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(clip)]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=duration * 8)
            clips.append(clip)
        except Exception as exc:
            job.status = "failed"
            job.output_path = None
            db.commit()
            raise HTTPException(status_code=500, detail=f"Could not render scene {scene.number}: {exc}") from exc

    concat = work / "clips.txt"
    concat.write_text("".join(f"file '{clip.resolve()}'\n" for clip in clips))
    silent_output = work / "silent-video.mp4" if voiceover else output
    job.status = "rendering"
    job.progress = 50
    job.output_path = str(output)
    db.commit()
    try:
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", "-movflags", "+faststart", str(silent_output)], check=True, capture_output=True, timeout=300)
        if voiceover:
            subprocess.run(["ffmpeg", "-y", "-i", str(silent_output), "-i", str(voiceover), "-map", "0:v:0", "-map", "1:a:0", "-af", "apad", "-c:v", "copy", "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(output)], check=True, capture_output=True, timeout=300)
        job.status = "completed"
        job.progress = 100
        db.commit()
        db.refresh(job)
        return {"id": job.id, "status": job.status, "progress": job.progress, "output_path": job.output_path, "scenes_rendered": len(scenes), "visual_mode": "attached assets and Wikimedia Commons fallback", "audio_mode": "project voiceover" if voiceover else "silent"}
    except Exception as exc:
        job.status = "failed"
        db.commit()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{render_id}/start")
def start_render(render_id: str, control: RenderControl, db: Session = Depends(get_db), _user: dict = Depends(require_role("producer"))):
    job = db.get(RenderJob, render_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Render job not found")
    source = Path(control.source_path)
    if not source.is_file() or not ffmpeg_available():
        raise HTTPException(status_code=422, detail="Source file and FFmpeg must be available")
    output = control.output_path or f"media/public/render-{render_id}.mp4"
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
