"""
상태 조회 API: HTMX용 Partial HTML 반환.

🛡️ [Rule Set] Flairy v4.0 경로/프로세스 격리: progress/viewer는 /progress/{type}/{id}, /viewer/{type}/{id} 사용.
   본 API는 project_id만 사용하며, type은 페이지 URL에서 이미 결정된 상태.
"""
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.crud import get_project
from app.database import SessionLocal

router = APIRouter(prefix="/api", tags=["status"])
ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = ROOT / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

STATUS_MESSAGES = {
    "PENDING": "대기 중...",
    "ANALYZING": "사진 분석 중...",
    "COMPOSING": "페이지 구성 중...",
    "GENERATING": "하이라이트 영상/앨범 생성 중...",
    "COMPLETED": "생성 완료!",
}

# 상세 단계 (sub_status). 클라이언트/UX용.
SUB_STATUS_MAP = {
    "PENDING": "PENDING",
    "ANALYZING": "ANALYZING_MEDIA",
    "COMPOSING": "COMPOSING",
    "GENERATING": "RENDERING",
    "COMPLETED": "COMPLETED",
}


@router.get("/projects/{project_id}/status", response_class=HTMLResponse)
async def get_project_status(request: Request, project_id: str, debug: str = ""):
    """DB에서 project status, mode, logs를 조회해 Partial HTML 조각을 반환 (HTMX 갱신용)."""
    try:
        uid = UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid project_id")
    db = SessionLocal()
    try:
        project = get_project(db, uid)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        status = (project.status or "PENDING").strip().upper()
        raw = getattr(project, "mode", None)
        mode = (getattr(raw, "value", None) if raw is not None and hasattr(raw, "value") else None) or (raw if isinstance(raw, str) else None) or "rule_based"
        if mode is None:
            mode = "rule_based"
        sub_status = SUB_STATUS_MAP.get(status, status)
        project_type = (getattr(project, "project_type", None) or "video").strip().lower()
        message = STATUS_MESSAGES.get(status, status)
        # Step4: 비디오/앨범·AI 모드별 메시지 (rule_based 비디오는 AI 문구 미사용)
        if status == "COMPOSING":
            if project_type == "video" and mode == "ai":
                message = "AI가 스토리 순서를 반영하고 있습니다. 곧 영상 렌더링이 시작됩니다."
            elif project_type == "video":
                message = "하이라이트 영상을 준비하는 중입니다..."
        elif status == "COMPLETED" and project_type == "video" and mode == "ai":
            message = "생성 완료! AI 스토리 순서·감성 자막이 반영된 하이라이트입니다."
        total = getattr(project, "ai_total_count", None) or 0
        processed = getattr(project, "ai_processed_count", None) or 0
        percentage = round(100 * processed / total) if total else 0
        progress_message = ""
        if status == "ANALYZING" and mode == "ai" and total > 0:
            progress_message = f"{total}장의 사진 중 {min(processed + 1, total)}번째 사진 분석 중..."
            message = f"AI가 소중한 추억을 분석하고 있습니다 ({processed}/{total})"
        elif status == "ANALYZING" and mode == "ai":
            message = "AI가 사진을 분석 중입니다..."
        # 디버그 모드일 때는 logs의 마지막 10줄만 tail로 전달
        logs_tail = ""
        debug_mode = debug.lower() in ("1", "true", "yes")
        if debug_mode and getattr(project, "logs", None):
            lines = (project.logs or "").rstrip().splitlines()
            logs_tail = "\n".join(lines[-10:])
        ai_pipeline_debug = ""
        if debug_mode and project_type == "video" and mode == "ai":
            raw_order = getattr(project, "ai_narrative_order", None)
            if isinstance(raw_order, dict) and raw_order:
                ai_pipeline_debug = (
                    f"[AI 파이프라인] 서사 가중치(narrative_weight) 저장됨: {len(raw_order)}개 키"
                )
            elif isinstance(raw_order, list) and raw_order:
                ai_pipeline_debug = (
                    f"[AI 파이프라인] 서사 순서(구버전 리스트) 저장됨: {len(raw_order)}개"
                )
            else:
                ai_pipeline_debug = (
                    "[AI 파이프라인] 서사 데이터 DB 없음 → 렌더 시 생성 또는 order_index 폴백"
                )
        return templates.TemplateResponse(
            "partials/_progress_fragment.html",
            {
                "request": request,
                "status": status,
                "sub_status": sub_status,
                "mode": mode,
                "project_type": project_type,
                "message": message,
                "total": total,
                "processed": processed,
                "percentage": percentage,
                "progress_message": progress_message,
                "logs_tail": logs_tail,
                "ai_pipeline_debug": ai_pipeline_debug,
            },
        )
    finally:
        db.close()
