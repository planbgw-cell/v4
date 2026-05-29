"""
업로드 API: 프로젝트 생성 + 파일 저장 (Zero-Wait I/O, pathlib).
사용자가 화면에서 드래그 앤 드롭으로 바꾼 순서가 그대로 order_index에 저장됨.
"""
import logging
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.cookie_utils import GUEST_COOKIE_KEY, set_guest_token_cookie
from app.auth.dependencies import get_current_user_optional
from app.config import get_beta_max_project_quota, get_highlight_merge_mode
from app.crud import count_projects_for_owner, create_project, create_video_task
from app.database import SessionLocal
from app.models import MediaFile, ProjectMode
from app.services.video_service import run_ai_analysis
from app.services.web_video_compat import VideoTranscodeError, ensure_web_compatible_video
from app.utils.ffmpeg_accel import get_accel_type

router = APIRouter(prefix="/api", tags=["upload"])
logger = logging.getLogger(__name__)

# 프로젝트 루트 (v4/)
ROOT = Path(__file__).resolve().parent.parent.parent
STORAGE_RAW_BASE = ROOT / "storage" / "raw"

MIN_UPLOAD_FILES = 5
MAX_TOTAL = 30
MAX_VIDEO_COUNT = 5
MAX_VIDEO_BYTES = 150 * 1024 * 1024  # 150MB (Bytes)
GUEST_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1년


def _beta_quota_message() -> str:
    return (
        f"베타서비스 기간에는 1인당 최대 {get_beta_max_project_quota()}개까지만 "
        "하이라이트 영상 생성이 가능합니다."
    )


def _is_video(content_type: str) -> bool:
    return (content_type or "").startswith("video/")


def _classify_transcode_failure(message: str) -> str:
    m = (message or "").lower()
    if "vaapi" in m and ("permission denied" in m or "권한" in m):
        return "VAAPI_PERMISSION"
    if "out of memory" in m:
        return "OOM"
    if "ffmpeg" in m and ("filter" in m or "invalid argument" in m):
        return "FFMPEG_FILTER_ERROR"
    if "gpu" in m or "nvenc" in m or "vaapi" in m:
        return "GPU_ERROR"
    return "UNKNOWN"


def _log_admin_transcode_failure(
    *,
    media_file_id: int,
    project_id: str | None,
    message: str,
) -> None:
    db: Session = SessionLocal()
    try:
        db.execute(text("""
            INSERT INTO admin_action_logs (
                id, admin_id, action_type, target_id, details, ip_address, user_agent
            ) VALUES (
                :id, NULL, 'TRANSCODE_FAIL', :target_id, CAST(:details AS jsonb), NULL, NULL
            )
        """), {
            "id": str(uuid.uuid4()),
            "target_id": str(media_file_id),
            "details": json.dumps(
                {
                    "media_file_id": media_file_id,
                    "project_id": project_id,
                    "error_code": _classify_transcode_failure(message),
                    "message": (message or "")[:1200],
                    "accel_mode": get_accel_type().upper(),
                    "merge_mode": get_highlight_merge_mode().upper(),
                },
                ensure_ascii=False,
            ),
        })
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


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


def _transcode_video_in_background(media_file_id: int, raw_abs_path: str) -> None:
    """비디오 웹호환 트랜스코딩 백그라운드 작업."""
    db: Session = SessionLocal()
    try:
        media = db.query(MediaFile).filter(MediaFile.id == media_file_id).first()
        if not media:
            return
        media.processing_status = "PROCESSING"
        db.commit()

        src_path = Path(raw_abs_path)
        final_path = ensure_web_compatible_video(src_path)
        media.file_path = str(Path("storage") / "raw" / str(media.project_id) / final_path.name)
        media.processing_status = "READY"
        db.commit()
    except VideoTranscodeError:
        db.rollback()
        media = db.query(MediaFile).filter(MediaFile.id == media_file_id).first()
        if media:
            media.processing_status = "FAILED"
            db.commit()
            _log_admin_transcode_failure(
                media_file_id=media_file_id,
                project_id=str(media.project_id),
                message="VideoTranscodeError",
            )
        logger.exception("동영상 트랜스코딩 실패: media_file_id=%s", media_file_id)
    except Exception:
        db.rollback()
        media = db.query(MediaFile).filter(MediaFile.id == media_file_id).first()
        if media:
            media.processing_status = "FAILED"
            db.commit()
            _log_admin_transcode_failure(
                media_file_id=media_file_id,
                project_id=str(media.project_id),
                message="Background transcode exception",
            )
        logger.exception("비디오 백그라운드 작업 실패: media_file_id=%s", media_file_id)
    finally:
        db.close()


@router.post("/upload")
async def api_upload(
    request: Request,
    background_tasks: BackgroundTasks,
    title: str = Form(..., max_length=255),
    mode: str = Form(...),
    project_type: str = Form("video"),
    files: list[UploadFile] = File(default=[]),
    current_user=Depends(get_current_user_optional),
):
    """프로젝트 생성 후 파일 저장/DB 기록 후 202로 즉시 반환. 비디오는 백그라운드 트랜스코딩."""
    quota_limit = get_beta_max_project_quota()
    guest_token = (request.cookies.get(GUEST_COOKIE_KEY) or "").strip() or uuid.uuid4().hex

    db_quota: Session = SessionLocal()
    try:
        if current_user is not None:
            project_count = count_projects_for_owner(db_quota, user_id=current_user.id)
        else:
            project_count = count_projects_for_owner(db_quota, guest_token=guest_token)
        if project_count >= quota_limit:
            raise HTTPException(status_code=403, detail=_beta_quota_message())
    finally:
        db_quota.close()

    if len(files) < MIN_UPLOAD_FILES:
        raise HTTPException(
            status_code=400,
            detail="최소 5개 이상의 사진을 업로드해야 앨범 생성이 가능합니다.",
        )

    _validate_files(files)

    if mode not in ("ai", "rule_based"):
        raise HTTPException(status_code=400, detail="mode는 'ai' 또는 'rule_based'여야 합니다.")
    project_mode = ProjectMode.AI if mode == "ai" else ProjectMode.RULE_BASED
    if project_type not in ("video", "album"):
        project_type = "video"

    db: Session = SessionLocal()
    task_type = (
        "ALBUM_AI"
        if project_type == "album"
        else ("VIDEO_AI" if project_mode == ProjectMode.AI else "VIDEO_RULE")
    )
    task = None
    task_id_str = None
    try:
        project = create_project(
            db, title=title, mode=project_mode, status="PENDING", project_type=project_type
        )
        if current_user is not None:
            project.user_id = current_user.id
            db.commit()
            db.refresh(project)
        project_id = project.id
        task = create_video_task(
            db,
            guest_token=guest_token,
            user_id=getattr(current_user, "id", None),
            project_id=project_id,
            task_type=task_type,
            status="PENDING",
            current_msg="작업 준비 중...",
        )
        task_id_str = str(task.task_id)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"프로젝트 생성 실패: {e!s}")

    project_raw_dir = STORAGE_RAW_BASE / str(project_id)
    project_raw_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: list[Path] = []
    media_entries: list[tuple[str, str, int, str, str]] = []  # (path, type, order, status, abs_path)
    pending_video_jobs: list[tuple[int, str]] = []
    file_ids: list[int] = []

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
            file_path_str = str(Path("storage") / "raw" / str(project_id) / out_path.name)
            initial_status = "PENDING" if is_video else "READY"
            media_entries.append((file_path_str, file_type, order_index, initial_status, str(out_path)))

        # DB에 한 번에 기록 (순서 = order_index 그대로)
        for file_path_str, file_type, order_index, processing_status, abs_path in media_entries:
            m = MediaFile(
                project_id=project_id,
                file_path=file_path_str,
                file_type=file_type,
                order_index=order_index,
                processing_status=processing_status,
                is_selected=True,
            )
            db.add(m)
            db.flush()
            file_ids.append(m.id)
            if file_type == "video":
                pending_video_jobs.append((m.id, abs_path))
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
    for media_file_id, abs_path in pending_video_jobs:
        background_tasks.add_task(_transcode_video_in_background, media_file_id, abs_path)

    response = JSONResponse(
        status_code=202,
        content={
            "project_id": str(project_id),
            "project_type": project_type,
            "task_id": task_id_str,
            "guest_token": guest_token,
            "file_ids": file_ids,
            "pending_file_ids": [media_file_id for media_file_id, _ in pending_video_jobs],
        },
    )
    if current_user is None:
        set_guest_token_cookie(response, guest_token, GUEST_COOKIE_MAX_AGE)
    return response


@router.get("/upload/status/{file_id}")
async def get_upload_status(file_id: int):
    """단일 파일 처리 상태 조회."""
    db: Session = SessionLocal()
    try:
        media = db.query(MediaFile).filter(MediaFile.id == file_id).first()
        if not media:
            raise HTTPException(status_code=404, detail="file not found")
        return {
            "file_id": media.id,
            "project_id": str(media.project_id),
            "file_type": media.file_type,
            "processing_status": (media.processing_status or "PENDING").upper(),
            "file_path": media.file_path,
        }
    finally:
        db.close()
