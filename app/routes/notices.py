from datetime import timedelta, timezone
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_optional
from app.config import get_public_base_url
from app.database import get_db
from app.models import Notice

ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = ROOT / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["public_base_url"] = get_public_base_url()

KST = timezone(timedelta(hours=9))
router = APIRouter(tags=["notices"])


def fmt_kst(dt) -> str:
    if not dt:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST).strftime("%Y.%m.%d %H:%M")


@router.get("/notice", response_class=HTMLResponse)
async def notice_list_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_optional),
):
    notices = (
        db.query(Notice)
        .order_by(Notice.is_pinned.desc(), Notice.created_at.desc())
        .all()
    )
    total = len(notices)
    items = []
    for idx, notice in enumerate(notices):
        items.append({
            "notice": notice,
            "row_num": total - idx,
            "created_at_kst": fmt_kst(notice.created_at),
        })
    return templates.TemplateResponse(
        "notice_list.html",
        {"request": request, "current_user": current_user, "items": items},
    )


@router.get("/notice/{notice_id}", response_class=HTMLResponse)
async def notice_detail_page(
    notice_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_optional),
):
    try:
        nid = UUID(notice_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Notice not found")

    notice = db.query(Notice).filter(Notice.id == nid).first()
    if not notice:
        raise HTTPException(status_code=404, detail="Notice not found")

    notice.view_count = int(notice.view_count or 0) + 1
    db.commit()
    db.refresh(notice)

    return templates.TemplateResponse(
        "notice_detail.html",
        {
            "request": request,
            "current_user": current_user,
            "notice": notice,
            "created_at_kst": fmt_kst(notice.created_at),
        },
    )
