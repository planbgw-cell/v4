import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy import text

from app.auth.security import verify_password
from app.database import SessionLocal

ADMIN_COOKIE_KEY = "admin_access_token"
ADMIN_ALGORITHM = "HS256"
ADMIN_ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12
ADMIN_SECRET_KEY = os.getenv("ADMIN_JWT_SECRET", "flairy_admin_dev_secret_change_me")


def create_admin_access_token(admin_id: UUID, role: str = "super_admin") -> str:
    payload = {
        "sub": str(admin_id),
        "role": role,
        "is_admin": True,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ADMIN_ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, ADMIN_SECRET_KEY, algorithm=ADMIN_ALGORITHM)


def decode_admin_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, ADMIN_SECRET_KEY, algorithms=[ADMIN_ALGORITHM])
    except JWTError:
        return None


def _wants_html(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    sec_fetch_mode = (request.headers.get("sec-fetch-mode") or "").lower()
    return ("text/html" in accept) or (sec_fetch_mode == "navigate")


def authenticate_admin(username: str, password: str) -> dict | None:
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                "SELECT id, username, hashed_password, role "
                "FROM admin_users WHERE username = :username"
            ),
            {"username": (username or "").strip()},
        ).mappings().first()
        if not row:
            return None
        if not verify_password(password, row["hashed_password"]):
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "role": row.get("role") or "super_admin",
        }
    finally:
        db.close()


def get_admin_payload_optional(request: Request) -> dict | None:
    token = request.cookies.get(ADMIN_COOKIE_KEY)
    if not token:
        return None
    payload = decode_admin_access_token(token)
    if not payload or not payload.get("is_admin"):
        return None
    return payload


def require_admin_api(request: Request):
    token = request.cookies.get(ADMIN_COOKIE_KEY)
    user_token = request.cookies.get("access_token")
    if not token:
        if not request.url.path.startswith("/api/"):
            return RedirectResponse(url="/admin/login", status_code=302)
        if user_token:
            raise HTTPException(status_code=403, detail="Admin privileges required")
        raise HTTPException(status_code=401, detail="Admin authentication required")
    payload = decode_admin_access_token(token)
    if not payload or not payload.get("is_admin"):
        if not request.url.path.startswith("/api/"):
            return RedirectResponse(url="/admin/login", status_code=302)
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return payload

