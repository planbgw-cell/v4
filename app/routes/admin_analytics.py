from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth_admin import require_admin_api
from app.database import get_db

router = APIRouter(tags=["admin-analytics"])
templates = Jinja2Templates(directory="templates")
KST = timezone(timedelta(hours=9))


def _admin_page_context(request: Request, admin_payload: dict) -> dict:
    now = datetime.now(timezone.utc)
    exp = now
    exp_ts = admin_payload.get("exp")
    if isinstance(exp_ts, (int, float)):
        exp = datetime.fromtimestamp(exp_ts, tz=timezone.utc)
    return {
        "request": request,
        "admin_role": admin_payload.get("role", "super_admin"),
        "server_now": now.isoformat(),
        "admin_session_expires_at": exp.isoformat(),
    }


def _to_utc_range(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    kst_start = datetime.combine(start_date, time.min, tzinfo=KST)
    kst_end_next = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=KST)
    return kst_start.astimezone(timezone.utc), kst_end_next.astimezone(timezone.utc)


@router.get("/admin/analytics")
async def admin_analytics_page(
    request: Request,
    admin_payload: dict = Depends(require_admin_api),
):
    if isinstance(admin_payload, RedirectResponse):
        return admin_payload
    return templates.TemplateResponse("admin/analytics.html", _admin_page_context(request, admin_payload))


@router.get("/api/v1/admin/analytics/summary")
def admin_analytics_summary(
    start_date: date = Query(...),
    end_date: date = Query(...),
    admin_payload: dict = Depends(require_admin_api),
    db: Session = Depends(get_db),
):
    if isinstance(admin_payload, RedirectResponse):
        raise HTTPException(status_code=401, detail="Admin authentication required")
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be >= start_date")

    start_utc, end_utc = _to_utc_range(start_date, end_date)

    base_params = {"start": start_utc, "end": end_utc}
    kpi_row = db.execute(
        text(
            """
            SELECT
              COUNT(DISTINCT session_id)::int AS uv_count,
              COALESCE(AVG(total_stay_duration), 0)::float AS avg_stay_sec,
              COALESCE(AVG(CASE WHEN is_converted_video THEN 1 ELSE 0 END) * 100, 0)::float AS video_cvr,
              COALESCE(AVG(CASE WHEN is_converted_signup THEN 1 ELSE 0 END) * 100, 0)::float AS signup_cvr
            FROM visitor_sessions
            WHERE first_seen_at >= :start AND first_seen_at < :end
            """
        ),
        base_params,
    ).mappings().first() or {}

    daily_rows = db.execute(
        text(
            """
            WITH days AS (
              SELECT generate_series(CAST(:start AS date), CAST(:end - interval '1 second' AS date), interval '1 day')::date AS d
            ),
            visits AS (
              SELECT (first_seen_at AT TIME ZONE 'Asia/Seoul')::date AS d, COUNT(DISTINCT session_id)::int AS uv
              FROM visitor_sessions
              WHERE first_seen_at >= :start AND first_seen_at < :end
              GROUP BY 1
            ),
            signups AS (
              SELECT (first_seen_at AT TIME ZONE 'Asia/Seoul')::date AS d, COUNT(*)::int AS signup
              FROM visitor_sessions
              WHERE first_seen_at >= :start AND first_seen_at < :end
                AND is_converted_signup = TRUE
              GROUP BY 1
            )
            SELECT
              to_char(days.d, 'YYYY-MM-DD') AS date,
              COALESCE(visits.uv, 0) AS uv,
              COALESCE(signups.signup, 0) AS signup
            FROM days
            LEFT JOIN visits ON visits.d = days.d
            LEFT JOIN signups ON signups.d = days.d
            ORDER BY days.d
            """
        ),
        base_params,
    ).mappings().all()

    channel_rows = db.execute(
        text(
            """
            SELECT COALESCE(NULLIF(latest_inflow_channel, ''), 'direct') AS inflow_channel,
                   COUNT(*)::int AS cnt
            FROM visitor_sessions
            WHERE first_seen_at >= :start AND first_seen_at < :end
            GROUP BY 1
            ORDER BY cnt DESC
            """
        ),
        base_params,
    ).mappings().all()
    channel_total = sum(int(r["cnt"]) for r in channel_rows) or 1

    device_rows = db.execute(
        text(
            """
            SELECT COALESCE(NULLIF(device_type, ''), 'Unknown') AS device_type, COUNT(*)::int AS cnt
            FROM visitor_sessions
            WHERE first_seen_at >= :start AND first_seen_at < :end
            GROUP BY 1
            ORDER BY cnt DESC
            """
        ),
        base_params,
    ).mappings().all()
    device_total = sum(int(r["cnt"]) for r in device_rows) or 1

    recent_rows = db.execute(
        text(
            """
            SELECT
              vl.created_at,
              vl.inflow_channel,
              COALESCE(vl.device_type, 'Unknown') AS device_type,
              COALESCE(vl.browser_name, 'Unknown') AS browser_name,
              COALESCE(vs.total_stay_duration, 0) AS total_stay_duration,
              COALESCE(vs.is_converted_video, FALSE) AS is_converted_video
            FROM visitor_logs vl
            LEFT JOIN visitor_sessions vs ON vs.session_id = vl.session_id
            WHERE vl.created_at >= :start AND vl.created_at < :end
            ORDER BY vl.created_at DESC
            LIMIT 20
            """
        ),
        base_params,
    ).mappings().all()

    return {
        "range": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        "kpi": {
            "uv_count": int(kpi_row.get("uv_count") or 0),
            "avg_active_stay_sec": float(kpi_row.get("avg_stay_sec") or 0),
            "video_conversion_rate": round(float(kpi_row.get("video_cvr") or 0), 2),
            "signup_conversion_rate": round(float(kpi_row.get("signup_cvr") or 0), 2),
        },
        "daily": [
            {"date": r["date"], "uv": int(r["uv"]), "signup": int(r["signup"])}
            for r in daily_rows
        ],
        "channels": [
            {
                "inflow_channel": r["inflow_channel"],
                "count": int(r["cnt"]),
                "ratio": round((int(r["cnt"]) / channel_total) * 100, 2),
            }
            for r in channel_rows
        ],
        "devices": [
            {
                "device_type": r["device_type"],
                "count": int(r["cnt"]),
                "ratio": round((int(r["cnt"]) / device_total) * 100, 2),
            }
            for r in device_rows
        ],
        "recent_logs": [
            {
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                "inflow_channel": r.get("inflow_channel") or "direct",
                "device_type": r.get("device_type") or "Unknown",
                "browser_name": r.get("browser_name") or "Unknown",
                "stay_duration_sec": int(r.get("total_stay_duration") or 0),
                "is_converted_video": bool(r.get("is_converted_video")),
            }
            for r in recent_rows
        ],
    }
