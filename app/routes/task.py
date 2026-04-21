from datetime import datetime, timezone
from pathlib import Path
import re
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException

from app.crud import (
    get_project,
    get_video_task_active,
    get_video_task_any,
    update_video_task_notify,
)
from app.database import SessionLocal

router = APIRouter(prefix="/api", tags=["tasks"])

_ACTIVE_STATUSES = {"PENDING", "ANALYZING", "COMPOSING", "GENERATING"}
_STATUS_PROGRESS = {
    "PENDING": 10,
    "ANALYZING": 35,
    "COMPOSING": 65,
    "GENERATING": 85,
    "COMPLETED": 100,
    "FAILED": 100,
}
_PHONE_RE = re.compile(r"^\+?[0-9][0-9-]{7,14}[0-9]$")


def _best_cut_image_url(project) -> str | None:
    media = getattr(project, "media_files", None) or []
    project_id = str(getattr(project, "id", ""))
    best_score = -1.0
    best_file = ""
    for mf in media:
        if getattr(mf, "file_type", "") != "image":
            continue
        if not bool(getattr(mf, "is_selected", True)):
            continue
        ai = getattr(mf, "ai_analysis", None) or {}
        score = ai.get("score")
        if not isinstance(score, (int, float)):
            continue
        file_path = getattr(mf, "file_path", "") or ""
        filename = Path(file_path).name
        if not filename:
            continue
        if float(score) > best_score:
            best_score = float(score)
            best_file = filename
    if not best_file or not project_id:
        return None
    return "/raw/" + quote(project_id) + "/" + quote(best_file)


def _progress_percent(project_status: str, project) -> int:
    if project_status == "ANALYZING" and project is not None:
        total = int(getattr(project, "ai_total_count", 0) or 0)
        processed = int(getattr(project, "ai_processed_count", 0) or 0)
        if total > 0:
            pct = 10 + int((min(processed, total) / total) * 45)
            return max(10, min(55, pct))
    return _STATUS_PROGRESS.get(project_status, 10)


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    try:
        uid = UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid task_id")

    db = SessionLocal()
    try:
        task = get_video_task_active(db, uid)
        if not task:
            expired_or_missing = get_video_task_any(db, uid)
            if expired_or_missing:
                raise HTTPException(status_code=410, detail="만료된 작업입니다")
            raise HTTPException(status_code=404, detail="Task not found")

        project = get_project(db, task.project_id) if task.project_id else None
        project_type = (getattr(project, "project_type", None) or "video").lower()
        project_status = (
            (getattr(project, "status", None) or task.status or "PENDING").strip().upper()
        )
        if project_status != (task.status or "").upper():
            task.status = project_status
            db.commit()

        current_msg = task.current_msg or "작업 준비 중..."
        if project_status == "COMPLETED":
            current_msg = "생성이 완료되었습니다."
        elif project_status == "FAILED":
            current_msg = "작업 중 오류가 발생했습니다."

        expires_at = task.expires_at
        now = datetime.now(timezone.utc)
        if expires_at is not None and getattr(expires_at, "tzinfo", None) is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at is not None and expires_at <= now:
            raise HTTPException(status_code=410, detail="만료된 작업입니다")

        project_id_str = str(task.project_id) if task.project_id else None
        result_url = None
        if project_status == "COMPLETED" and project_id_str:
            result_url = f"/viewer/{project_type}/{project_id_str}"

        return {
            "task_id": str(task.task_id),
            "project_id": project_id_str,
            "project_type": project_type,
            "status": project_status,
            "current_msg": current_msg,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "is_active": project_status in _ACTIVE_STATUSES,
            "progress_percent": _progress_percent(project_status, project),
            "best_cut_image_url": _best_cut_image_url(project) if project is not None else None,
            "result_url": result_url,
        }
    finally:
        db.close()


@router.patch("/tasks/{task_id}/notify")
async def update_task_notify(
    task_id: str,
    payload: dict = Body(...),
):
    try:
        uid = UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid task_id")

    raw_target = (payload or {}).get("notify_target", "")
    notify_target = str(raw_target or "").strip()
    if not notify_target:
        raise HTTPException(status_code=400, detail="notify_target is required")
    if not _PHONE_RE.match(notify_target):
        raise HTTPException(status_code=400, detail="Invalid phone number format")

    db = SessionLocal()
    try:
        task = get_video_task_active(db, uid)
        if not task:
            expired_or_missing = get_video_task_any(db, uid)
            if expired_or_missing:
                raise HTTPException(status_code=410, detail="만료된 작업입니다")
            raise HTTPException(status_code=404, detail="Task not found")
        updated = update_video_task_notify(db, uid, notify_target)
        if not updated:
            raise HTTPException(status_code=404, detail="Task not found")
        return {
            "task_id": str(updated.task_id),
            "notify_target": updated.notify_target,
            "updated": True,
        }
    finally:
        db.close()
