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


def gemini_key() -> str:
    key = get_settings().gemini_api_key
    if not key:
        raise HTTPException(status_code=503, detail="Configure GEMINI_API_KEY to use image and speech generation")
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


def pcm_to_wav(pcm: bytes, sample_rate: int = 24000) -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm)
    return output.getvalue()


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
    key = gemini_key()
    scene = db.get(VideoScene, request.scene_id) if request.scene_id else None
    if request.scene_id and not scene:
        raise HTTPException(status_code=404, detail="Storyboard scene not found")
    try:
        response = httpx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent",
            params={"key": key},
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": request.prompt}]}],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
            },
            timeout=180,
        )
        response.raise_for_status()
        parts = response.json()["candidates"][0]["content"]["parts"]
        inline = next(part["inlineData"] for part in parts if "inlineData" in part)
        image = base64.b64decode(inline["data"])
        mime_type = inline.get("mimeType", "image/png")
        extension = "png" if "png" in mime_type else "jpg"
        asset = store_media_bytes(image, f"generated-{uuid.uuid4().hex}.{extension}", mime_type, "Google Gemini", db, scene.project_id if scene else None)
        if scene:
            scene.visual = asset.file_location
            scene.asset_type = "generated image"
            db.commit()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Gemini image provider returned HTTP {exc.response.status_code}: {exc.response.text}") from exc
    except (httpx.RequestError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Image generation failed") from exc
    return {"id": asset.id, "name": asset.name, "file_location": asset.file_location, "mime_type": asset.mime_type}


@router.post("/speech", status_code=201)
def generate_speech(request: SpeechRequest, db: Session = Depends(get_db), _user: dict = Depends(require_role("producer"))):
    key = gemini_key()
    if not request.text.strip():
        raise HTTPException(status_code=422, detail="Voiceover text cannot be blank")
    if request.project_id and not db.get(VideoProject, request.project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        voice_names = {"alloy": "Kore", "ash": "Charon", "coral": "Aoede", "echo": "Fenrir", "fable": "Puck", "onyx": "Fenrir", "nova": "Kore", "sage": "Aoede", "shimmer": "Aoede"}
        pcm_audio = bytearray()
        for text_chunk in split_text_chunks(request.text):
            response = httpx.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent",
                params={"key": key},
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": text_chunk}]}],
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice_names.get(request.voice, "Kore")}}},
                    },
                },
                timeout=180,
            )
            response.raise_for_status()
            parts = response.json()["candidates"][0]["content"]["parts"]
            inline = next(part["inlineData"] for part in parts if "inlineData" in part)
            pcm_audio.extend(base64.b64decode(inline["data"]))
        audio = pcm_to_wav(bytes(pcm_audio))
        asset = store_media_bytes(audio, f"voiceover-{uuid.uuid4().hex}.wav", "audio/wav", "Google Gemini", db, request.project_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Gemini speech provider returned HTTP {exc.response.status_code}: {exc.response.text}") from exc
    except (httpx.RequestError, KeyError, StopIteration, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Gemini speech generation failed") from exc
    return {"id": asset.id, "name": asset.name, "file_location": asset.file_location, "mime_type": asset.mime_type}