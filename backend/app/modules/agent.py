import json
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import require_role
from app.modules.domain import ContentTopic, ScriptVersion, VideoScript, VideoScene

router = APIRouter(prefix="/api/agent", tags=["AI agent"])


class GenerateTopicsRequest(BaseModel):
    brief: str = Field(min_length=3, max_length=2000)
    count: int = Field(default=3, ge=1, le=10)


class GenerateScriptRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=36)
    title: str = Field(min_length=3, max_length=255)
    brief: str = Field(min_length=3, max_length=4000)


class GenerateStoryboardRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=36)
    script_id: str = Field(min_length=1, max_length=36)
    scene_count: int = Field(default=8, ge=3, le=20)


class ResearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    project_id: str = Field(min_length=1, max_length=36)
    limit: int = Field(default=5, ge=1, le=10)


def parse_topics(content: str) -> list[dict]:
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
    parsed = json.loads(content)
    if isinstance(parsed, dict):
        parsed = parsed.get("topics", parsed.get("ideas", []))
    if not isinstance(parsed, list):
        raise ValueError("AI response did not contain a topic list")
    return parsed


def topic_prompt(brief: str, count: int) -> str:
    return (
        "Generate exactly " + str(count) + " documentary topic ideas for this brief: " + brief + ". "
        "Return only a valid JSON object with a 'topics' array. Each item must contain "
        "title, pillar, priority (high/medium/low), and description. "
        "Do not invent sources, statistics, or factual claims."
    )


def generate_with_openai_compatible(url: str, key: str, model: str, prompt: str) -> str:
    response = httpx.post(
        url,
        headers={"Authorization": "Bearer " + key},
        json={"model": model, "messages": [{"role": "system", "content": "You create factual documentary topic ideas."}, {"role": "user", "content": prompt}], "temperature": 0.7},
        timeout=90,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def generate_json_with_providers(prompt: str) -> tuple[dict, str]:
    settings = get_settings()
    errors = []
    if settings.gemini_api_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
            response = httpx.post(url, params={"key": settings.gemini_api_key}, json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.7}}, timeout=60)
            response.raise_for_status()
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
            return json.loads(text), "Google Gemini"
        except Exception as exc:
            errors.append(f"Gemini: {exc}")
    if settings.groq_api_key:
        try:
            text = generate_with_openai_compatible("https://api.groq.com/openai/v1/chat/completions", settings.groq_api_key, settings.groq_model, prompt)
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
            return json.loads(text), "Groq"
        except Exception as exc:
            errors.append(f"Groq: {exc}")
    try:
        response = httpx.post(settings.ollama_url.rstrip("/") + "/api/generate", json={"model": settings.ollama_model, "prompt": prompt, "stream": False, "format": "json"}, timeout=180)
        response.raise_for_status()
        return json.loads(response.json()["response"]), "Ollama (local)"
    except Exception as exc:
        errors.append(f"Ollama: {exc}")
    if settings.openai_api_key:
        try:
            text = generate_with_openai_compatible("https://api.openai.com/v1/chat/completions", settings.openai_api_key, settings.openai_model, prompt)
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
            return json.loads(text), "OpenAI"
        except Exception as exc:
            errors.append(f"OpenAI: {exc}")
    raise HTTPException(status_code=503, detail="No AI provider available. " + " | ".join(errors[-3:]))


def generate_topics_with_providers(brief: str, count: int) -> tuple[list[dict], str]:
    settings = get_settings()
    prompt = topic_prompt(brief, count)
    errors = []

    if settings.gemini_api_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
            response = httpx.post(url, params={"key": settings.gemini_api_key}, json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.7}}, timeout=60)
            response.raise_for_status()
            return parse_topics(response.json()["candidates"][0]["content"]["parts"][0]["text"]), "Google Gemini"
        except Exception as exc:
            errors.append(f"Gemini: {exc}")

    if settings.groq_api_key:
        try:
            content = generate_with_openai_compatible("https://api.groq.com/openai/v1/chat/completions", settings.groq_api_key, settings.groq_model, prompt)
            return parse_topics(content), "Groq"
        except Exception as exc:
            errors.append(f"Groq: {exc}")

    try:
        url = settings.ollama_url.rstrip("/") + "/api/generate"
        response = httpx.post(url, json={"model": settings.ollama_model, "prompt": prompt, "stream": False, "format": "json"}, timeout=180)
        response.raise_for_status()
        return parse_topics(response.json()["response"]), "Ollama (local)"
    except Exception as exc:
        errors.append(f"Ollama: {exc}")

    if settings.openai_api_key:
        try:
            content = generate_with_openai_compatible("https://api.openai.com/v1/chat/completions", settings.openai_api_key, settings.openai_model, prompt)
            return parse_topics(content), "OpenAI"
        except Exception as exc:
            errors.append(f"OpenAI: {exc}")

    raise HTTPException(status_code=503, detail="No AI provider available. Configure Gemini, Groq, OpenAI, or install Ollama. " + " | ".join(errors[-3:]))


@router.post("/topics")
def generate_topics(request: GenerateTopicsRequest, db: Session = Depends(get_db), _user: dict = Depends(require_role("producer"))):
    ideas, provider = generate_topics_with_providers(request.brief, request.count)
    created = []
    for idea in ideas[:request.count]:
        if not isinstance(idea, dict) or not str(idea.get("title", "")).strip():
            continue
        item = ContentTopic(title=str(idea["title"]).strip(), pillar=str(idea.get("pillar", "General")).strip() or "General", priority=str(idea.get("priority", "medium")).strip().lower(), description=str(idea.get("description", "")).strip())
        db.add(item)
        created.append(item)
    if not created:
        raise HTTPException(status_code=502, detail="AI returned no usable topic ideas")
    db.commit()
    for item in created:
        db.refresh(item)
    return {"provider": provider, "items": created}


@router.post("/script")
def generate_script(request: GenerateScriptRequest, db: Session = Depends(get_db), _user: dict = Depends(require_role("producer"))):
    prompt = (
        "Write a documentary narration script for the title: " + request.title + ". "
        "Use this production brief: " + request.brief + ". Return only a JSON object with "
        "hook, intro, narration, and conclusion strings. Avoid unsupported claims and keep the complete narration between 800 and 1200 words."
    )
    script_data, provider = generate_json_with_providers(prompt)
    hook = str(script_data.get("hook", "")).strip()
    intro = str(script_data.get("intro", "")).strip()
    narration = str(script_data.get("narration", "")).strip()
    conclusion = str(script_data.get("conclusion", "")).strip()
    full_text = "\n\n".join(part for part in [hook, intro, narration, conclusion] if part)
    if not full_text:
        raise HTTPException(status_code=502, detail="AI did not return a usable script")
    script = VideoScript(project_id=request.project_id, title=request.title, hook=hook, intro=intro, narration=narration, conclusion=conclusion, status="draft", word_count=len(full_text.split()))
    db.add(script)
    db.flush()
    db.add(ScriptVersion(script_id=script.id, content=full_text))
    db.commit()
    db.refresh(script)
    return {"provider": provider, "script": script}


@router.post("/storyboard")
def generate_storyboard(request: GenerateStoryboardRequest, db: Session = Depends(get_db), _user: dict = Depends(require_role("producer"))):
    script = db.get(VideoScript, request.script_id)
    if script is None:
        raise HTTPException(status_code=404, detail="Script not found")
    source = "\n".join(part for part in [script.hook, script.intro, script.narration, script.conclusion] if part)
    prompt = (
        "Turn this documentary script into exactly " + str(request.scene_count) + " scenes. "
        "Return only a JSON object with a scenes array. Each scene has number, title, narration, visual, "
        "asset_type, duration, and transition. SCRIPT:\n" + source[:12000]
    )
    data, provider = generate_json_with_providers(prompt)
    scenes = data.get("scenes", []) if isinstance(data, dict) else []
    if not isinstance(scenes, list) or not scenes:
        raise HTTPException(status_code=502, detail="AI did not return usable storyboard scenes")
    created = []
    db.query(VideoScene).filter(VideoScene.project_id == request.project_id).delete(synchronize_session=False)
    for index, scene in enumerate(scenes[:request.scene_count], start=1):
        if not isinstance(scene, dict):
            continue
        item = VideoScene(project_id=request.project_id, number=index, title=str(scene.get("title", f"Scene {index}"))[:255], narration=str(scene.get("narration", "")), visual=str(scene.get("visual", "")), asset_type=str(scene.get("asset_type", "AI-generated visual"))[:50], duration=max(1, int(scene.get("duration", 8))), transition=str(scene.get("transition", "Cut"))[:50])
        db.add(item)
        created.append(item)
    if not created:
        raise HTTPException(status_code=502, detail="AI did not return usable storyboard scenes")
    db.commit()
    for item in created:
        db.refresh(item)
    return {"provider": provider, "items": created}


@router.post("/research")
def generate_research(request: ResearchRequest, db: Session = Depends(get_db), _user: dict = Depends(require_role("producer"))):
    response = httpx.get("https://api.duckduckgo.com/", params={"q": request.query, "format": "json", "no_html": 1, "skip_disambig": 1}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    results = []
    for topic in payload.get("RelatedTopics", []):
        if isinstance(topic, dict) and topic.get("FirstURL") and topic.get("Text"):
            results.append({"title": topic["Text"][:255], "url": topic["FirstURL"]})
        for nested in topic.get("Topics", []) if isinstance(topic, dict) else []:
            if nested.get("FirstURL") and nested.get("Text"):
                results.append({"title": nested["Text"][:255], "url": nested["FirstURL"]})
    created = []
    from app.modules.domain import ResearchSource
    for result in results[:request.limit]:
        item = ResearchSource(project_id=request.project_id, title=result["title"], url=result["url"], publisher="DuckDuckGo Instant Answer", verified="unverified")
        db.add(item)
        created.append(item)
    db.commit()
    for item in created:
        db.refresh(item)
    return {"provider": "DuckDuckGo", "items": created}
