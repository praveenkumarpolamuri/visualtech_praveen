import json
import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import require_role
from app.modules.domain import Approval, IntegrationCredential, OAuthState, RenderJob, VideoAnalytics, YouTubeUpload, utcnow

router = APIRouter(prefix="/api/integrations", tags=["integrations"])
YOUTUBE_SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/yt-analytics.readonly"
MAX_UPLOAD_ATTEMPTS = 5


def youtube_configured() -> bool:
    settings = get_settings()
    return bool(settings.youtube_client_id and settings.youtube_client_secret)


def credential_cipher() -> Fernet:
    key = get_settings().youtube_token_encryption_key
    if not key:
        raise HTTPException(status_code=503, detail="Configure YOUTUBE_TOKEN_ENCRYPTION_KEY before connecting YouTube")
    try:
        return Fernet(key.encode())
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="YOUTUBE_TOKEN_ENCRYPTION_KEY must be a valid Fernet key") from exc


def read_token(db: Session) -> dict:
    credential = db.get(IntegrationCredential, "youtube")
    if not credential:
        raise HTTPException(status_code=503, detail="Connect a YouTube account before using this operation")
    try:
        return json.loads(credential_cipher().decrypt(credential.encrypted_token.encode()))
    except (InvalidToken, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Stored YouTube credentials cannot be decrypted; reconnect the account") from exc


def save_token(db: Session, token: dict) -> None:
    credential = db.get(IntegrationCredential, "youtube")
    encrypted = credential_cipher().encrypt(json.dumps(token).encode()).decode()
    if credential:
        credential.encrypted_token = encrypted
    else:
        db.add(IntegrationCredential(provider="youtube", encrypted_token=encrypted))
    db.commit()


def get_upload_session(upload: YouTubeUpload) -> str | None:
    if not upload.resumable_url:
        return None
    try:
        return credential_cipher().decrypt(upload.resumable_url.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Stored YouTube upload session cannot be decrypted; retry the upload") from exc


def access_token(db: Session) -> str:
    settings = get_settings()
    token = read_token(db)
    if token.get("access_token") and int(token.get("expires_at", 0)) > int(time.time()) + 60:
        return token["access_token"]
    refresh = token.get("refresh_token")
    if not refresh:
        raise HTTPException(status_code=503, detail="YouTube authorization expired; reconnect the account")
    try:
        response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={"client_id": settings.youtube_client_id, "client_secret": settings.youtube_client_secret, "refresh_token": refresh, "grant_type": "refresh_token"},
            timeout=30,
        )
        response.raise_for_status()
        updated = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Could not refresh YouTube authorization") from exc
    token.update(updated)
    token["refresh_token"] = refresh
    token["expires_at"] = int(time.time()) + int(updated.get("expires_in", 3600))
    save_token(db, token)
    return token["access_token"]


def approved_stages(db: Session, project_id: str) -> set[str]:
    rows = db.query(func.lower(Approval.stage)).filter(
        Approval.project_id == project_id,
        func.lower(Approval.action) == "approved",
        func.lower(Approval.stage).in_(("final_video", "publishing")),
    ).all()
    return {row[0] for row in rows}


def consume_oauth_state(db: Session, state: str) -> bool:
    now = utcnow()
    consumed = db.query(OAuthState).filter(
        OAuthState.state_hash == hashlib.sha256(state.encode()).hexdigest(),
        OAuthState.consumed_at.is_(None),
        OAuthState.expires_at > now,
    ).update({OAuthState.consumed_at: now}, synchronize_session=False)
    db.commit()
    return consumed == 1


def upsert_video_analytics(db: Session, upload: YouTubeUpload, row: list) -> VideoAnalytics:
    analytics = db.query(VideoAnalytics).filter(VideoAnalytics.youtube_upload_id == upload.id).first()
    if analytics is None:
        analytics = db.query(VideoAnalytics).filter(
            VideoAnalytics.project_id == upload.project_id,
            VideoAnalytics.youtube_upload_id.is_(None),
        ).first()
        if analytics is None:
            analytics = VideoAnalytics(project_id=upload.project_id)
            db.add(analytics)
        analytics.youtube_upload_id = upload.id
    analytics.views = int(row[0] or 0)
    analytics.watch_time_minutes = int(row[1] or 0)
    analytics.average_view_duration = int(row[2] or 0)
    analytics.subscribers = int(row[3] or 0)
    return analytics


@router.get("/status")
def status(db: Session = Depends(get_db)):
    settings = get_settings()
    youtube_connected = db.get(IntegrationCredential, "youtube") is not None
    return {
        "data_source": "provider configuration and connected account state",
        "providers": {
            "gemini": {"configured": bool(settings.gemini_api_key), "operation": "primary hosted topic generation"},
            "groq": {"configured": bool(settings.groq_api_key), "operation": "hosted fallback generation"},
            "ollama": {"configured": bool(settings.ollama_url and settings.ollama_model), "operation": "local fallback when Ollama is running"},
            "openai": {"configured": bool(settings.openai_api_key), "operation": "optional AI fallback, images, and speech"},
            "image_generation": {"configured": bool(settings.openai_api_key), "operation": "OpenAI image generation"},
            "voice": {"configured": bool(settings.openai_api_key), "operation": "OpenAI text-to-speech"},
            "youtube": {"configured": youtube_configured(), "token_storage_configured": bool(settings.youtube_token_encryption_key), "connected": youtube_connected, "operation": "OAuth upload, publishing, and analytics"},
            "storage": {"configured": bool(settings.s3_endpoint and settings.s3_access_key and settings.s3_secret_key), "operation": "S3-compatible object storage; local storage is used otherwise"},
        },
        "publishing_guard": "Final-video and publishing approvals plus a completed render are required before upload.",
    }


@router.get("/youtube/authorize")
def authorize_youtube(db: Session = Depends(get_db), _user: dict = Depends(require_role("admin"))):
    if not youtube_configured():
        raise HTTPException(status_code=503, detail="Configure YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET")
    settings = get_settings()
    if not settings.youtube_token_encryption_key:
        raise HTTPException(status_code=503, detail="Configure YOUTUBE_TOKEN_ENCRYPTION_KEY before connecting YouTube")
    credential_cipher()
    state = secrets.token_urlsafe(32)
    now = utcnow()
    db.query(OAuthState).filter(OAuthState.expires_at <= now).delete(synchronize_session=False)
    db.add(OAuthState(state_hash=hashlib.sha256(state.encode()).hexdigest(), expires_at=now + timedelta(minutes=10)))
    db.commit()
    params = {
        "client_id": settings.youtube_client_id,
        "redirect_uri": settings.youtube_redirect_uri,
        "response_type": "code",
        "scope": YOUTUBE_SCOPES,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return {"authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)}


@router.get("/youtube/callback")
def youtube_callback(code: str = Query(min_length=1), state: str = Query(min_length=1), db: Session = Depends(get_db)):
    settings = get_settings()
    if not consume_oauth_state(db, state):
        raise HTTPException(status_code=400, detail="Invalid, expired, or already used OAuth state")
    try:
        response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={"code": code, "client_id": settings.youtube_client_id, "client_secret": settings.youtube_client_secret, "redirect_uri": settings.youtube_redirect_uri, "grant_type": "authorization_code"},
            timeout=30,
        )
        response.raise_for_status()
        token = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="YouTube authorization exchange failed") from exc
    existing = db.get(IntegrationCredential, "youtube")
    if not token.get("refresh_token") and existing:
        previous = read_token(db)
        token["refresh_token"] = previous.get("refresh_token")
    if not token.get("refresh_token"):
        raise HTTPException(status_code=502, detail="Google did not return a refresh token; remove this app's access in Google Account permissions and reconnect")
    token["expires_at"] = int(time.time()) + int(token.get("expires_in", 3600))
    save_token(db, token)
    return RedirectResponse(url=f"{settings.frontend_url.rstrip('/')}/studio/youtube?connected=1", status_code=303)


def validate_youtube_upload(db: Session, upload: YouTubeUpload) -> Path:
    if not {"final_video", "publishing"}.issubset(approved_stages(db, upload.project_id)):
        raise HTTPException(status_code=403, detail="Final-video and publishing approvals are both required")
    if upload.approved.lower() != "true":
        raise HTTPException(status_code=403, detail="Mark the upload record approved before publishing")
    job = db.query(RenderJob).filter(RenderJob.project_id == upload.project_id, RenderJob.status == "completed").order_by(RenderJob.id.desc()).first()
    video_path = Path(job.output_path) if job and job.output_path else None
    if not video_path or not video_path.is_file():
        raise HTTPException(status_code=422, detail="A completed render file is required before publishing")
    visibility = upload.visibility.lower()
    if visibility not in ("private", "unlisted", "public"):
        raise HTTPException(status_code=422, detail="Visibility must be private, unlisted, or public")
    metadata = {"snippet": {"title": upload.title, "categoryId": "28"}, "status": {"privacyStatus": visibility}}
    if upload.scheduled_at:
        scheduled = upload.scheduled_at
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        if scheduled <= datetime.now(timezone.utc):
            raise HTTPException(status_code=422, detail="Scheduled publish time must be in the future")
        if visibility != "private":
            raise HTTPException(status_code=422, detail="Scheduled YouTube videos must use private visibility")
    return video_path


def claim_youtube_upload(db: Session, upload: YouTubeUpload, allow_failed: bool = False) -> bool:
    now = utcnow()
    query = db.query(YouTubeUpload).filter(
        YouTubeUpload.id == upload.id,
        YouTubeUpload.youtube_id.is_(None),
    )
    if allow_failed:
        query = query.filter(YouTubeUpload.status.in_(("not_started", "queued", "failed")))
    else:
        query = query.filter(or_(
            YouTubeUpload.status.in_(("not_started", "queued")),
            and_(YouTubeUpload.status == "failed", YouTubeUpload.retry_after <= now),
            and_(YouTubeUpload.status == "uploading", YouTubeUpload.claimed_at <= now - timedelta(minutes=30)),
        ), YouTubeUpload.upload_attempts < MAX_UPLOAD_ATTEMPTS)
    updated = query.update({
        YouTubeUpload.status: "uploading",
        YouTubeUpload.upload_attempts: YouTubeUpload.upload_attempts + 1,
        YouTubeUpload.retry_after: None,
        YouTubeUpload.claimed_at: now,
    }, synchronize_session=False)
    db.commit()
    if updated:
        db.refresh(upload)
    return updated == 1


def record_upload_failure(db: Session, upload: YouTubeUpload, message: str, retryable: bool = True) -> None:
    upload.status = "failed"
    upload.last_error = message[:1000]
    upload.claimed_at = None
    attempt = max(upload.upload_attempts, 1)
    if retryable and attempt < MAX_UPLOAD_ATTEMPTS:
        delay_minutes = min(5 * 2 ** (attempt - 1), 360)
        upload.retry_after = utcnow() + timedelta(minutes=delay_minutes)
    else:
        upload.retry_after = None
    db.commit()


def upload_resumable_video(db: Session, upload: YouTubeUpload, video_path: Path, token: str, metadata: dict) -> str:
    total_size = video_path.stat().st_size
    session_url = get_upload_session(upload)
    resuming_existing = session_url is not None
    if not session_url:
        initiation = httpx.post(
            "https://www.googleapis.com/upload/youtube/v3/videos",
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(total_size),
            },
            content=json.dumps(metadata),
            timeout=30,
        )
        initiation.raise_for_status()
        session_url = initiation.headers.get("Location")
        if not session_url:
            raise HTTPException(status_code=502, detail="YouTube did not return an upload session")
        upload.resumable_url = credential_cipher().encrypt(session_url.encode()).decode()
        db.commit()

    offset = 0
    if resuming_existing and upload.upload_attempts > 1:
        probe = httpx.put(
            session_url,
            headers={"Authorization": f"Bearer {token}", "Content-Length": "0", "Content-Range": f"bytes */{total_size}"},
            content=b"",
            timeout=30,
        )
        if probe.status_code in (200, 201):
            return probe.json()["id"]
        if probe.status_code in (404, 410):
            upload.resumable_url = None
            db.commit()
            return upload_resumable_video(db, upload, video_path, token, metadata)
        if probe.status_code != 308:
            probe.raise_for_status()
            raise HTTPException(status_code=502, detail="YouTube returned an unexpected upload-session status")
        received_range = probe.headers.get("Range", "")
        if received_range:
            offset = int(received_range.rsplit("-", 1)[-1]) + 1

    with video_path.open("rb") as video:
        video.seek(offset)
        while offset < total_size:
            chunk = video.read(8 * 1024 * 1024)
            if not chunk:
                break
            end = offset + len(chunk) - 1
            response = httpx.put(
                session_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{end}/{total_size}",
                },
                content=chunk,
                timeout=300,
            )
            if response.status_code in (200, 201):
                return response.json()["id"]
            if response.status_code != 308:
                response.raise_for_status()
                raise HTTPException(status_code=502, detail="YouTube returned an unexpected upload-session status")
            received_range = response.headers.get("Range", "")
            offset = int(received_range.rsplit("-", 1)[-1]) + 1 if received_range else end + 1
    raise HTTPException(status_code=502, detail="YouTube upload session ended before the video was complete")


def publish_claimed_upload(db: Session, upload: YouTubeUpload, video_path: Path) -> dict:
    visibility = upload.visibility.lower()
    metadata = {"snippet": {"title": upload.title, "categoryId": "28"}, "status": {"privacyStatus": visibility}}
    if upload.scheduled_at:
        scheduled = upload.scheduled_at
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        metadata["status"]["publishAt"] = scheduled.isoformat().replace("+00:00", "Z")
    try:
        token = access_token(db)
        youtube_id = upload_resumable_video(db, upload, video_path, token, metadata)
    except HTTPException as exc:
        record_upload_failure(db, upload, str(exc.detail), retryable=exc.status_code >= 500)
        raise
    except httpx.HTTPStatusError as exc:
        retryable = exc.response.status_code in (408, 429) or exc.response.status_code >= 500
        record_upload_failure(db, upload, f"YouTube upload failed with HTTP {exc.response.status_code}", retryable)
        raise HTTPException(status_code=502, detail=f"YouTube upload failed with HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        record_upload_failure(db, upload, "YouTube upload request failed")
        raise HTTPException(status_code=502, detail="YouTube upload failed") from exc
    except (KeyError, ValueError) as exc:
        record_upload_failure(db, upload, "YouTube returned an invalid upload response", retryable=False)
        raise HTTPException(status_code=502, detail="YouTube upload failed") from exc
    upload.youtube_id = youtube_id
    upload.status = "scheduled" if upload.scheduled_at else "uploaded"
    upload.claimed_at = None
    upload.retry_after = None
    upload.last_error = None
    upload.resumable_url = None
    db.commit()
    return {"youtube_id": youtube_id, "status": upload.status, "url": f"https://www.youtube.com/watch?v={youtube_id}"}


@router.post("/youtube/publish/{upload_id}")
def publish_youtube(upload_id: str, db: Session = Depends(get_db), _user: dict = Depends(require_role("reviewer"))):
    upload = db.get(YouTubeUpload, upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail="YouTube upload record not found")
    video_path = validate_youtube_upload(db, upload)
    if not claim_youtube_upload(db, upload, allow_failed=True):
        raise HTTPException(status_code=409, detail="This upload is already in progress or has already been published")
    return publish_claimed_upload(db, upload, video_path)


@router.post("/youtube/sync-analytics")
def sync_youtube_analytics(db: Session = Depends(get_db), _user: dict = Depends(require_role("producer"))):
    token = access_token(db)
    uploads = db.query(YouTubeUpload).filter(YouTubeUpload.youtube_id.isnot(None)).all()
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=30)
    synced = 0
    for upload in uploads:
        try:
            response = httpx.get(
                "https://youtubeanalytics.googleapis.com/v2/reports",
                headers={"Authorization": f"Bearer {token}"},
                params={"ids": "channel==MINE", "startDate": start_date.isoformat(), "endDate": end_date.isoformat(), "metrics": "views,estimatedMinutesWatched,averageViewDuration,subscribersGained", "filters": f"video=={upload.youtube_id}"},
                timeout=30,
            )
            response.raise_for_status()
            rows = response.json().get("rows", [])
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="YouTube Analytics request failed; verify that the Analytics API is enabled") from exc
        if not rows:
            continue
        row = rows[0]
        upsert_video_analytics(db, upload, row)
        synced += 1
    db.commit()
    return {"synced_videos": synced, "window_days": 30}


@router.post("/youtube/validate-publish/{project_id}")
def validate_publish(project_id: str, db: Session = Depends(get_db), _user: dict = Depends(require_role("reviewer"))):
    approvals = approved_stages(db, project_id)
    render = db.query(RenderJob).filter(RenderJob.project_id == project_id, RenderJob.status == "completed").order_by(RenderJob.id.desc()).first()
    checks = {
        "final_video_approved": "final_video" in approvals,
        "publishing_approved": "publishing" in approvals,
        "completed_render": bool(render and render.output_path and Path(render.output_path).is_file()),
        "youtube_connected": db.get(IntegrationCredential, "youtube") is not None and youtube_configured(),
    }
    return {"project_id": project_id, "allowed": all(checks.values()), "checks": checks}
