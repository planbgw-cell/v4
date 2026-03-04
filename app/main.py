"""
Flairy v4.0 FastAPI 앱.
Jinja2 템플릿 및 정적 파일 서빙.
"""
import logging
import os
from pathlib import Path
from uuid import UUID

logging.getLogger("app").setLevel(logging.INFO)
logging.getLogger("engine").setLevel(logging.INFO)

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.crud import get_project
from app.database import SessionLocal, ensure_ai_progress_columns, ensure_logs_column
from app.routes import upload as upload_router
from app.routes import status as status_router
from app.routes import generate as generate_router

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
TEMPLATES_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"
FINAL_DIR = ROOT / "storage" / "final"

app = FastAPI(title="Flairy v4")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.on_event("startup")
def on_startup():
    """앱 기동 시 projects 로그·AI 진행률 컬럼이 없으면 추가."""
    ensure_logs_column()
    ensure_ai_progress_columns()
app.include_router(upload_router.router)
app.include_router(status_router.router)
app.include_router(generate_router.router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
if FINAL_DIR.exists():
    app.mount("/outputs", StaticFiles(directory=str(FINAL_DIR)), name="outputs")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/progress", response_class=HTMLResponse)
async def progress_page(request: Request, project_id: str = "", debug: str = ""):
    """진행률 UI. HTMX로 2초마다 /api/projects/{id}/status 갱신. debug=1이면 디버그 패널·보기 버튼 표시."""
    if not project_id:
        return HTMLResponse(
            "<!DOCTYPE html><html><body><p>project_id가 필요합니다.</p><a href='/'>랜딩</a></body></html>"
        )
    is_debug = (debug.lower() in ("true", "1")) or (os.getenv("DEBUG", "").lower() in ("true", "1"))
    return templates.TemplateResponse(
        "progress.html",
        {"request": request, "project_id": project_id, "debug": is_debug},
    )


@app.get("/viewer/{project_id}", response_class=HTMLResponse)
async def viewer_page(request: Request, project_id: str):
    """하이라이트 영상 뷰어. DB에서 프로젝트 제목·출력 경로 조회 후 9:16 플레이어로 재생."""
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
        title = project.title or "하이라이트 영상"
        if project.output_path:
            if project.output_path == f"storage/final/{project_id}.mp4":
                video_url = f"/outputs/{project_id}.mp4"  # 레거시 평면 구조
            else:
                video_url = f"/outputs/{project_id}/output.mp4"
        else:
            video_url = None
    finally:
        db.close()
    return templates.TemplateResponse(
        "viewer.html",
        {
            "request": request,
            "project_id": project_id,
            "project_title": title,
            "video_url": video_url,
        },
    )
