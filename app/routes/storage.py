"""
포터블 앨범 HTML export API.
"""
from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_optional
from app.config import get_public_base_url
from app.crud import get_project
from app.database import get_db
from app.models import User
from app.services.portable_album_compiler import (
    compile_portable_album_html,
    content_disposition_attachment,
    load_album_layout,
    safe_highlight_export_filename,
)
from app.storage import get_project_final_dir, get_storage_root

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["storage"])


def _ensure_project_owner(project, current_user: User | None) -> None:
    if project.user_id is not None:
        if current_user is None or project.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not the project owner")


def _resolve_highlight_video_path(project_id: UUID, output_path: str | None) -> Path | None:
    root = get_storage_root()
    if output_path:
        normalized = output_path.replace("\\", "/").strip()
        candidate = root / normalized
        if candidate.is_file():
            return candidate
    final_dir = get_project_final_dir(project_id)
    for name in ("output.mp4", f"{project_id}.mp4"):
        candidate = final_dir / name
        if candidate.is_file():
            return candidate
    return None


@router.get("/projects/{project_id}/download-video")
def download_project_video(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    project = get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if (project.project_type or "video") != "video":
        raise HTTPException(status_code=400, detail="Project is not a video")

    if (project.status or "").upper() != "COMPLETED":
        raise HTTPException(status_code=400, detail="Video is not completed yet")

    _ensure_project_owner(project, current_user)

    video_path = _resolve_highlight_video_path(project_id, project.output_path)
    if not video_path or not video_path.is_file():
        raise HTTPException(status_code=404, detail="Video file not found")

    title = project.title or "하이라이트 영상"
    filename = safe_highlight_export_filename(title)
    return FileResponse(
        path=video_path,
        media_type="video/mp4",
        headers={
            "Content-Disposition": content_disposition_attachment(
                filename,
                default_name="flairy_highlight.mp4",
            ),
            "Cache-Control": "no-store",
        },
    )


@router.get("/projects/{project_id}/export-html")
def export_project_html(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    project = get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if (project.project_type or "video") != "album":
        raise HTTPException(status_code=400, detail="Project is not an album")

    if (project.status or "").upper() != "COMPLETED":
        raise HTTPException(status_code=400, detail="Album is not completed yet")

    _ensure_project_owner(project, current_user)

    try:
        layout = load_album_layout(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    title = project.title or "디지털 앨범"
    try:
        html, filename = compile_portable_album_html(
            project_id=project_id,
            title=title,
            layout=layout,
            public_base_url=get_public_base_url(),
        )
    except ValueError as e:
        raise HTTPException(status_code=413, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        logger.exception("Portable album export failed project=%s", project_id)
        raise HTTPException(status_code=500, detail="Failed to compile portable album") from e

    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": content_disposition_attachment(
                filename,
                default_name="flairy_album.html",
            ),
            "Cache-Control": "no-store",
        },
    )
