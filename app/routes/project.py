"""
프로젝트 소유권·목록·삭제 API.
"""
from uuid import UUID


from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.crud import claim_project, delete_project, get_project, get_projects_by_user_id
from app.database import get_db
from app.models import User

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _thumbnail_url_for_project(project_id: UUID, first_media_path: str | None) -> str | None:
    """첫 미디어 파일 경로로 썸네일 URL 생성. 없으면 None."""
    if not first_media_path:
        return None
    # file_path 예: storage/raw/{project_id}/uuid_filename.jpg
    parts = first_media_path.replace("\\", "/").strip("/").split("/")
    if len(parts) >= 4 and parts[0] == "storage" and parts[1] == "raw":
        filename = parts[-1]
        return f"/raw/{project_id}/{filename}"
    return None


@router.get("/my")
def list_my_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    로그인 유저의 프로젝트 목록. created_at 내림차순.
    반환: project_id, project_type, title, thumbnail_url, created_at
    """
    projects = get_projects_by_user_id(db, current_user.id)
    out = []
    for p in projects:
        first_path = p.media_files[0].file_path if p.media_files else None
        out.append({
            "project_id": str(p.id),
            "project_type": p.project_type or "video",
            "title": p.title or "",
            "thumbnail_url": _thumbnail_url_for_project(p.id, first_path),
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })
    return {"projects": out}


@router.post("/{project_id}/claim")
def claim_project_by_user(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    해당 프로젝트의 user_id를 현재 로그인 사용자로 설정.
    이미 소유자가 있으면 409. 프로젝트 없으면 404.
    """
    project = get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id is not None and project.user_id != current_user.id:
        raise HTTPException(status_code=409, detail="Project already owned by another user")
    claim_project(db, project_id, current_user.id)
    return {"message": "Project claimed", "project_id": str(project_id)}


@router.delete("/{project_id}")
def delete_my_project(
    request: Request,
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    본인 소유 프로젝트만 삭제. DB 레코드 제거(실제 파일은 별도 정리).
    HTMX 요청(HX-Request)이면 빈 HTML 200 반환해 항목만 DOM에서 제거.
    """
    project = get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not the project owner")
    delete_project(db, project_id)
    if request.headers.get("HX-Request"):
        return Response(content="", status_code=200, media_type="text/html")
    return {"message": "Project deleted", "project_id": str(project_id)}
