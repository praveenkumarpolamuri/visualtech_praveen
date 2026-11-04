import os
from fastapi import APIRouter

router=APIRouter(prefix="/api/integrations",tags=["integrations"])

@router.get("/status")
def status():
    return {
        "data_source":"provider configuration read from environment; no provider response is simulated as successful",
        "providers":{
            "gemini":{"configured":bool(os.getenv("GEMINI_API_KEY")),"operation":"primary free hosted topic generation"},
            "groq":{"configured":bool(os.getenv("GROQ_API_KEY")),"operation":"fast hosted fallback"},
            "ollama":{"configured":True,"operation":"local fallback when Ollama is running"},
            "openai":{"configured":bool(os.getenv("OPENAI_API_KEY")),"operation":"optional final paid fallback"},
            "image_generation":{"configured":False,"operation":"adapter-ready; no provider configured"},
            "voice":{"configured":False,"operation":"adapter-ready; no provider configured"},
            "youtube":{"configured":bool(os.getenv("YOUTUBE_CLIENT_ID") and os.getenv("YOUTUBE_CLIENT_SECRET")),"operation":"private upload and analytics require OAuth configuration"},
            "storage":{"configured":bool(os.getenv("S3_ENDPOINT")),"operation":"S3-compatible object storage"}
        },
        "publishing_guard":"A YouTube upload is never started unless final video and publishing approvals exist."
    }

@router.post("/youtube/validate-publish/{project_id}")
def validate_publish(project_id:str):
    return {"project_id":project_id,"allowed":False,"reason":"Human final-video and publishing approvals are required; YouTube credentials are not configured in this environment."}
