import uuid
from datetime import timedelta, timezone
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, get_current_user_optional
from app.config import get_public_base_url
from app.database import get_db
from app.models import Inquiry

ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = ROOT / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["public_base_url"] = get_public_base_url()

KST = timezone(timedelta(hours=9))
router = APIRouter(tags=["inquiries"])


def fmt_kst(dt) -> str:
    if not dt:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST).strftime("%Y.%m.%d %H:%M")


def _status_label(status: str | None) -> str:
    if (status or "").upper() == "ANSWERED":
        return "답변 완료"
    return "답변 대기"


class InquiryCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)


@router.get("/qna", response_class=HTMLResponse)
async def qna_list_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_optional),
):
    items = []
    if current_user:
        inquiries = (
            db.query(Inquiry)
            .filter(Inquiry.user_id == current_user.id)
            .order_by(Inquiry.created_at.desc())
            .all()
        )
        total = len(inquiries)
        for idx, inquiry in enumerate(inquiries):
            items.append({
                "inquiry": inquiry,
                "row_num": total - idx,
                "created_at_kst": fmt_kst(inquiry.created_at),
                "status_label": _status_label(inquiry.status),
            })
    return templates.TemplateResponse(
        "qna_list.html",
        {"request": request, "current_user": current_user, "items": items},
    )


@router.get("/qna/new", response_class=HTMLResponse)
async def qna_write_page(
    request: Request,
    current_user=Depends(get_current_user_optional),
):
    if current_user is None:
        return RedirectResponse(url="/?login=qna", status_code=302)
    return templates.TemplateResponse(
        "qna_write.html",
        {"request": request, "current_user": current_user},
    )


@router.get("/qna/{inquiry_id}", response_class=HTMLResponse)
async def qna_detail_page(
    inquiry_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_optional),
):
    if current_user is None:
        return RedirectResponse(url="/?login=qna", status_code=302)
    try:
        iid = UUID(inquiry_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Inquiry not found")

    inquiry = (
        db.query(Inquiry)
        .filter(Inquiry.id == iid, Inquiry.user_id == current_user.id)
        .first()
    )
    if not inquiry:
        raise HTTPException(status_code=404, detail="Inquiry not found")

    return templates.TemplateResponse(
        "qna_detail.html",
        {
            "request": request,
            "current_user": current_user,
            "inquiry": inquiry,
            "created_at_kst": fmt_kst(inquiry.created_at),
            "answered_at_kst": fmt_kst(inquiry.answered_at),
            "status_label": _status_label(inquiry.status),
            "is_answered": (inquiry.status or "").upper() == "ANSWERED",
        },
    )


@router.post("/api/inquiries")
def create_inquiry(
    body: InquiryCreateBody,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inquiry = Inquiry(
        id=uuid.uuid4(),
        user_id=current_user.id,
        title=body.title.strip(),
        content=body.content.strip(),
        is_secret=False,
        status="PENDING",
    )
    db.add(inquiry)
    db.commit()
    db.refresh(inquiry)
    return {
        "id": str(inquiry.id),
        "title": inquiry.title,
        "status": inquiry.status,
        "created_at": inquiry.created_at.isoformat() if inquiry.created_at else None,
    }
