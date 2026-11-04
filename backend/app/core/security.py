from datetime import datetime, timedelta, timezone
from typing import Optional
import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.config import get_settings

bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str, roles: list[str]) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": subject, "roles": roles, "iat": now, "exp": now + timedelta(minutes=settings.access_token_expire_minutes)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def require_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> dict:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        payload = jwt.decode(credentials.credentials, get_settings().jwt_secret, algorithms=["HS256"])
        return payload
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc


def require_role(role: str):
    def guard(user: dict = Depends(require_user)) -> dict:
        if role not in user.get("roles", []):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Role '{role}' required")
        return user
    return guard
