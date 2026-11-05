import base64
import re
import uuid
import wave
from io import BytesIO
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import require_role
from app.modules.domain import VideoProject, VideoScene
from app.modules.storage import store_media_bytes

router = APIRouter(prefix="/api/integrations/openai", tags=["media generation"])


class ImageRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=4000)
    size: Literal["1024x1024", "1536x1024", "1024x1536"] = "1024x1024"
    scene_id: str | None = None


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=100000)
    voice: Literal["alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer"] = "alloy"
    project_id: str | None = None


def openai_key() -> str:
    key = get_settings().openai_api_key
    if not key:
        raise HTTPException(status_code=503, detail="Configure OPENAI_API_KEY to use image and speech generation")
    return key


def split_text_chunks(text: str, maximum_chars: int = 3500) -> list[str]:
    chunks = []
    current = ""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    for sentence in sentences:
        parts = [sentence]
        if len(sentence) > maximum_chars:
            words = sentence.split()
            parts = []
            fragment = ""
            for word in words:
                if len(word) > maximum_chars:
                    if fragment:
                        parts.append(fragment)
                        fragment = ""
                    parts.extend(word[index:index + maximum_chars] for index in range(0, len(word), maximum_chars))
                    continue
                candidate = f"{fragment} {word}".strip()
                if len(candidate) > maximum_chars and fragment:
                    parts.append(fragment)
                    fragment = word
                else:
                    fragment = candidate
            if fragment:
                parts.append(fragment)
        for part in parts:
            candidate = f"{current} {part}".strip()
            if len(candidate) > maximum_chars and current:
                chunks.append(current)
                current = part
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


def combine_wav_chunks(chunks: list[bytes]) -> bytes:
    if not chunks:
        raise ValueError("No generated speech audio")
    output = BytesIO()
    with wave.open(output, "wb") as writer:
        parameters = None
        for chunk in chunks:
            with wave.open(BytesIO(chunk), "rb") as reader:
                current_parameters = reader.getparams()
                if parameters is None:
                    parameters = current_parameters
                    writer.setparams(parameters)
                elif (
                    current_parameters.nchannels,
                    current_parameters.sampwidth,
                    current_parameters.framerate,
                    current_parameters.comptype,
                    current_parameters.compname,
                ) != (
                    parameters.nchannels,
                    parameters.sampwidth,
                    parameters.framerate,
                    parameters.comptype,
                    parameters.compname,
                ):
                    raise ValueError("Speech chunks have incompatible audio formats")
                writer.writeframes(reader.readframes(reader.getnframes()))
    return output.getvalue()


@router.post("/images", status_code=201)
def generate_image(request: ImageRequest, db: Session = Depends(get_db), _user: dict = Depends(require_role("producer"))):
    key = openai_key()
    scene = db.get(VideoScene, request.scene_id) if request.scene_id else None
    if request.scene_id and not scene:
        raise HTTPException(status_code=404, detail="Storyboard scene not found")
    try:
        response = httpx.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "gpt-image-1", "prompt": request.prompt, "size": request.size},
            timeout=180,
        )
        response.raise_for_status()
        image = base64.b64decode(response.json()["data"][0]["b64_json"])
        asset = store_media_bytes(image, f"generated-{uuid.uuid4().hex}.png", "image/png", "OpenAI", db, scene.project_id if scene else None)
        if scene:
            scene.visual = asset.file_location
            scene.asset_type = "generated image"
            db.commit()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Image provider returned HTTP {exc.response.status_code}") from exc
    except (httpx.RequestError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Image generation failed") from exc
    return {"id": asset.id, "name": asset.name, "file_location": asset.file_location, "mime_type": asset.mime_type}


@router.post("/speech", status_code=201)
def generate_speech(request: SpeechRequest, db: Session = Depends(get_db), _user: dict = Depends(require_role("producer"))):
    key = openai_key()
    if not request.text.strip():
        raise HTTPException(status_code=422, detail="Voiceover text cannot be blank")
    if request.project_id and not db.get(VideoProject, request.project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        audio_chunks = []
        for text_chunk in split_text_chunks(request.text):
            response = httpx.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": "tts-1", "input": text_chunk, "voice": request.voice, "response_format": "wav"},
                timeout=180,
            )
            response.raise_for_status()
            audio_chunks.append(response.content)
        audio = combine_wav_chunks(audio_chunks)
        asset = store_media_bytes(audio, f"voiceover-{uuid.uuid4().hex}.wav", "audio/wav", "OpenAI", db, request.project_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Speech provider returned HTTP {exc.response.status_code}") from exc
    except (httpx.RequestError, ValueError, wave.Error) as exc:
        raise HTTPException(status_code=502, detail="Speech generation failed") from exc
    return {"id": asset.id, "name": asset.name, "file_location": asset.file_location, "mime_type": asset.mime_type}