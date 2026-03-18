"""
OAuth2 토큰 교환 및 userinfo 조회 (Google / Apple). httpx 사용.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import jwt as pyjwt

from app.auth.config import (
    get_apple_client_id,
    get_apple_key_id,
    get_apple_private_key,
    get_apple_team_id,
    get_google_client_id,
    get_google_client_secret,
)

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
APPLE_TOKEN_URL = "https://appleid.apple.com/auth/token"


def _apple_client_secret() -> str:
    """Apple client_secret JWT (ES256) 생성."""
    key_id = get_apple_key_id()
    team_id = get_apple_team_id()
    private_key_pem = get_apple_private_key()
    client_id = get_apple_client_id()
    if not all([key_id, team_id, private_key_pem, client_id]):
        return ""
    try:
        key = private_key_pem.replace("\\n", "\n").encode("utf-8")
        now = datetime.now(timezone.utc)
        payload = {
            "iss": team_id,
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "aud": "https://appleid.apple.com",
            "sub": client_id,
        }
        return pyjwt.encode(
            payload,
            key,
            algorithm="ES256",
            headers={"kid": key_id},
        )
    except Exception as e:
        logger.warning("Apple client_secret JWT 생성 실패: %s", e)
        return ""


async def exchange_code_for_token(provider: str, code: str, redirect_uri: str) -> dict[str, Any]:
    """
    authorization code로 access_token(및 id_token) 교환.
    provider: "google" | "apple"
    반환: {"access_token", "id_token"(Apple 시), "token_type", ...}
    """
    if provider == "google":
        data = {
            "code": code,
            "client_id": get_google_client_id(),
            "client_secret": get_google_client_secret(),
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        url = GOOGLE_TOKEN_URL
    elif provider == "apple":
        client_secret = _apple_client_secret()
        if not client_secret:
            raise ValueError("Apple OAuth not configured (client_secret)")
        data = {
            "code": code,
            "client_id": get_apple_client_id(),
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        url = APPLE_TOKEN_URL
    else:
        raise ValueError(f"Unknown provider: {provider}")

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, data=data, headers={"Accept": "application/json"})
    if resp.status_code >= 400:
        logger.warning("%s token exchange failed: %s %s", provider, resp.status_code, resp.text)
        from fastapi import HTTPException
        raise HTTPException(status_code=502, detail=f"OAuth token exchange failed: {resp.text}")
    return resp.json()


async def fetch_userinfo_google(access_token: str) -> dict[str, Any]:
    """
    Google access_token으로 userinfo 조회.
    반환: {"email", "provider_sub"(sub), "name"(선택)}
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code >= 400:
        logger.warning("Google userinfo failed: %s %s", resp.status_code, resp.text)
        from fastapi import HTTPException
        raise HTTPException(status_code=502, detail="Google userinfo failed")
    data = resp.json()
    return {
        "email": data.get("email") or "",
        "provider_sub": data.get("sub") or "",
        "name": data.get("name"),
    }


def _decode_apple_id_token(id_token: str) -> dict[str, Any]:
    """Apple id_token JWT 디코딩 (서명 검증 생략, 토큰은 이미 Apple token 엔드포인트에서 수신)."""
    try:
        payload = pyjwt.decode(
            id_token,
            options={"verify_signature": False},
            algorithms=["ES256", "RS256"],
        )
        return payload
    except pyjwt.PyJWTError as e:
        logger.warning("Apple id_token decode failed: %s", e)
        return {}


async def fetch_userinfo_apple(id_token: str) -> dict[str, Any]:
    """
    Apple id_token(JWT)에서 email, sub 추출.
    반환: {"email", "provider_sub"(sub), "name"(없을 수 있음)}
    """
    payload = _decode_apple_id_token(id_token)
    # Apple은 최초 인증 시에만 email을 주고, 이후에는 빈 값일 수 있음.
    email = (payload.get("email") or "").strip()
    sub = (payload.get("sub") or "").strip()
    return {
        "email": email,
        "provider_sub": sub,
        "name": payload.get("name"),
    }
