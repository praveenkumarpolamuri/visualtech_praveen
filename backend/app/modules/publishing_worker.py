import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import and_, or_

from app.core.database import SessionLocal
from app.integrations.providers import claim_youtube_upload, publish_claimed_upload, validate_youtube_upload, youtube_configured
from app.modules.domain import IntegrationCredential, YouTubeUpload, utcnow

logger = logging.getLogger(__name__)


def retry_delay_minutes(attempt: int) -> int:
    return min(5 * 2 ** max(attempt - 1, 0), 360)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def process_scheduled_upload(upload_id: str) -> None:
    db = SessionLocal()
    try:
        if not youtube_configured() or db.get(IntegrationCredential, "youtube") is None:
            return
        upload = db.get(YouTubeUpload, upload_id)
        if not upload or upload.status not in ("not_started", "queued", "failed", "uploading") or not upload.scheduled_at:
            return
        now = utcnow()
        if upload.status == "failed" and (upload.retry_after is None or as_utc(upload.retry_after) > now):
            return
        stale_claim = upload.status == "uploading" and upload.claimed_at and as_utc(upload.claimed_at) <= now - timedelta(minutes=30)
        if upload.status == "uploading" and not stale_claim:
            return
        if upload.upload_attempts >= 5 and stale_claim:
            upload.status = "failed"
            upload.claimed_at = None
            upload.last_error = "Upload worker lease expired after the maximum retry count"
            db.commit()
            return
        scheduled_at = as_utc(upload.scheduled_at)
        if scheduled_at <= now:
            upload.status = "schedule_missed"
            upload.claimed_at = None
            upload.last_error = "Scheduled time passed before the video could be uploaded; choose a future time to retry"
            db.commit()
            return
        try:
            video_path = validate_youtube_upload(db, upload)
        except HTTPException as exc:
            logger.info("Scheduled YouTube upload %s is waiting for prerequisites: %s", upload_id, exc.detail)
            return
        if not claim_youtube_upload(db, upload):
            return
        try:
            publish_claimed_upload(db, upload, video_path)
        except HTTPException as exc:
            logger.warning("Scheduled YouTube upload %s failed: %s", upload_id, exc.detail)
    except Exception:
        logger.exception("Scheduled YouTube upload processing failed for %s", upload_id)
    finally:
        db.close()


async def scheduled_publisher_loop() -> None:
    while True:
        await asyncio.sleep(30)
        db = SessionLocal()
        try:
            now = utcnow()
            upload_ids = [row[0] for row in db.query(YouTubeUpload.id).filter(
                YouTubeUpload.scheduled_at.isnot(None),
                or_(
                    YouTubeUpload.status.in_(("not_started", "queued")),
                    and_(YouTubeUpload.status == "failed", YouTubeUpload.retry_after <= now),
                    and_(YouTubeUpload.status == "uploading", YouTubeUpload.claimed_at <= now - timedelta(minutes=30)),
                ),
            ).order_by(YouTubeUpload.scheduled_at.asc()).limit(20).all()]
        except Exception:
            logger.exception("Could not load scheduled YouTube uploads")
            upload_ids = []
        finally:
            db.close()

        for upload_id in upload_ids:
            await asyncio.to_thread(process_scheduled_upload, upload_id)