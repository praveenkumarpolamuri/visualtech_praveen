import secrets
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.core.config import get_settings
from app.core.security import create_access_token, require_user

router = APIRouter(prefix="/api/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    roles: list[str]


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest):
    settings = get_settings()
    if payload.email.strip().lower() != settings.bootstrap_admin_email.lower() or not secrets.compare_digest(payload.password, settings.bootstrap_admin_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(payload.email.lower(), ["admin", "producer", "reviewer"])
    return TokenResponse(access_token=token, roles=["admin", "producer", "reviewer"])


@router.get("/me")
def me(user: dict = Depends(require_user)):
    return {"email": user["sub"], "roles": user.get("roles", [])}
