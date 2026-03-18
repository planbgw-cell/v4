"""
이메일 로그인/회원가입 API. JWT는 HttpOnly 쿠키로 설정.
구글·애플 OAuth2 소셜 로그인 포함.
"""
import base64
import json
import logging
import os
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.auth.config import (
    get_google_redirect_uri,
    get_apple_redirect_uri,
    get_google_client_id,
    get_apple_client_id,
    google_oauth_configured,
    apple_oauth_configured,
)
from app.auth.oauth_clients import (
    exchange_code_for_token,
    fetch_userinfo_google,
    fetch_userinfo_apple,
)
from app.auth.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    hash_password,
    verify_password,
)
from app.auth.dependencies import get_current_user
from app.crud import create_user, get_user_by_email
from app.database import get_db
from app.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_KEY = "access_token"
COOKIE_MAX_AGE = ACCESS_TOKEN_EXPIRE_MINUTES * 60


class SignupBody(BaseModel):
    email: EmailStr
    password: str


class LoginBody(BaseModel):
    email: EmailStr
    password: str


@router.post("/signup")
def signup(body: SignupBody, db: Session = Depends(get_db)):
    """중복 이메일 체크 후 비밀번호 암호화 저장."""
    if get_user_by_email(db, body.email):
        raise HTTPException(status_code=400, detail="이미 등록된 이메일입니다.")
    hashed = hash_password(body.password)
    user = create_user(db, email=body.email, hashed_password=hashed, provider="local")
    return {"message": "회원가입 완료", "user_id": str(user.id), "email": user.email}


@router.post("/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    """비밀번호 확인 후 JWT를 HttpOnly 쿠키에 저장."""
    user = get_user_by_email(db, body.email)
    if not user or not user.hashed_password:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
    token = create_access_token(user.id, expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    response = JSONResponse(content={"message": "로그인 성공", "user_id": str(user.id), "email": user.email})
    response.set_cookie(
        key=COOKIE_KEY,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=os.getenv("COOKIE_SECURE", "false").lower() in ("true", "1"),
    )
    return response


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    """현재 로그인 사용자 정보. 쿠키 또는 Bearer 토큰 필요. 미인증 시 401."""
    return {"user_id": str(current_user.id), "email": current_user.email}


@router.post("/logout")
def logout():
    """access_token 쿠키 삭제. 인증 불필요. set_cookie(max_age=0)로 로그인 시와 동일한 옵션 사용해 확실히 제거."""
    response = JSONResponse(content={"message": "로그아웃되었습니다."})
    response.set_cookie(
        key=COOKIE_KEY,
        value="",
        max_age=0,
        path="/",
        httponly=True,
        samesite="lax",
        secure=os.getenv("COOKIE_SECURE", "false").lower() in ("true", "1"),
    )
    return response


# ---------- 소셜 로그인 (Google / Apple) ----------


def _build_state(next_path: str | None) -> str:
    """state 파라미터: next 경로 인코딩 (리다이렉트 복원용)."""
    payload = {"next": (next_path or "/").strip() or "/"}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def _parse_state(state: str | None) -> str:
    """state에서 next 경로 추출."""
    if not state:
        return "/"
    try:
        padded = state + "=" * (4 - len(state) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded).decode())
        return (data.get("next") or "/").strip() or "/"
    except Exception:
        return "/"


@router.get("/google/login")
async def google_login(next_path: str | None = Query(None, alias="next")):
    """구글 OAuth2 authorize URL로 리다이렉트."""
    if not google_oauth_configured():
        raise HTTPException(status_code=503, detail="Google OAuth not configured")
    state = _build_state(next_path)
    params = {
        "response_type": "code",
        "client_id": get_google_client_id(),
        "redirect_uri": get_google_redirect_uri(),
        "scope": "email profile",
        "state": state,
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return RedirectResponse(url=url, status_code=302)


@router.get("/google/callback")
async def google_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """구글 callback: code로 토큰 교환 → userinfo → 유저 조회/생성 → JWT 쿠키 → 리다이렉트."""
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")
    redirect_uri = get_google_redirect_uri()
    token_data = await exchange_code_for_token("google", code, redirect_uri)
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="Google did not return access_token")
    userinfo = await fetch_userinfo_google(access_token)
    logger.info("Google profile: %s", userinfo)
    email = (userinfo.get("email") or "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="Google did not return email")
    user = get_user_by_email(db, email)
    if not user:
        user = create_user(db, email=email, hashed_password=None, provider="google")
    elif user.provider not in ("google", "local"):
        raise HTTPException(status_code=400, detail="이미 다른 소셜 계정으로 가입된 이메일입니다.")
    token = create_access_token(user.id, expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    next_path = _parse_state(state)
    response = RedirectResponse(url=next_path, status_code=302)
    response.set_cookie(
        key=COOKIE_KEY,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=os.getenv("COOKIE_SECURE", "false").lower() in ("true", "1"),
    )
    return response


@router.get("/apple/login")
async def apple_login(next_path: str | None = Query(None, alias="next")):
    """애플 OAuth2 authorize URL로 리다이렉트."""
    if not apple_oauth_configured():
        raise HTTPException(status_code=503, detail="Apple OAuth not configured")
    state = _build_state(next_path)
    params = {
        "response_type": "code id_token",
        "response_mode": "query",
        "client_id": get_apple_client_id(),
        "redirect_uri": get_apple_redirect_uri(),
        "scope": "name email",
        "state": state,
    }
    url = "https://appleid.apple.com/auth/authorize?" + urlencode(params)
    return RedirectResponse(url=url, status_code=302)


@router.get("/apple/callback")
async def apple_callback(
    code: str | None = Query(None),
    id_token: str | None = Query(None),
    state: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """애플 callback: code로 토큰 교환 후 id_token에서 이메일·sub 추출 → 유저 조회/생성 → JWT 쿠키 → 리다이렉트."""
    if not code and not id_token:
        raise HTTPException(status_code=400, detail="Missing code and id_token")
    redirect_uri = get_apple_redirect_uri()
    token_data = {}
    if code:
        token_data = await exchange_code_for_token("apple", code, redirect_uri)
    id_token_raw = id_token or token_data.get("id_token")
    if not id_token_raw:
        raise HTTPException(status_code=400, detail="Apple id_token not available")
    userinfo = await fetch_userinfo_apple(id_token_raw)
    logger.info("Apple profile: %s", userinfo)
    email = (userinfo.get("email") or "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="Apple did not return email")
    user = get_user_by_email(db, email)
    if not user:
        user = create_user(db, email=email, hashed_password=None, provider="apple")
    elif user.provider not in ("apple", "local"):
        raise HTTPException(status_code=400, detail="이미 다른 소셜 계정으로 가입된 이메일입니다.")
    token = create_access_token(user.id, expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    next_path = _parse_state(state)
    response = RedirectResponse(url=next_path, status_code=302)
    response.set_cookie(
        key=COOKIE_KEY,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=os.getenv("COOKIE_SECURE", "false").lower() in ("true", "1"),
    )
    return response
