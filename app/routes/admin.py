import math
import json
import os
import re
import time
import uuid
from pathlib import Path
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Query, Request
from pydantic import BaseModel, Field
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None

from app.core.auth_admin import (
    ADMIN_COOKIE_KEY,
    ADMIN_ACCESS_TOKEN_EXPIRE_MINUTES,
    authenticate_admin,
    create_admin_access_token,
    get_admin_payload_optional,
    require_admin_api,
)
from app.config import get_flairy_temp_dir, get_highlight_merge_mode, get_video_render_max_workers
from app.database import get_db
from app.routes.generate import _run_generate_task
from app.services.storage_service import get_user_storage_usage_bytes, invalidate_user_storage_cache
from app.utils.ffmpeg_accel import get_accel_type

router = APIRouter(tags=["admin"])
templates = Jinja2Templates(directory="templates")

_STATS_CACHE_TTL_SEC = 60
_stats_cache: dict[str, tuple[float, dict]] = {}

_TASK_PENDING_STATUSES = {"PENDING", "ANALYZING", "GENERATING", "COMPOSING"}


class NoticeCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    is_pinned: bool = False


class NoticeUpdateBody(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1)
    is_pinned: bool | None = None


class InquiryAnswerBody(BaseModel):
    answer_content: str = Field(min_length=1)


class UserStatusBody(BaseModel):
    is_active: bool


def _cache_get(key: str) -> dict | None:
    entry = _stats_cache.get(key)
    if not entry:
        return None
    ts, payload = entry
    if time.time() - ts > _STATS_CACHE_TTL_SEC:
        _stats_cache.pop(key, None)
        return None
    return payload


def _cache_set(key: str, payload: dict) -> dict:
    _stats_cache[key] = (time.time(), payload)
    return payload


def _parse_range(range_key: str) -> tuple[str, date | None, date]:
    today = datetime.now(timezone.utc).date()
    key = (range_key or "30d").strip().lower()
    if key == "7d":
        return key, today - timedelta(days=6), today
    if key == "all":
        return key, None, today
    return "30d", today - timedelta(days=29), today


def _resolve_start_date(db: Session, start_date: date | None) -> date:
    if start_date is not None:
        return start_date
    row = db.execute(text(
        "SELECT LEAST("
        "COALESCE((SELECT MIN(created_at)::date FROM users), CURRENT_DATE), "
        "COALESCE((SELECT MIN(created_at)::date FROM video_tasks), CURRENT_DATE)"
        ") AS min_date"
    )).mappings().first()
    return (row or {}).get("min_date") or datetime.now(timezone.utc).date()


def _admin_exclude_condition(alias: str = "vt") -> str:
    return (
        f"({alias}.user_id IS NULL OR {alias}.user_id NOT IN "
        "(SELECT id FROM admin_users))"
    )


def _serialize_task_row(row) -> dict:
    status = (row.get("status") or "").upper()
    return {
        "task_id": str(row["task_id"]),
        "project_id": str(row["project_id"]) if row.get("project_id") else None,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        "task_type": row.get("task_type") or "",
        "status": status,
        "current_msg": row.get("current_msg") or "",
        "guest_token": row.get("guest_token") or "",
        "user_email": row.get("user_email"),
        "error_log": row.get("error_log") or "",
    }


def _serialize_notice_row(row) -> dict:
    return {
        "id": str(row["id"]),
        "title": row.get("title") or "",
        "content": row.get("content") or "",
        "is_pinned": bool(row.get("is_pinned")),
        "view_count": int(row.get("view_count") or 0),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


def _serialize_inquiry_row(row) -> dict:
    return {
        "id": str(row["id"]),
        "user_id": str(row["user_id"]) if row.get("user_id") else None,
        "guest_token": row.get("guest_token") or "",
        "title": row.get("title") or "",
        "content": row.get("content") or "",
        "is_secret": bool(row.get("is_secret")),
        "answer_content": row.get("answer_content") or "",
        "answered_at": row["answered_at"].isoformat() if row.get("answered_at") else None,
        "status": (row.get("status") or "PENDING").upper(),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        "user_email": row.get("user_email"),
    }


def _safe_dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        if not path.exists() or not path.is_dir():
            return 0
        for root, _dirs, files in os.walk(path):
            for name in files:
                fp = Path(root) / name
                try:
                    total += fp.stat().st_size
                except OSError:
                    continue
    except OSError:
        return 0
    return total


def _storage_usage_by_user_ids(user_ids: list[str], storage_root: Path) -> tuple[dict[str, int], int]:
    raw_root = storage_root / "raw"
    usage_map: dict[str, int] = {}
    total = 0
    for user_id in user_ids:
        size = _safe_dir_size_bytes(raw_root / user_id)
        usage_map[user_id] = size
        total += size
    return usage_map, total


def _serialize_user_row(row, storage_usage_bytes: int) -> dict:
    return {
        "id": str(row["id"]),
        "email": row.get("email") or "",
        "provider": row.get("provider") or "local",
        "is_active": bool(row.get("is_active", True)),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "last_login_at": row["last_login_at"].isoformat() if row.get("last_login_at") else None,
        "project_count": int(row.get("project_count") or 0),
        "storage_usage_bytes": int(storage_usage_bytes or 0),
    }


def _admin_page_context(request: Request, admin_payload: dict) -> dict:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=ADMIN_ACCESS_TOKEN_EXPIRE_MINUTES)
    exp_ts = admin_payload.get("exp")
    if isinstance(exp_ts, (int, float)):
        exp = datetime.fromtimestamp(exp_ts, tz=timezone.utc)
    return {
        "request": request,
        "admin_role": admin_payload.get("role", "super_admin"),
        "server_now": now.isoformat(),
        "admin_session_expires_at": exp.isoformat(),
    }


def _log_admin_action(
    db: Session,
    *,
    admin_payload: dict,
    request: Request | None,
    action_type: str,
    target_id: str,
    details: dict | None = None,
) -> None:
    admin_id = str(admin_payload.get("sub")) if admin_payload.get("sub") else None
    if admin_id:
        exists = db.execute(
            text("SELECT 1 FROM admin_users WHERE id::text = :admin_id"),
            {"admin_id": admin_id},
        ).first()
        if not exists:
            admin_id = None
    ip_address = request.client.host if request and request.client else None
    user_agent = request.headers.get("user-agent") if request else None
    db.execute(text("""
        INSERT INTO admin_action_logs (id, admin_id, action_type, target_id, details, ip_address, user_agent)
        VALUES (:id, :admin_id, :action_type, :target_id, CAST(:details AS jsonb), :ip_address, :user_agent)
    """), {
        "id": str(uuid.uuid4()),
        "admin_id": admin_id,
        "action_type": action_type,
        "target_id": target_id,
        "details": json.dumps(details or {}, ensure_ascii=False),
        "ip_address": ip_address,
        "user_agent": (user_agent[:512] if user_agent else None),
    })


def _serialize_audit_log_row(row) -> dict:
    details = row.get("details")
    if details is None:
        details_obj: dict | list | str | None = {}
    elif isinstance(details, dict):
        details_obj = details
    elif isinstance(details, str):
        try:
            details_obj = json.loads(details)
        except json.JSONDecodeError:
            details_obj = {}
    else:
        details_obj = details
    return {
        "id": str(row["id"]),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "action_type": row.get("action_type") or "",
        "target_id": row.get("target_id") or "",
        "details": details_obj,
        "ip_address": row.get("ip_address"),
        "user_agent": row.get("user_agent"),
        "admin_id": str(row["admin_id"]) if row.get("admin_id") else None,
        "admin_username": row.get("admin_username"),
    }


_TOTAL_RE = re.compile(r"영상 생성 파이프라인 완료 \(총 ([0-9.]+)s\)")
_TIMELINE_RE = re.compile(r"타임라인 검증: merged=([0-9.]+)s")


def _extract_latest_render_speed(logs: str | None) -> tuple[float, float] | None:
    if not logs:
        return None
    total_matches = list(_TOTAL_RE.finditer(logs))
    if not total_matches:
        return None
    total = float(total_matches[-1].group(1))
    prefix = logs[: total_matches[-1].end()]
    timeline_matches = list(_TIMELINE_RE.finditer(prefix))
    if not timeline_matches:
        return None
    merged = float(timeline_matches[-1].group(1))
    if total <= 0:
        return None
    return merged, total


@router.get("/admin/stats")
async def admin_stats_page(
    request: Request,
    admin_payload: dict = Depends(require_admin_api),
):
    if isinstance(admin_payload, RedirectResponse):
        return admin_payload
    return templates.TemplateResponse("admin/stats.html", _admin_page_context(request, admin_payload))


@router.get("/admin/tasks")
async def admin_tasks_page(
    request: Request,
    admin_payload: dict = Depends(require_admin_api),
):
    if isinstance(admin_payload, RedirectResponse):
        return admin_payload
    return templates.TemplateResponse("admin/tasks.html", _admin_page_context(request, admin_payload))


@router.get("/admin/board")
async def admin_board_page(
    request: Request,
    admin_payload: dict = Depends(require_admin_api),
):
    if isinstance(admin_payload, RedirectResponse):
        return admin_payload
    return templates.TemplateResponse("admin/board.html", _admin_page_context(request, admin_payload))


@router.get("/admin/users")
async def admin_users_page(
    request: Request,
    admin_payload: dict = Depends(require_admin_api),
):
    if isinstance(admin_payload, RedirectResponse):
        return admin_payload
    return templates.TemplateResponse("admin/users.html", _admin_page_context(request, admin_payload))


@router.get("/admin/audit")
async def admin_audit_page(
    request: Request,
    admin_payload: dict = Depends(require_admin_api),
):
    if isinstance(admin_payload, RedirectResponse):
        return admin_payload
    return templates.TemplateResponse("admin/audit.html", _admin_page_context(request, admin_payload))


@router.get("/admin/logout")
async def admin_logout():
    r = RedirectResponse(url="/admin/login", status_code=302)
    r.delete_cookie(ADMIN_COOKIE_KEY, path="/")
    return r


@router.get("/admin")
async def admin_root(request: Request):
    payload = get_admin_payload_optional(request)
    if payload:
        return RedirectResponse(url="/admin/stats", status_code=302)
    return RedirectResponse(url="/admin/login", status_code=302)


@router.get("/admin/login")
async def admin_login_page(request: Request):
    payload = get_admin_payload_optional(request)
    if payload:
        return RedirectResponse(url="/admin/stats", status_code=302)
    return templates.TemplateResponse(
        "admin/login.html",
        {"request": request, "error": ""},
    )


@router.post("/admin/login")
async def admin_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    admin = authenticate_admin(username, password)
    if not admin:
        return templates.TemplateResponse(
            "admin/login.html",
            {"request": request, "error": "아이디 또는 비밀번호가 올바르지 않습니다."},
            status_code=401,
        )

    token = create_admin_access_token(admin["id"], admin.get("role", "super_admin"))
    response = RedirectResponse(url="/admin/stats", status_code=302)
    response.set_cookie(
        key=ADMIN_COOKIE_KEY,
        value=token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=86400,
        path="/",
    )
    return response


@router.get("/api/notices")
def public_notices(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT id, title, content, is_pinned, view_count, created_at, updated_at
        FROM board_notices
        ORDER BY is_pinned DESC, created_at DESC
        LIMIT 3
    """)).mappings().all()
    return {"items": [_serialize_notice_row(r) for r in rows]}


@router.post("/api/admin/notices")
def admin_create_notice(
    body: NoticeCreateBody,
    admin_payload: dict = Depends(require_admin_api),
    db: Session = Depends(get_db),
):
    row = db.execute(text("""
        INSERT INTO board_notices (id, title, content, is_pinned)
        VALUES (:id, :title, :content, :is_pinned)
        RETURNING id, title, content, is_pinned, view_count, created_at, updated_at
    """), {
        "id": str(uuid.uuid4()),
        "title": body.title.strip(),
        "content": body.content.strip(),
        "is_pinned": body.is_pinned,
    }).mappings().first()
    db.commit()
    return _serialize_notice_row(row)


@router.get("/api/admin/notices")
def admin_list_notices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin_payload: dict = Depends(require_admin_api),
    db: Session = Depends(get_db),
):
    total_row = db.execute(text("SELECT COUNT(*)::int AS cnt FROM board_notices")).mappings().first() or {"cnt": 0}
    total = int(total_row["cnt"])
    offset = (page - 1) * page_size
    rows = db.execute(text("""
        SELECT id, title, content, is_pinned, view_count, created_at, updated_at
        FROM board_notices
        ORDER BY is_pinned DESC, created_at DESC
        LIMIT :limit OFFSET :offset
    """), {"limit": page_size, "offset": offset}).mappings().all()
    return {
        "items": [_serialize_notice_row(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, math.ceil(total / page_size) if page_size else 1),
    }


@router.put("/api/admin/notices/{notice_id}")
def admin_update_notice(
    notice_id: str,
    body: NoticeUpdateBody,
    admin_payload: dict = Depends(require_admin_api),
    db: Session = Depends(get_db),
):
    existing = db.execute(text("""
        SELECT id FROM board_notices WHERE id::text = :notice_id
    """), {"notice_id": notice_id}).mappings().first()
    if not existing:
        raise HTTPException(status_code=404, detail="Notice not found")

    current = db.execute(text("""
        SELECT title, content, is_pinned FROM board_notices WHERE id::text = :notice_id
    """), {"notice_id": notice_id}).mappings().first()

    title = body.title.strip() if body.title is not None else current["title"]
    content = body.content.strip() if body.content is not None else current["content"]
    is_pinned = body.is_pinned if body.is_pinned is not None else bool(current["is_pinned"])

    row = db.execute(text("""
        UPDATE board_notices
        SET title = :title,
            content = :content,
            is_pinned = :is_pinned,
            updated_at = now()
        WHERE id::text = :notice_id
        RETURNING id, title, content, is_pinned, view_count, created_at, updated_at
    """), {
        "notice_id": notice_id,
        "title": title,
        "content": content,
        "is_pinned": is_pinned,
    }).mappings().first()
    db.commit()
    return _serialize_notice_row(row)


@router.delete("/api/admin/notices/{notice_id}")
def admin_delete_notice(
    notice_id: str,
    admin_payload: dict = Depends(require_admin_api),
    db: Session = Depends(get_db),
):
    result = db.execute(text("""
        DELETE FROM board_notices WHERE id::text = :notice_id
    """), {"notice_id": notice_id})
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Notice not found")
    return {"ok": True, "id": notice_id}


@router.get("/api/admin/inquiries")
def admin_list_inquiries(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin_payload: dict = Depends(require_admin_api),
    db: Session = Depends(get_db),
):
    total_row = db.execute(text("SELECT COUNT(*)::int AS cnt FROM board_inquiries")).mappings().first() or {"cnt": 0}
    total = int(total_row["cnt"])
    offset = (page - 1) * page_size
    rows = db.execute(text("""
        SELECT
            i.id, i.user_id, i.guest_token, i.title, i.content, i.is_secret,
            i.answer_content, i.answered_at, i.status, i.created_at, i.updated_at,
            u.email AS user_email
        FROM board_inquiries i
        LEFT JOIN users u ON u.id = i.user_id
        ORDER BY
            CASE WHEN UPPER(i.status) = 'PENDING' THEN 0 ELSE 1 END,
            i.created_at DESC
        LIMIT :limit OFFSET :offset
    """), {"limit": page_size, "offset": offset}).mappings().all()
    return {
        "items": [_serialize_inquiry_row(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, math.ceil(total / page_size) if page_size else 1),
    }


@router.post("/api/admin/inquiries/{inquiry_id}/answer")
def admin_answer_inquiry(
    inquiry_id: str,
    body: InquiryAnswerBody,
    admin_payload: dict = Depends(require_admin_api),
    db: Session = Depends(get_db),
):
    row = db.execute(text("""
        UPDATE board_inquiries
        SET answer_content = :answer_content,
            answered_at = now(),
            status = 'ANSWERED',
            updated_at = now()
        WHERE id::text = :inquiry_id
        RETURNING id, user_id, guest_token, title, content, is_secret,
                  answer_content, answered_at, status, created_at, updated_at
    """), {
        "inquiry_id": inquiry_id,
        "answer_content": body.answer_content.strip(),
    }).mappings().first()
    if not row:
        db.rollback()
        raise HTTPException(status_code=404, detail="Inquiry not found")
    db.commit()
    return _serialize_inquiry_row(row)


@router.get("/api/admin/users")
def admin_list_users(
    search: str = Query("", max_length=255),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin_payload: dict = Depends(require_admin_api),
    db: Session = Depends(get_db),
):
    q = (search or "").strip()
    where_clause = "u.id NOT IN (SELECT id FROM admin_users)"
    params: dict[str, object] = {}
    if q:
        where_clause += " AND (u.email ILIKE :q OR COALESCE(u.provider, '') ILIKE :q)"
        params["q"] = f"%{q}%"

    total_row = db.execute(text(f"""
        SELECT COUNT(*)::int AS cnt
        FROM users u
        WHERE {where_clause}
    """), params).mappings().first() or {"cnt": 0}
    total = int(total_row["cnt"])
    offset = (page - 1) * page_size

    rows = db.execute(text(f"""
        SELECT
            u.id,
            u.email,
            u.provider,
            u.is_active,
            COALESCE(u.storage_usage_bytes, 0)::bigint AS storage_usage_bytes,
            u.created_at,
            u.last_login_at,
            COUNT(p.id)::int AS project_count
        FROM users u
        LEFT JOIN projects p ON p.user_id = u.id
        WHERE {where_clause}
        GROUP BY u.id, u.email, u.provider, u.is_active, u.storage_usage_bytes, u.created_at, u.last_login_at
        ORDER BY u.created_at DESC
        LIMIT :limit OFFSET :offset
    """), {**params, "limit": page_size, "offset": offset}).mappings().all()

    usage_map: dict[str, int] = {}
    for row in rows:
        user_id = str(row["id"])
        cached = get_user_storage_usage_bytes(
            db,
            user_id,
            force_refresh=False,
            update_db=False,
        )
        usage_map[user_id] = int(cached if cached is not None else (row.get("storage_usage_bytes") or 0))
    db.commit()

    summary_row = db.execute(text("""
        SELECT
            COUNT(*)::int AS total_users,
            COUNT(*) FILTER (WHERE created_at::date = CURRENT_DATE)::int AS today_new_users,
            COALESCE(SUM(storage_usage_bytes), 0)::bigint AS total_storage_bytes
        FROM users
        WHERE id NOT IN (SELECT id FROM admin_users)
    """)).mappings().first() or {}

    items = [
        _serialize_user_row(r, usage_map.get(str(r["id"]), 0))
        for r in rows
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, math.ceil(total / page_size) if page_size else 1),
        "summary": {
            "total_users": int(summary_row.get("total_users") or 0),
            "today_new_users": int(summary_row.get("today_new_users") or 0),
            "total_storage_bytes": int(summary_row.get("total_storage_bytes") or 0),
        },
    }


@router.post("/api/admin/users/{user_id}/storage/refresh")
def admin_refresh_user_storage(
    user_id: str,
    admin_payload: dict = Depends(require_admin_api),
    db: Session = Depends(get_db),
):
    invalidate_user_storage_cache(user_id)
    usage = get_user_storage_usage_bytes(db, user_id, force_refresh=True, update_db=True)
    row = db.execute(text("""
        SELECT id, email, provider, is_active, created_at, last_login_at,
               COALESCE((SELECT COUNT(*) FROM projects p WHERE p.user_id = u.id), 0)::int AS project_count
        FROM users u
        WHERE id::text = :user_id
    """), {"user_id": user_id}).mappings().first()
    if not row:
        db.rollback()
        raise HTTPException(status_code=404, detail="User not found")
    db.commit()
    return {"ok": True, "item": _serialize_user_row(row, usage)}


@router.patch("/api/admin/users/{user_id}/status")
def admin_update_user_status(
    request: Request,
    user_id: str,
    body: UserStatusBody,
    admin_payload: dict = Depends(require_admin_api),
    db: Session = Depends(get_db),
):
    before = db.execute(text("""
        SELECT is_active FROM users WHERE id::text = :user_id
    """), {"user_id": user_id}).mappings().first()
    if not before:
        raise HTTPException(status_code=404, detail="User not found")
    result = db.execute(text("""
        UPDATE users
        SET is_active = :is_active
        WHERE id::text = :user_id
        RETURNING id, email, provider, is_active, created_at, last_login_at
    """), {"user_id": user_id, "is_active": body.is_active}).mappings().first()
    if not result:
        db.rollback()
        raise HTTPException(status_code=404, detail="User not found")
    usage = get_user_storage_usage_bytes(db, user_id, force_refresh=False, update_db=False)
    _log_admin_action(
        db,
        admin_payload=admin_payload,
        request=request,
        action_type="UNBAN_USER" if body.is_active else "BAN_USER",
        target_id=user_id,
        details={"before_is_active": bool(before.get("is_active")), "after_is_active": bool(body.is_active)},
    )
    db.commit()
    item = _serialize_user_row({**result, "project_count": 0}, usage)
    return {"ok": True, "item": item}


@router.get("/api/admin/system/health")
def admin_system_health(
    admin_payload: dict = Depends(require_admin_api),
    db: Session = Depends(get_db),
):
    if psutil is None:
        raise HTTPException(status_code=500, detail="psutil is not available")
    storage_root = Path(__file__).resolve().parents[2] / "storage"
    storage_raw = storage_root / "raw"
    storage_total_bytes = _safe_dir_size_bytes(storage_raw)
    configured_temp = get_flairy_temp_dir()
    if configured_temp is None:
        temp_path = storage_root / "temp"
    else:
        temp_path = configured_temp

    disk = psutil.disk_usage(str(storage_root))
    temp_disk = psutil.disk_usage(str(temp_path))
    vm = psutil.virtual_memory()
    cpu_percent = psutil.cpu_percent(interval=0.1)

    return {
        "cpu_percent": round(float(cpu_percent), 2),
        "memory_percent": round(float(vm.percent), 2),
        "memory_total_bytes": int(vm.total),
        "memory_available_bytes": int(vm.available),
        "disk_total_bytes": int(disk.total),
        "disk_used_bytes": int(disk.used),
        "disk_free_bytes": int(disk.free),
        "disk_percent": round(float(disk.percent), 2),
        "temp_path": str(temp_path),
        "temp_total_bytes": int(temp_disk.total),
        "temp_used_bytes": int(temp_disk.used),
        "temp_free_bytes": int(temp_disk.free),
        "temp_percent": round(float(temp_disk.percent), 2),
        "storage_total_bytes": int(storage_total_bytes),
        "accel_mode": get_accel_type().upper(),
        "merge_mode": get_highlight_merge_mode().upper(),
        "render_workers": int(get_video_render_max_workers()),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/api/admin/stats/render-speed")
def admin_render_speed_stats(
    admin_payload: dict = Depends(require_admin_api),
    db: Session = Depends(get_db),
):
    rows = db.execute(text("""
        SELECT id, logs, created_at
        FROM projects
        WHERE status = 'COMPLETED' AND logs IS NOT NULL
        ORDER BY created_at DESC
        LIMIT 40
    """)).mappings().all()
    items: list[dict] = []
    for row in rows:
        parsed = _extract_latest_render_speed(row.get("logs"))
        if not parsed:
            continue
        merged, total = parsed
        items.append(
            {
                "project_id": str(row["id"]),
                "video_sec": round(merged, 2),
                "render_sec": round(total, 2),
                "speed_ratio": round(merged / total, 3),
                "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            }
        )
        if len(items) >= 10:
            break
    avg_ratio = round(sum(x["speed_ratio"] for x in items) / len(items), 3) if items else 0.0
    return {"items": items, "avg_speed_ratio": avg_ratio}


@router.get("/api/admin/tasks")
def admin_list_tasks(
    status: str = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin_payload: dict = Depends(require_admin_api),
    db: Session = Depends(get_db),
):
    sf = (status or "all").strip().lower()
    if sf not in ("all", "success", "fail", "pending"):
        raise HTTPException(status_code=400, detail="Invalid status filter")

    where_clause = "1=1"
    if sf == "success":
        where_clause = "UPPER(vt.status) = 'COMPLETED'"
    elif sf == "fail":
        where_clause = "UPPER(vt.status) = 'FAILED'"
    elif sf == "pending":
        where_clause = "UPPER(vt.status) IN ('PENDING','ANALYZING','GENERATING','COMPOSING')"

    total_row = db.execute(text(f"""
        SELECT COUNT(*)::int AS cnt
        FROM video_tasks vt
        WHERE {where_clause}
    """)).mappings().first() or {"cnt": 0}
    total = int(total_row["cnt"])
    offset = (page - 1) * page_size

    rows = db.execute(text(f"""
        SELECT
            vt.task_id,
            vt.project_id,
            vt.created_at,
            vt.updated_at,
            vt.task_type,
            vt.status,
            vt.current_msg,
            vt.guest_token,
            COALESCE(vt.error_log, '') AS error_log,
            u.email AS user_email
        FROM video_tasks vt
        LEFT JOIN users u ON u.id = vt.user_id
        WHERE {where_clause}
        ORDER BY vt.created_at DESC
        LIMIT :limit OFFSET :offset
    """), {"limit": page_size, "offset": offset}).mappings().all()

    return {
        "items": [_serialize_task_row(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, math.ceil(total / page_size) if page_size else 1),
    }


@router.post("/api/admin/tasks/{task_id}/retry")
def admin_retry_task(
    request: Request,
    task_id: str,
    background_tasks: BackgroundTasks,
    admin_payload: dict = Depends(require_admin_api),
    db: Session = Depends(get_db),
):
    row = db.execute(text("""
        SELECT task_id, project_id, status
        FROM video_tasks
        WHERE task_id::text = :task_id
    """), {"task_id": task_id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    if not row["project_id"]:
        raise HTTPException(status_code=400, detail="Task has no project")
    if (row["status"] or "").upper() != "FAILED":
        raise HTTPException(status_code=409, detail="Only FAILED task can be retried")

    db.execute(text("""
        UPDATE video_tasks
        SET status = 'PENDING',
            current_msg = '관리자가 작업을 재시도했습니다.',
            updated_at = now()
        WHERE task_id::text = :task_id
    """), {"task_id": task_id})
    db.execute(text("""
        UPDATE projects
        SET status = 'PENDING'
        WHERE id = :project_id
    """), {"project_id": row["project_id"]})
    _log_admin_action(
        db,
        admin_payload=admin_payload,
        request=request,
        action_type="RETRY_TASK",
        target_id=task_id,
        details={
            "project_id": str(row["project_id"]),
            "before_status": (row.get("status") or "").upper(),
            "after_status": "PENDING",
        },
    )
    db.commit()

    background_tasks.add_task(_run_generate_task, str(row["project_id"]))
    return {"ok": True, "task_id": task_id, "project_id": str(row["project_id"])}


@router.delete("/api/admin/tasks/{task_id}")
def admin_delete_task(
    request: Request,
    task_id: str,
    admin_payload: dict = Depends(require_admin_api),
    db: Session = Depends(get_db),
):
    before = db.execute(text("""
        SELECT project_id, status FROM video_tasks WHERE task_id::text = :task_id
    """), {"task_id": task_id}).mappings().first()
    if not before:
        raise HTTPException(status_code=404, detail="Task not found")
    result = db.execute(text("""
        DELETE FROM video_tasks WHERE task_id::text = :task_id
    """), {"task_id": task_id})
    if result.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=404, detail="Task not found")
    _log_admin_action(
        db,
        admin_payload=admin_payload,
        request=request,
        action_type="DELETE_TASK",
        target_id=task_id,
        details={
            "project_id": str(before["project_id"]) if before.get("project_id") else None,
            "before_status": (before.get("status") or "").upper(),
        },
    )
    db.commit()
    return {"ok": True, "task_id": task_id}


@router.get("/api/admin/audit-logs")
def admin_list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action_type: str | None = Query(None),
    admin_id: str | None = Query(None),
    admin_name: str | None = Query(None),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    admin_payload: dict = Depends(require_admin_api),
    db: Session = Depends(get_db),
):
    where_parts = ["1=1"]
    params: dict = {}
    if action_type and str(action_type).strip():
        where_parts.append("l.action_type ILIKE :action_pat")
        params["action_pat"] = f"%{str(action_type).strip()}%"
    if admin_id and str(admin_id).strip():
        where_parts.append("l.admin_id::text = :audit_admin_id")
        params["audit_admin_id"] = str(admin_id).strip()
    if admin_name and str(admin_name).strip():
        where_parts.append("au.username ILIKE :audit_admin_name")
        params["audit_admin_name"] = f"%{str(admin_name).strip()}%"
    if start_date and str(start_date).strip():
        where_parts.append("l.created_at::date >= CAST(:audit_start AS date)")
        params["audit_start"] = str(start_date).strip()
    if end_date and str(end_date).strip():
        where_parts.append("l.created_at::date <= CAST(:audit_end AS date)")
        params["audit_end"] = str(end_date).strip()

    where_sql = " AND ".join(where_parts)
    from_clause = """
        FROM admin_action_logs l
        LEFT JOIN admin_users au ON au.id = l.admin_id
    """

    total_row = db.execute(text(f"""
        SELECT COUNT(*)::int AS cnt
        {from_clause}
        WHERE {where_sql}
    """), params).mappings().first() or {"cnt": 0}
    total = int(total_row["cnt"])
    offset = (page - 1) * page_size
    params_with_page = {**params, "limit": page_size, "offset": offset}

    rows = db.execute(text(f"""
        SELECT
            l.id,
            l.created_at,
            l.action_type,
            l.target_id,
            l.details,
            l.ip_address,
            l.user_agent,
            l.admin_id,
            au.username AS admin_username
        {from_clause}
        WHERE {where_sql}
        ORDER BY l.created_at DESC
        LIMIT :limit OFFSET :offset
    """), params_with_page).mappings().all()

    return {
        "items": [_serialize_audit_log_row(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, math.ceil(total / page_size) if page_size else 1),
    }


@router.get("/api/admin/stats/summary")
def admin_stats_summary(
    range_key: str = Query("30d", alias="range"),
    admin_payload: dict = Depends(require_admin_api),
    db: Session = Depends(get_db),
):
    rk, start_date, _end_date = _parse_range(range_key)
    cache_key = f"summary:{rk}"
    if cached := _cache_get(cache_key):
        return cached
    where_users = "u.id NOT IN (SELECT id FROM admin_users)"
    where_tasks = _admin_exclude_condition("vt")
    params = {}
    if start_date is not None:
        where_users += " AND u.created_at::date >= :start_date"
        where_tasks += " AND vt.created_at::date >= :start_date"
        params["start_date"] = start_date
    row = db.execute(text(f"""
        WITH users_scope AS (
            SELECT COUNT(*)::int AS total_users,
                   COUNT(*) FILTER (WHERE u.created_at::date = CURRENT_DATE)::int AS today_users
            FROM users u
            WHERE {where_users}
        ),
        tasks_scope AS (
            SELECT
              COUNT(*)::int AS total_tasks,
              COUNT(*) FILTER (WHERE vt.created_at::date = CURRENT_DATE)::int AS today_tasks,
              COUNT(*) FILTER (WHERE UPPER(vt.status) = 'COMPLETED')::int AS success_tasks
            FROM video_tasks vt
            WHERE {where_tasks}
        ),
        creators_scope AS (
            SELECT
              COUNT(DISTINCT CASE
                  WHEN vt.user_id IS NOT NULL THEN ('u:' || vt.user_id::text)
                  WHEN NULLIF(vt.guest_token, '') IS NOT NULL THEN ('g:' || vt.guest_token)
                  ELSE NULL
              END)::int AS unique_creators
            FROM video_tasks vt
            WHERE {where_tasks}
        )
        SELECT
          u.total_users,
          u.today_users,
          t.today_tasks,
          t.total_tasks,
          t.success_tasks,
          c.unique_creators
        FROM users_scope u, tasks_scope t, creators_scope c
    """), params).mappings().first() or {}
    total_tasks = int(row.get("total_tasks") or 0)
    success_tasks = int(row.get("success_tasks") or 0)
    unique_creators = int(row.get("unique_creators") or 0)
    success_rate = (success_tasks / total_tasks * 100.0) if total_tasks else 0.0
    tasks_per_creator = (total_tasks / unique_creators) if unique_creators else 0.0
    payload = {
        "range": rk,
        "total_users": int(row.get("total_users") or 0),
        "today_users": int(row.get("today_users") or 0),
        "today_tasks": int(row.get("today_tasks") or 0),
        "success_rate": round(success_rate, 2),
        "conversion_rate": round(success_rate, 2),
        "tasks_per_creator": round(tasks_per_creator, 2),
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    return _cache_set(cache_key, payload)


@router.get("/api/admin/stats/daily-growth")
def admin_stats_daily_growth(
    range_key: str = Query("30d", alias="range"),
    admin_payload: dict = Depends(require_admin_api),
    db: Session = Depends(get_db),
):
    rk, start_date, end_date = _parse_range(range_key)
    start_date = _resolve_start_date(db, start_date)
    cache_key = f"daily-growth:{rk}:{start_date}:{end_date}"
    if cached := _cache_get(cache_key):
        return cached
    rows = db.execute(text(f"""
        WITH days AS (
            SELECT generate_series(CAST(:start_date AS date), CAST(:end_date AS date), interval '1 day')::date AS d
        ),
        users_daily AS (
            SELECT date_trunc('day', u.created_at)::date AS d, COUNT(*)::int AS new_users
            FROM users u
            WHERE u.id NOT IN (SELECT id FROM admin_users)
              AND u.created_at::date BETWEEN :start_date AND :end_date
            GROUP BY 1
        ),
        dau_daily AS (
            SELECT
              date_trunc('day', vt.created_at)::date AS d,
              COUNT(DISTINCT CASE
                WHEN vt.user_id IS NOT NULL THEN ('u:' || vt.user_id::text)
                WHEN NULLIF(vt.guest_token, '') IS NOT NULL THEN ('g:' || vt.guest_token)
                ELSE NULL
              END)::int AS dau
            FROM video_tasks vt
            WHERE { _admin_exclude_condition('vt') }
              AND vt.created_at::date BETWEEN :start_date AND :end_date
            GROUP BY 1
        )
        SELECT
            days.d AS date,
            COALESCE(users_daily.new_users, 0)::int AS new_users,
            COALESCE(dau_daily.dau, 0)::int AS dau
        FROM days
        LEFT JOIN users_daily ON users_daily.d = days.d
        LEFT JOIN dau_daily ON dau_daily.d = days.d
        ORDER BY days.d
    """), {"start_date": start_date, "end_date": end_date}).mappings().all()
    payload = {
        "range": rk,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "items": [
            {
                "date": str(r["date"]),
                "new_users": int(r["new_users"]),
                "dau": int(r["dau"]),
            }
            for r in rows
        ],
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    return _cache_set(cache_key, payload)


@router.get("/api/admin/stats/task-analysis")
def admin_stats_task_analysis(
    range_key: str = Query("30d", alias="range"),
    admin_payload: dict = Depends(require_admin_api),
    db: Session = Depends(get_db),
):
    rk, start_date, _end_date = _parse_range(range_key)
    cache_key = f"task-analysis:{rk}:{start_date}"
    if cached := _cache_get(cache_key):
        return cached
    where_clause = _admin_exclude_condition("vt")
    params = {}
    if start_date is not None:
        where_clause += " AND vt.created_at::date >= :start_date"
        params["start_date"] = start_date
    mode_rows = db.execute(text(f"""
        SELECT
          CASE
            WHEN p.mode::text = 'ai' THEN 'AI'
            WHEN p.mode::text = 'rule_based' THEN 'Rule'
            WHEN UPPER(vt.task_type) LIKE '%AI%' THEN 'AI'
            ELSE 'Rule'
          END AS mode_name,
          COUNT(*)::int AS cnt
        FROM video_tasks vt
        LEFT JOIN projects p ON p.id = vt.project_id
        WHERE {where_clause}
        GROUP BY 1
    """), params).mappings().all()
    status_rows = db.execute(text(f"""
        SELECT
          CASE
            WHEN UPPER(vt.status) = 'COMPLETED' THEN 'success'
            WHEN UPPER(vt.status) = 'FAILED' THEN 'fail'
            ELSE 'other'
          END AS status_name,
          COUNT(*)::int AS cnt
        FROM video_tasks vt
        WHERE {where_clause}
        GROUP BY 1
    """), params).mappings().all()
    weekday_rows = db.execute(text(f"""
        SELECT
          EXTRACT(DOW FROM vt.created_at)::int AS dow,
          COUNT(*)::int AS cnt
        FROM video_tasks vt
        WHERE {where_clause}
        GROUP BY 1
        ORDER BY 1
    """), params).mappings().all()
    mode_map = {"AI": 0, "Rule": 0}
    for r in mode_rows:
        k = str(r["mode_name"])
        if k in mode_map:
            mode_map[k] = int(r["cnt"])
    status_map = {"success": 0, "fail": 0, "other": 0}
    for r in status_rows:
        status_map[str(r["status_name"])] = int(r["cnt"])
    dow_map = {i: 0 for i in range(7)}
    for r in weekday_rows:
        dow_map[int(r["dow"])] = int(r["cnt"])
    payload = {
        "range": rk,
        "mode_ratio": mode_map,
        "status_ratio": status_map,
        "weekday_distribution": [
            {"dow": i, "count": dow_map[i]} for i in range(7)
        ],
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    return _cache_set(cache_key, payload)

