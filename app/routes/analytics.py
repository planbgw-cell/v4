from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.crud import (
    add_session_stay_duration,
    create_visitor_log,
    upsert_visitor_session,
)
from app.database import get_db
from app.utils.analytics_helper import (
    parse_browser_name,
    parse_device_type,
    parse_inflow_channel,
    parse_os_name,
)

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


class CollectBody(BaseModel):
    session_id: str = Field(min_length=8, max_length=64)
    referrer_url: str | None = None
    landing_page: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_term: str | None = None
    utm_content: str | None = None


class StayTimeBody(BaseModel):
    session_id: str = Field(min_length=8, max_length=64)
    stay_duration: int = Field(ge=0, le=86400)


def _hash_ip(ip: str | None) -> str | None:
    raw = (ip or "").strip()
    if not raw:
        return None
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def extract_analytics_session_id(request: Request) -> str | None:
    header_id = (request.headers.get("x-flairy-session-id") or "").strip()
    if header_id:
        return header_id[:64]
    cookie_id = (request.cookies.get("flairy_analytics_sid") or "").strip()
    if cookie_id:
        return cookie_id[:64]
    return None


@router.post("/collect")
async def collect_analytics(
    request: Request,
    body: CollectBody,
    db: Session = Depends(get_db),
):
    ua = request.headers.get("user-agent", "")
    device = parse_device_type(ua)
    os_name = parse_os_name(ua)
    browser = parse_browser_name(ua)
    inflow = parse_inflow_channel(body.referrer_url, body.utm_source)
    ip_hash = _hash_ip(request.client.host if request.client else None)

    upsert_visitor_session(
        db,
        session_id=body.session_id.strip()[:64],
        inflow_channel=inflow,
        landing_page=(body.landing_page or "")[:1024] or None,
        referrer_url=(body.referrer_url or "")[:2048] or None,
        utm_source=(body.utm_source or "")[:255] or None,
        utm_medium=(body.utm_medium or "")[:255] or None,
        utm_campaign=(body.utm_campaign or "")[:255] or None,
        utm_term=(body.utm_term or "")[:255] or None,
        utm_content=(body.utm_content or "")[:255] or None,
        device_type=device,
        os_name=os_name,
        browser_name=browser,
        ip_hash=ip_hash,
    )
    create_visitor_log(
        db,
        session_id=body.session_id.strip()[:64],
        inflow_channel=inflow,
        referrer_url=(body.referrer_url or "")[:2048] or None,
        landing_page=(body.landing_page or "")[:1024] or None,
        utm_source=(body.utm_source or "")[:255] or None,
        utm_medium=(body.utm_medium or "")[:255] or None,
        utm_campaign=(body.utm_campaign or "")[:255] or None,
        utm_term=(body.utm_term or "")[:255] or None,
        utm_content=(body.utm_content or "")[:255] or None,
        ip_hash=ip_hash,
        user_agent=(ua or "")[:1024] or None,
        device_type=device,
        os_name=os_name,
        browser_name=browser,
    )

    return {
        "ok": True,
        "session_id": body.session_id,
        "inflow_channel": inflow,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/stay-time", status_code=204)
async def update_stay_time(
    request: Request,
    body: StayTimeBody = Body(...),
    db: Session = Depends(get_db),
):
    updated = add_session_stay_duration(
        db,
        session_id=body.session_id.strip()[:64],
        duration_seconds=int(body.stay_duration),
    )
    if not updated:
        upsert_visitor_session(
            db,
            session_id=body.session_id.strip()[:64],
            inflow_channel="direct",
            landing_page=None,
            referrer_url=None,
            utm_source=None,
            utm_medium=None,
            utm_campaign=None,
            utm_term=None,
            utm_content=None,
            device_type="Unknown",
            os_name="Unknown",
            browser_name="Unknown",
            ip_hash=_hash_ip(request.client.host if request.client else None),
        )
        add_session_stay_duration(
            db,
            session_id=body.session_id.strip()[:64],
            duration_seconds=int(body.stay_duration),
        )
    return None
