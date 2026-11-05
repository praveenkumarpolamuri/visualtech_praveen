from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.config import get_settings
from app.core.database import Base, engine
from app.modules.dashboard import models  # noqa: F401
from app.modules.dashboard.router import router as dashboard_router
from app.modules.domain import router as domain_router, ContentPillar, ContentTopic, VideoProject, ResearchSource, VideoScript, VideoScene, MediaAsset, Approval, RenderJob
from app.integrations.providers import router as integrations_router
from app.integrations.media_generation import router as media_generation_router
from app.core.auth import router as auth_router
from app.modules.agent import router as agent_router
from app.modules.render_worker import router as render_worker_router
from app.modules.storage import router as storage_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.environment == "production" and settings.jwt_secret == "change-this-jwt-secret-in-production":
        raise RuntimeError("JWT_SECRET must be configured in production")
    if settings.environment == "production" and settings.bootstrap_admin_password == "change-me":
        raise RuntimeError("BOOTSTRAP_ADMIN_PASSWORD must be configured in production")
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
if settings.environment == "production":
    if not settings.cors_origin_list or settings.cors_origin_list == ["*"]:
        raise RuntimeError("CORS_ORIGINS must contain explicit frontend origins in production")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/auth") else response.headers.get("Cache-Control", "")
    return response
app.include_router(dashboard_router)
app.include_router(domain_router)
app.include_router(integrations_router)
app.include_router(media_generation_router)
app.include_router(auth_router)
app.include_router(agent_router)
app.include_router(render_worker_router)
app.include_router(storage_router)
media_directory = (Path("media") / "public").resolve()
media_directory.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(media_directory)), name="media")


@app.get("/api/health")
def health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        return JSONResponse(status_code=503, content={"status": "unhealthy", "service": "visualtech-api", "environment": settings.environment})
    return {"status": "healthy", "service": "visualtech-api", "environment": settings.environment}
