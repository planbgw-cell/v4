"""
업로드 API: 프로젝트 생성 + 파일 저장 (Zero-Wait I/O, pathlib).
사용자가 화면에서 드래그 앤 드롭으로 바꾼 순서가 그대로 order_index에 저장됨.

🛡️ [Rule Set] Flairy v4.0 경로/프로세스 격리: 응답에 project_type 필수 반환.
   클라이언트는 /progress/${project_type}/${project_id} 로 리다이렉트.
"""
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.crud import create_project
from app.database import SessionLocal
from app.models import MediaFile, ProjectMode
from app.services.video_service import run_ai_analysis

router = APIRouter(prefix="/api", tags=["upload"])

# 프로젝트 루트 (v4/)
ROOT = Path(__file__).resolve().parent.parent.parent
STORAGE_RAW_BASE = ROOT / "storage" / "raw"

MAX_TOTAL = 30
MAX_VIDEO_COUNT = 5
MAX_VIDEO_BYTES = 150 * 1024 * 1024  # 150MB (Bytes)


def _is_video(content_type: str) -> bool:
    return (content_type or "").startswith("video/")


def _validate_files(files: list[UploadFile]) -> None:
    """서버 측 재검증: 개수 및 동영상 용량. 위반 시 HTTPException."""
    if len(files) > MAX_TOTAL:
        raise HTTPException(
            status_code=400,
            detail=f"파일 개수는 최대 {MAX_TOTAL}개까지 가능합니다.",
        )
    video_count = 0
    for f in files:
        if _is_video(f.content_type or ""):
            video_count += 1
    if video_count > MAX_VIDEO_COUNT:
        raise HTTPException(
            status_code=400,
            detail=f"동영상은 최대 {MAX_VIDEO_COUNT}개까지 가능합니다.",
        )
    # 개별 동영상 용량은 읽으면서 체크 (아래 저장 시)


@router.post("/upload")
async def api_upload(
    background_tasks: BackgroundTasks,
    title: str = Form(..., max_length=255),
    mode: str = Form(...),
    project_type: str = Form("video"),
    files: list[UploadFile] = File(default=[]),
):
    """프로젝트 생성 후 파일을 storage/raw/{project_id}/ 에 저장하고 MediaFiles에 기록. 순서 유지."""
    if not files:
        raise HTTPException(status_code=400, detail="파일을 1개 이상 선택해 주세요.")

    _validate_files(files)

    if mode not in ("ai", "rule_based"):
        raise HTTPException(status_code=400, detail="mode는 'ai' 또는 'rule_based'여야 합니다.")
    project_mode = ProjectMode.AI if mode == "ai" else ProjectMode.RULE_BASED
    if project_type not in ("video", "album"):
        project_type = "video"

    db: Session = SessionLocal()
    try:
        project = create_project(
            db, title=title, mode=project_mode, status="PENDING", project_type=project_type
        )
        project_id = project.id
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"프로젝트 생성 실패: {e!s}")

    project_raw_dir = STORAGE_RAW_BASE / str(project_id)
    project_raw_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: list[Path] = []
    media_entries: list[tuple[str, str, int]] = []  # (file_path_str, file_type, order_index)

    try:
        for order_index, upload_file in enumerate(files):
            content_type = upload_file.content_type or ""
            is_video = _is_video(content_type)
            file_type = "video" if is_video else "image"

            # 동영상 용량 제한: 150 * 1024 * 1024 Bytes
            content = await upload_file.read()
            if is_video and len(content) > MAX_VIDEO_BYTES:
                for p in saved_paths:
                    try:
                        p.unlink(missing_ok=True)
                    except Exception:
                        pass
                raise HTTPException(
                    status_code=400,
                    detail=f"동영상 파일은 개당 최대 150MB까지 가능합니다. ({upload_file.filename})",
                )

            safe_name = (upload_file.filename or "file").replace("..", "").lstrip("/")
            if not safe_name:
                safe_name = "file"
            stored_name = f"{uuid.uuid4().hex}_{safe_name}"
            out_path = project_raw_dir / stored_name
            out_path.write_bytes(content)
            saved_paths.append(out_path)
            file_path_str = str(Path("storage") / "raw" / str(project_id) / stored_name)
            media_entries.append((file_path_str, file_type, order_index))

        # DB에 한 번에 기록 (순서 = order_index 그대로)
        for file_path_str, file_type, order_index in media_entries:
            m = MediaFile(
                project_id=project_id,
                file_path=file_path_str,
                file_type=file_type,
                order_index=order_index,
                is_selected=True,
            )
            db.add(m)
        db.commit()
    except HTTPException:
        db.rollback()
        for p in saved_paths:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        raise
    except Exception as e:
        db.rollback()
        for p in saved_paths:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"파일 저장 또는 DB 기록 실패: {e!s}")
    finally:
        db.close()

    if project_mode == ProjectMode.AI:
        background_tasks.add_task(run_ai_analysis, project_id)

    return {"project_id": str(project_id), "project_type": project_type}
