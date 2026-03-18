"""
인증 의존성: 쿠키 또는 Bearer 토큰에서 JWT 해석 후 현재 유저 조회.
"""
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.crud import get_user_by_id
from app.database import get_db

COOKIE_KEY = "access_token"
http_bearer = HTTPBearer(auto_error=False)


def _token_from_request(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str | None:
    """쿠키 access_token 우선, 없으면 Authorization: Bearer."""
    token = request.cookies.get(COOKIE_KEY)
    if token:
        return token
    if credentials:
        return credentials.credentials
    return None


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
    db: Session = Depends(get_db),
):
    """
    JWT를 쿠키 또는 Authorization 헤더에서 읽어 검증 후 User 반환.
    없거나 만료/무효 시 401.
    """
    token = _token_from_request(request, credentials)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id_str = decode_access_token(token)
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    try:
        user_id = UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
    db: Session = Depends(get_db),
):
    """
    JWT가 있으면 User 반환, 없거나 무효면 None.
    페이지 라우트에서 로그인 선택 처리용.
    """
    token = _token_from_request(request, credentials)
    if not token:
        return None
    user_id_str = decode_access_token(token)
    if not user_id_str:
        return None
    try:
        user_id = UUID(user_id_str)
    except ValueError:
        return None
    user = get_user_by_id(db, user_id)
    return user
