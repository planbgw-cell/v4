"""
OAuth2 토큰 교환 및 userinfo 조회 (Google / Kakao). httpx 사용.
"""
import logging
from typing import Any

import httpx

from app.auth.config import (
    get_google_client_id,
    get_google_client_secret,
    get_kakao_client_id,
    get_kakao_client_secret,
)

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_USERINFO_URL = "https://kapi.kakao.com/v2/user/me"


async def exchange_code_for_token(provider: str, code: str, redirect_uri: str) -> dict[str, Any]:
    """
    authorization code로 access_token(및 id_token) 교환.
    provider: "google" | "kakao"
    반환: {"access_token", "token_type", ...}
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
    elif provider == "kakao":
        data = {
            "code": code,
            "client_id": get_kakao_client_id(),
            "client_secret": get_kakao_client_secret(),
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        url = KAKAO_TOKEN_URL
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


async def fetch_userinfo_kakao(access_token: str) -> dict[str, Any]:
    """
    Kakao access_token으로 userinfo 조회.
    반환: {"email", "provider_sub"(id), "name"(선택)}
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            KAKAO_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code >= 400:
        logger.warning("Kakao userinfo failed: %s %s", resp.status_code, resp.text)
        from fastapi import HTTPException
        raise HTTPException(status_code=502, detail="Kakao userinfo failed")

    data = resp.json()
    kakao_account = data.get("kakao_account") or {}
    profile = kakao_account.get("profile") or {}
    email = (kakao_account.get("email") or "").strip()
    kakao_id = str(data.get("id") or "").strip()
    name = profile.get("nickname") or None
    return {
        "email": email,
        "provider_sub": kakao_id,
        "name": name,
    }
