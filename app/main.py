"""
Flairy v4.0 FastAPI 앱.
Jinja2 템플릿 및 정적 파일 서빙.

---
🛡️ [Rule Set] Flairy v4.0 경로 및 프로세스 격리 규칙
---
1. 명시적 URL 구조 (Explicit URL Path)
   진행/결과 경로는 반드시 {type}을 포함. DB 조회 없이 즉시 렌더 대상 결정.
   - 영상: /progress/video/{id}, /viewer/video/{id}
   - 앨범: /progress/album/{id}, /viewer/album/{id}

2. 생성 요청 및 리다이렉트 (Landing Page JS)
   업로드 응답의 {id}, {project_type}으로 window.location.href = /progress/${type}/${id} 이동.

3. 서버 템플릿 분기 (FastAPI)
   라우터에서 {type} 인자로 템플릿 결정.
   - type=video → progress.html / viewer.html
   - type=album → progress_album.html / viewer_album.html
---
"""
import logging
import os
from pathlib import Path
from uuid import UUID

logging.getLogger("app").setLevel(logging.INFO)
logging.getLogger("engine").setLevel(logging.INFO)
logger = logging.getLogger(__name__)

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.auth.dependencies import get_current_user_optional, COOKIE_KEY
from app.crud import get_project, get_projects_by_user_id
from app.database import (
    SessionLocal,
    ensure_ai_progress_columns,
    ensure_logs_column,
    ensure_project_type_column,
    ensure_user_id_column,
)
from app.routes import auth as auth_router
from app.routes import project as project_router
from app.routes import upload as upload_router
from app.routes import status as status_router
from app.routes import generate as generate_router

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
TEMPLATES_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"
FINAL_DIR = ROOT / "storage" / "final"
RAW_DIR = ROOT / "storage" / "raw"

app = FastAPI(title="Flairy v4")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.on_event("startup")
def on_startup():
    """앱 기동 시 projects 로그·AI 진행률·project_type·user_id 컬럼이 없으면 추가."""
    ensure_logs_column()
    ensure_ai_progress_columns()
    ensure_project_type_column()
    ensure_user_id_column()


app.include_router(auth_router.router)
app.include_router(project_router.router)
app.include_router(upload_router.router)
app.include_router(status_router.router)
app.include_router(generate_router.router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
if FINAL_DIR.exists():
    app.mount("/outputs", StaticFiles(directory=str(FINAL_DIR)), name="outputs")
if RAW_DIR.exists():
    app.mount("/raw", StaticFiles(directory=str(RAW_DIR)), name="raw")


def _mypage_thumbnail_url(project_id: UUID, first_media_path: str | None) -> str | None:
    """첫 미디어 경로로 썸네일 URL 생성 (마이페이지용)."""
    if not first_media_path:
        return None
    parts = first_media_path.replace("\\", "/").strip("/").split("/")
    if len(parts) >= 4 and parts[0] == "storage" and parts[1] == "raw":
        return f"/raw/{project_id}/{parts[-1]}"
    return None


@app.get("/auth/logout", response_class=RedirectResponse)
async def auth_logout():
    """JWT 쿠키 삭제 후 메인(/)으로 리다이렉트."""
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie(COOKIE_KEY, path="/")
    return response


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, current_user=Depends(get_current_user_optional)):
    return templates.TemplateResponse(
        "index.html", {"request": request, "current_user": current_user}
    )


@app.get("/mypage", response_class=HTMLResponse)
async def mypage_page(
    request: Request,
    current_user=Depends(get_current_user_optional),
):
    """내 보관함. 로그인 필수; 비로그인 시 / 로 리다이렉트."""
    if current_user is None:
        return RedirectResponse(url="/", status_code=302)
    db = SessionLocal()
    try:
        projects_raw = get_projects_by_user_id(db, current_user.id)
        projects = []
        for p in projects_raw:
            first_path = p.media_files[0].file_path if p.media_files else None
            projects.append({
                "project_id": str(p.id),
                "project_type": p.project_type or "video",
                "title": p.title or "",
                "thumbnail_url": _mypage_thumbnail_url(p.id, first_path),
                "created_at": p.created_at.isoformat() if p.created_at else None,
            })
        return templates.TemplateResponse(
            "mypage.html",
            {"request": request, "projects": projects, "current_user": current_user},
        )
    finally:
        db.close()


def _progress_debug(debug: str) -> bool:
    return (debug.lower() in ("true", "1")) or (os.getenv("DEBUG", "").lower() in ("true", "1"))


@app.get("/progress/{type}/{project_id}", response_class=HTMLResponse)
async def progress_page(request: Request, type: str, project_id: str, debug: str = ""):
    """진행률 UI. type으로 템플릿 즉시 결정 (DB 조회 없음). video→progress.html, album→progress_album.html."""
    if type not in ("video", "album"):
        return HTMLResponse(
            "<!DOCTYPE html><html><body><p>type은 video 또는 album이어야 합니다.</p><a href='/'>랜딩</a></body></html>",
            status_code=404,
        )
    try:
        UUID(project_id)
    except ValueError:
        return HTMLResponse(
            "<!DOCTYPE html><html><body><p>잘못된 project_id입니다.</p><a href='/'>랜딩</a></body></html>",
            status_code=404,
        )
    template = "progress.html" if type == "video" else "progress_album.html"
    return templates.TemplateResponse(
        template,
        {"request": request, "project_id": project_id, "project_type": type, "debug": _progress_debug(debug)},
    )


@app.get("/progress", response_class=HTMLResponse)
async def progress_page_legacy(request: Request, project_id: str = "", debug: str = ""):
    """레거시: project_id만 있으면 DB 조회 후 /progress/{type}/{id}로 리다이렉트."""
    if not project_id:
        return HTMLResponse(
            "<!DOCTYPE html><html><body><p>project_id가 필요합니다.</p><a href='/'>랜딩</a></body></html>"
        )
    try:
        uid = UUID(project_id)
    except ValueError:
        return HTMLResponse(
            "<!DOCTYPE html><html><body><p>잘못된 project_id입니다.</p><a href='/'>랜딩</a></body></html>",
            status_code=404,
        )
    db = SessionLocal()
    try:
        project = get_project(db, uid)
        if not project:
            return HTMLResponse(
                "<!DOCTYPE html><html><body><p>프로젝트를 찾을 수 없습니다.</p><a href='/'>랜딩</a></body></html>",
                status_code=404,
            )
        project_type = getattr(project, "project_type", None) or "video"
        return RedirectResponse(
            url=f"/progress/{project_type}/{project_id}" + (f"?debug={debug}" if debug else ""),
            status_code=302,
        )
    finally:
        db.close()


def _render_project_error(request: Request, status_code: int = 404, current_user=None):
    """존재하지 않거나 권한이 없는 프로젝트 안내 페이지."""
    return templates.TemplateResponse(
        "error_project.html",
        {"request": request, "current_user": current_user},
        status_code=status_code,
    )


@app.get("/viewer/{type}/{project_id}", response_class=HTMLResponse)
async def viewer_page(
    request: Request,
    type: str,
    project_id: str,
    mode: str | None = None,
    current_user=Depends(get_current_user_optional),
):
    """뷰어. type으로 템플릿 즉시 결정. mode=mypage면 마이페이지 조회용 버튼(공유/다운로드), 없으면 생성 모드(저장/내 보관함)."""
    if type not in ("video", "album"):
        return _render_project_error(request, 404, current_user)
    try:
        uid = UUID(project_id)
    except ValueError:
        return _render_project_error(request, 404, current_user)
    db = SessionLocal()
    try:
        project = get_project(db, uid)
        if not project:
            return _render_project_error(request, 404, current_user)
        project_mode = getattr(project, "mode", None)
        if project_mode is not None and hasattr(project_mode, "value"):
            project_mode = project_mode.value
        if project_mode is None:
            project_mode = "rule_based"
        if type == "album":
            media_files = getattr(project, "media_files", None) or []
            logger.info("[Album Viewer] project_id=%s media_count=%s", project_id, len(media_files))
        title = project.title or ("디지털 앨범" if type == "album" else "하이라이트 영상")
        video_url = None
        if type == "video" and project.output_path:
            if project.output_path == f"storage/final/{project_id}.mp4":
                video_url = f"/outputs/{project_id}.mp4"
            else:
                video_url = f"/outputs/{project_id}/output.mp4"
    finally:
        db.close()
    ctx = {
        "request": request,
        "project_id": project_id,
        "project_title": title,
        "current_url": request.url.path,
        "project_type": type,
        "mode": mode,
        "project_mode": project_mode,
        "current_user": current_user,
    }
    if type == "video":
        ctx["video_url"] = video_url

    # HTMX 요청 시 조각만 반환 (전체 html/body 중복 방지, 스타일은 조각 내부에 포함)
    if request.headers.get("HX-Request"):
        if type == "video":
            return templates.TemplateResponse("viewer_fragment_video.html", ctx)
        if type == "album":
            return templates.TemplateResponse("viewer_fragment_album.html", ctx)
    template = "viewer.html" if type == "video" else "viewer_album.html"
    return templates.TemplateResponse(template, ctx)


@app.get("/viewer/{project_id}", response_class=HTMLResponse)
async def viewer_page_legacy(request: Request, project_id: str):
    """레거시: DB에서 project_type 조회 후 /viewer/{type}/{id}로 리다이렉트."""
    try:
        uid = UUID(project_id)
    except ValueError:
        return HTMLResponse(
            "<!DOCTYPE html><html><body><p>잘못된 project_id입니다.</p><a href='/'>랜딩</a></body></html>",
            status_code=404,
        )
    db = SessionLocal()
    try:
        project = get_project(db, uid)
        if not project:
            return HTMLResponse(
                "<!DOCTYPE html><html><body><p>프로젝트를 찾을 수 없습니다.</p><a href='/'>랜딩</a></body></html>",
                status_code=404,
            )
        project_type = getattr(project, "project_type", None) or "video"
        return RedirectResponse(url=f"/viewer/{project_type}/{project_id}", status_code=302)
    finally:
        db.close()
