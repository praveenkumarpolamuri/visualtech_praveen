import uuid
from pathlib import Path

import boto3
from botocore.client import Config
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from app.core.config import get_settings
from app.core.security import require_role

router = APIRouter(prefix="/api/storage", tags=["storage"])


@router.post("/upload")
def upload_media(file: UploadFile = File(...), _user: dict = Depends(require_role("producer"))):
    settings = get_settings()
    extension = Path(file.filename or "asset").suffix
    object_name = f"visualtech/{uuid.uuid4().hex}{extension}"
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")

    if settings.s3_endpoint and settings.s3_access_key and settings.s3_secret_key:
        try:
            client = boto3.client("s3", endpoint_url=settings.s3_endpoint, aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key, config=Config(signature_version="s3v4"))
            bucket = getattr(settings, "s3_bucket", "visualtech-media")
            client.put_object(Bucket=bucket, Key=object_name, Body=content, ContentType=file.content_type or "application/octet-stream")
            return {"provider": "S3", "location": object_name, "filename": file.filename}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Object storage upload failed: {exc}") from exc

    destination = Path("media") / object_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return {"provider": "local", "location": str(destination), "filename": file.filename}
