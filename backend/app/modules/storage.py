import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import copyfileobj
from urllib.parse import quote

import boto3
import jwt
from botocore.client import Config
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.config import get_settings
from app.core.security import require_role
from app.modules.domain import MediaAsset, VideoProject

router = APIRouter(prefix="/api/storage", tags=["storage"])


def get_limited_upload_size(file, maximum: int) -> int:
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > maximum:
        raise HTTPException(status_code=413, detail=f"Media upload exceeds the {maximum}-byte limit")
    return size


def store_media_file(file, filename: str, content_type: str, size_bytes: int, db: Session, project_id: str | None = None) -> MediaAsset:
    settings = get_settings()
    extension = Path(filename).suffix
    object_name = f"visualtech/{uuid.uuid4().hex}{extension}"
    if settings.s3_endpoint and settings.s3_access_key and settings.s3_secret_key:
        client = boto3.client("s3", endpoint_url=settings.s3_endpoint, aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key, config=Config(signature_version="s3v4"))
        bucket = settings.s3_bucket
        client.upload_fileobj(file, bucket, object_name, ExtraArgs={"ContentType": content_type})
        location = f"s3://{bucket}/{object_name}"
    else:
        destination = Path("media") / "private-assets" / object_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as output:
            copyfileobj(file, output, length=1024 * 1024)
        location = str(destination)

    mime_group = content_type.split("/", 1)[0]
    asset = MediaAsset(
        name=filename,
        asset_type=mime_group if mime_group in ("audio", "image", "video") else "file",
        file_location=location,
        mime_type=content_type,
        size_bytes=size_bytes,
        source="User upload",
        license="Unverified",
        ai_generated="false",
        project_id=project_id,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def store_media_bytes(content: bytes, filename: str, content_type: str, source: str, db: Session, project_id: str | None = None) -> MediaAsset:
    settings = get_settings()
    extension = Path(filename).suffix
    object_name = f"visualtech/{uuid.uuid4().hex}{extension}"
    if settings.s3_endpoint and settings.s3_access_key and settings.s3_secret_key:
        client = boto3.client("s3", endpoint_url=settings.s3_endpoint, aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key, config=Config(signature_version="s3v4"))
        bucket = settings.s3_bucket
        client.put_object(Bucket=bucket, Key=object_name, Body=content, ContentType=content_type)
        location = f"s3://{bucket}/{object_name}"
    else:
        destination = Path("media") / "private-assets" / object_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        location = str(destination)

    mime_group = content_type.split("/", 1)[0]
    asset = MediaAsset(
        name=filename,
        asset_type=mime_group if mime_group in ("audio", "image", "video") else "file",
        file_location=location,
        mime_type=content_type,
        size_bytes=len(content),
        source=source,
        license="AI-generated" if source == "OpenAI" else "Unverified",
        ai_generated="true" if source == "OpenAI" else "false",
        project_id=project_id,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/{asset_id}/url")
def get_media_url(asset_id: str, db: Session = Depends(get_db), _user: dict = Depends(require_role("producer"))):
    asset = db.get(MediaAsset, asset_id)
    if not asset or not asset.file_location:
        raise HTTPException(status_code=404, detail="Media asset not found")
    if asset.file_location.startswith("s3://"):
        settings = get_settings()
        bucket_key = asset.file_location.removeprefix("s3://").split("/", 1)
        if len(bucket_key) != 2 or bucket_key[0] != settings.s3_bucket or not (settings.s3_endpoint and settings.s3_access_key and settings.s3_secret_key):
            raise HTTPException(status_code=503, detail="Object storage is not configured")
        try:
            client = boto3.client("s3", endpoint_url=settings.s3_endpoint, aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key, config=Config(signature_version="s3v4"))
            url = client.generate_presigned_url("get_object", Params={"Bucket": bucket_key[0], "Key": bucket_key[1]}, ExpiresIn=3600)
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Could not create an object download link") from exc
        return {"url": url}

    media_root = Path("media").resolve()
    asset_path = Path(asset.file_location).resolve()
    try:
        relative_path = asset_path.relative_to(media_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Media asset is outside the media directory") from exc
    if not asset_path.is_file():
        raise HTTPException(status_code=404, detail="Media file is missing")
    token = jwt.encode(
        {"purpose": "media_asset", "asset_id": asset.id, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        get_settings().jwt_secret,
        algorithm="HS256",
    )
    return {"url": f"/api/storage/{asset.id}/content?token={quote(token)}"}


@router.get("/{asset_id}/content")
def get_media_content(asset_id: str, token: str = Query(min_length=1), db: Session = Depends(get_db)):
    try:
        claims = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired media link") from exc
    if claims.get("purpose") != "media_asset" or claims.get("asset_id") != asset_id:
        raise HTTPException(status_code=401, detail="Invalid media link")
    asset = db.get(MediaAsset, asset_id)
    if not asset or not asset.file_location or asset.file_location.startswith("s3://"):
        raise HTTPException(status_code=404, detail="Local media asset not found")
    media_root = Path("media").resolve()
    asset_path = Path(asset.file_location).resolve()
    try:
        asset_path.relative_to(media_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Media asset is outside the media directory") from exc
    if not asset_path.is_file():
        raise HTTPException(status_code=404, detail="Media file is missing")
    return FileResponse(asset_path, media_type=asset.mime_type or "application/octet-stream", filename=asset.name)


@router.post("/upload")
def upload_media(file: UploadFile = File(...), project_id: str | None = Form(None), db: Session = Depends(get_db), _user: dict = Depends(require_role("producer"))):
    if project_id and not db.get(VideoProject, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    size_bytes = get_limited_upload_size(file.file, get_settings().media_upload_max_bytes)
    if not size_bytes:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")
    try:
        asset = store_media_file(file.file, file.filename or "asset", file.content_type or "application/octet-stream", size_bytes, db, project_id)
        return {"provider": "S3" if asset.file_location and asset.file_location.startswith("s3://") else "local", "location": asset.file_location, "filename": asset.name, "asset_id": asset.id}
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"Media storage failed: {exc}") from exc
