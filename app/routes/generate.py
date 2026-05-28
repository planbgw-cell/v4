"""
하이라이트 영상 생성 API. AI 모드일 때는 ai_analysis가 모두 채워진 뒤에만 렌더링 시작.

🛡️ [Rule Set] Flairy v4.0 경로/프로세스 격리: project_type이 'album'이면 VideoEngine 호출 금지.
   album → album_engine.build_layout() / album_layout.json만 생성.
   video → FlairyVideoEngine.create_highlight() 만 사용.
"""
import logging
import json
import uuid
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import text

from app.auth.dependencies import get_current_user_optional
from app.crud import (
    get_latest_video_task_by_project,
    get_project,
    get_project_media_readiness,
    mark_video_task_status,
    update_project_output_path,
    update_project_status,
)
from app.config import get_highlight_merge_mode
from app.database import SessionLocal
from app.storage import get_project_final_dir
from app.services import narrative_service
from app.services.album_service import AlbumAIService
from app.services.notification_service import send_task_completion_alert
from app.services.video_service import run_ai_analysis
from app.utils.color_utils import get_accent_color_hex, get_dominant_color_hex
from engine.album_engine import build_layout, build_layout_ai, save_album_layout
from engine.bgm_engine import get_dominant_emotion, select_bgm_path
from engine.video_engine import FlairyVideoEngine
from app.utils.ffmpeg_accel import get_accel_type

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["generate"])
ROOT = Path(__file__).resolve().parent.parent.parent


def _is_debug_admin_email(email: str | None) -> bool:
    e = (email or "").strip().lower()
    return e == "admin@flairy.kr"


def _mode_value(project) -> str:
    """DB/드라이버가 enum 또는 문자열로 반환해도 'ai' 여부를 안정적으로 판별."""
    if not project or not getattr(project, "mode", None):
        return "rule_based"
    m = project.mode
    if hasattr(m, "value"):
        return (m.value or "rule_based") or "rule_based"
    return "ai" if m == "ai" else "rule_based"


def _is_ai_mode(project) -> bool:
    return _mode_value(project) == "ai"


def _classify_failure(message: str) -> str:
    m = (message or "").lower()
    if "vaapi" in m and ("permission denied" in m or "권한" in m):
        return "VAAPI_PERMISSION"
    if "out of memory" in m or "cannot allocate memory" in m:
        return "OOM"
    if "ffmpeg" in m and ("filter" in m or "invalid argument" in m):
        return "FFMPEG_FILTER_ERROR"
    if "gpu" in m or "nvenc" in m or "vaapi" in m:
        return "GPU_ERROR"
    if "database" in m or "sql" in m:
        return "DB_ERROR"
    return "UNKNOWN"


def _log_admin_render_failure(
    *,
    project_id: UUID,
    task_id: str | None,
    message: str,
    merge_mode_request: str | None,
) -> None:
    db = SessionLocal()
    try:
        db.execute(text("""
            INSERT INTO admin_action_logs (
                id, admin_id, action_type, target_id, details, ip_address, user_agent
            )
            VALUES (
                :id, NULL, 'RENDER_FAIL', :target_id, CAST(:details AS jsonb), NULL, NULL
            )
        """), {
            "id": str(uuid.uuid4()),
            "target_id": str(project_id),
            "details": json.dumps(
                {
                    "project_id": str(project_id),
                    "task_id": task_id,
                    "error_code": _classify_failure(message),
                    "message": (message or "")[:1200],
                    "accel_mode": get_accel_type().upper(),
                    "merge_mode": (merge_mode_request or get_highlight_merge_mode() or "").upper(),
                },
                ensure_ascii=False,
            ),
        })
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def validate_ai_data(project) -> tuple[bool, list]:
    """
    선택된 이미지 미디어에 ai_analysis가 100% 있는지 검사.
    반환: (valid, missing_media_ids)
    """
    if not project or not getattr(project, "media_files", None):
        return True, []
    selected_images = [
        mf for mf in project.media_files
        if getattr(mf, "file_type", None) == "image" and getattr(mf, "is_selected", True)
    ]
    if not selected_images:
        return True, []
    missing = [mf for mf in selected_images if not mf.ai_analysis]
    return (len(missing) == 0, [m.id for m in missing])


def _run_generate_task(project_id_str: str, merge_mode: str | None = None) -> None:
    """
    백그라운드에서 실행. project_type에 따라 영상 또는 앨범 설계도 생성.
    DB는 상태 갱신 시점에만 짧은 세션을 열고 닫는다.
    """
    try:
        project_id = UUID(project_id_str)
    except ValueError:
        logger.error("Invalid project_id: %s", project_id_str)
        return
    db = SessionLocal()
    try:
        update_project_status(db, project_id, "GENERATING")
        project = get_project(db, project_id)
        project_type = getattr(project, "project_type", None) or "video"
        task = get_latest_video_task_by_project(db, project_id)
        if task:
            mark_video_task_status(
                db,
                task.task_id,
                status="GENERATING",
                current_msg="고화질 영상을 굽는 중입니다. 거의 다 됐어요!",
            )
    finally:
        db.close()

    # 앨범 전용: VideoEngine 호출 금지. album_engine.build_layout() → album_layout.json만 생성
    if project_type == "album":
        logger.info("앨범 레이아웃 구성 중: project_id=%s (VideoEngine 미호출)", project_id)
        _run_album_task(project_id_str, project_id)
        return

    # 하이라이트 영상 전용: FlairyVideoEngine만 사용 (앨범 분기 위에서 return 되었음)
    db = SessionLocal()
    try:
        project = get_project(db, project_id)
        use_ai = _is_ai_mode(project) if project else False
        if use_ai and project:
            valid, missing_ids = validate_ai_data(project)
            if not valid:
                logger.error(
                    "Pre-render validation failed: AI data missing for media_ids=%s. Aborting.",
                    missing_ids,
                )
                update_project_status(db, project_id, "FAILED")
                task = get_latest_video_task_by_project(db, project_id)
                if task:
                    mark_video_task_status(
                        db,
                        task.task_id,
                        status="FAILED",
                        current_msg="작업 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
                    )
                return
    finally:
        db.close()
    logger.info(
        "영상 생성 시작: project_id=%s use_ai=%s merge_mode_request=%s",
        project_id,
        use_ai,
        merge_mode,
    )
    try:
        engine = FlairyVideoEngine(project_id, ROOT)
        final_path = engine.create_highlight(use_ai=use_ai, merge_mode=merge_mode)
        if final_path is None:
            db = SessionLocal()
            try:
                update_project_status(db, project_id, "FAILED")
            finally:
                db.close()
            logger.warning("영상 생성 실패 (클립 없음): project_id=%s", project_id)
            return
        output_path_str = str(Path("storage") / "final" / str(project_id) / "output.mp4")
        db = SessionLocal()
        try:
            task = get_latest_video_task_by_project(db, project_id)
            if task:
                mark_video_task_status(
                    db,
                    task.task_id,
                    status="GENERATING",
                    current_msg="마지막 디테일을 점검하고 있습니다...",
                )
            update_project_output_path(db, project_id, output_path_str)
            update_project_status(db, project_id, "COMPLETED")
            if task:
                mark_video_task_status(
                    db,
                    task.task_id,
                    status="COMPLETED",
                    current_msg="생성이 완료되었습니다.",
                )
                try:
                    send_task_completion_alert(task.task_id, task.notify_target)
                except Exception:
                    logger.exception("완료 알림 로그 처리 실패: task_id=%s", task.task_id)
        finally:
            db.close()
        logger.info("영상 생성 완료: %s", final_path)
    except Exception as e:
        logger.exception("영상 생성 중 오류: project_id=%s", project_id)
        err_msg = str(e)
        task_ref = None
        db = SessionLocal()
        try:
            update_project_status(db, project_id, "FAILED")
            task = get_latest_video_task_by_project(db, project_id)
            task_ref = task
            if task:
                mark_video_task_status(
                    db,
                    task.task_id,
                    status="FAILED",
                    current_msg="작업 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
                )
        except Exception:
            pass
        finally:
            db.close()
        try:
            _log_admin_render_failure(
                project_id=project_id,
                task_id=str(task_ref.task_id) if task_ref else None,
                message=err_msg,
                merge_mode_request=merge_mode,
            )
        except Exception:
            logger.exception("관리자 실패 감사로그 기록 실패: project_id=%s", project_id)
        raise


MIN_ALBUM_MEDIA_FILES = 5


def _run_album_task(project_id_str: str, project_id: UUID) -> None:
    """앨범 설계도 생성: order_index 정렬 미디어 → build_layout 또는 build_layout_ai → album_layout.json 저장."""
    try:
        db = SessionLocal()
        try:
            project = get_project(db, project_id)
        finally:
            db.close()
        if not project:
            logger.warning("앨범 프로젝트를 찾을 수 없음: project_id=%s", project_id)
            return
        media_files = getattr(project, "media_files", None) or []
        sorted_media = sorted(media_files, key=lambda m: getattr(m, "order_index", 0))
        if len(sorted_media) < MIN_ALBUM_MEDIA_FILES:
            logger.warning(
                "앨범: 미디어 %d개로 최소 %d개 미만 project_id=%s",
                len(sorted_media),
                MIN_ALBUM_MEDIA_FILES,
                project_id,
            )
            db = SessionLocal()
            try:
                update_project_status(db, project_id, "FAILED")
                task = get_latest_video_task_by_project(db, project_id)
                if task:
                    mark_video_task_status(
                        db,
                        task.task_id,
                        status="FAILED",
                        current_msg="작업 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
                    )
            finally:
                db.close()
            return
        title = getattr(project, "title", None) or "디지털 앨범"

        if _is_ai_mode(project):
            narrative_scores = getattr(project, "ai_narrative_order", None)
            if not isinstance(narrative_scores, dict):
                narrative_scores = None
            selected = AlbumAIService.preprocess_media_for_ai_mode(
                sorted_media,
                narrative_scores=narrative_scores,
                project_seed=str(project_id),
            )
            curated = []
            for m in selected:
                ai = getattr(m, "ai_analysis", None) or {}
                curated.append({
                    "file_path": getattr(m, "file_path", "") or "",
                    "file_type": getattr(m, "file_type", "image") or "image",
                    "width": getattr(m, "width", None),
                    "height": getattr(m, "height", None),
                    "ai_analysis": ai,
                    "media_id": getattr(m, "id", None),
                    "show_caption": bool(getattr(m, "show_caption", False)),
                    "caption_position": (getattr(m, "caption_position", "") or "").strip().lower(),
                    "emotional_caption": (getattr(m, "emotional_caption", "") or "").strip(),
                    "caption_delay_ms": int(getattr(m, "caption_delay_ms", 0) or 0),
                })
            if not curated:
                logger.warning("앨범 AI: 전처리 후 미디어 0건 (project_id=%s)", project_id)
            else:
                descriptions = [item["ai_analysis"].get("description") or "" for item in curated]
                lyrical_list = narrative_service.generate_lyrical_captions(descriptions)
                for i, item in enumerate(curated):
                    item["lyrical_caption"] = lyrical_list[i] if i < len(lyrical_list) else ""
                for item in curated:
                    ai = item.get("ai_analysis") or {}
                    dominant_hex = ai.get("dominant_color") or (
                        (ai.get("colors") or [None])[0] if ai.get("colors") else None
                    )
                    if not dominant_hex and item.get("file_path"):
                        abs_path = ROOT / item["file_path"]
                        dominant_hex = get_dominant_color_hex(abs_path)
                    item["dominant_color_hex"] = dominant_hex
                    if item.get("file_path"):
                        item["accent_color_hex"] = get_accent_color_hex(ROOT / item["file_path"])
            cover_collage_paths = None
            if curated and len(selected) >= 4:
                cover_three = AlbumAIService.select_cover_collage_candidates(
                    selected,
                    narrative_scores=narrative_scores,
                )
                if cover_three and len(cover_three) == 3:
                    cover_collage_paths = [getattr(m, "file_path", "") or "" for m in cover_three]
                    if len(set(cover_collage_paths)) != 3:
                        cover_collage_paths = None
            logger.info(
                "[Album] Calling build_layout_ai: curated_count=%s project_id=%s cover_collage=%s",
                len(curated),
                project_id,
                bool(cover_collage_paths),
            )
            layout = build_layout_ai(
                curated,
                title,
                project_id=str(project_id),
                cover_collage_paths=cover_collage_paths,
            )
            try:
                if layout and layout.get("pages"):
                    pages = layout.get("pages") or []
                    spread_count = sum(1 for p in pages if p and p.get("type") == "spread")
                    pages_len = len(pages)
                    n_cur = len(curated)
                    # 콜라주: 내지가 ordered 전체 n장 → ceil(n/2) spread. 비콜라주: 앞표지 1장 제외 → floor(n/2) spread.
                    expected_spreads = (
                        (n_cur + 1) // 2 if cover_collage_paths else n_cur // 2
                    )
                    logger.info(
                        "[Album] build_layout_ai result: pages=%d spreads=%d expected_spreads=%d (n=%d collage=%s)",
                        pages_len,
                        spread_count,
                        expected_spreads,
                        n_cur,
                        bool(cover_collage_paths),
                    )
            except Exception:
                logger.exception("[Album] build_layout_ai post-validate failed: project_id=%s", project_id)
        else:
            media_list = [
                {
                    "file_path": getattr(m, "file_path", "") or "",
                    "file_type": getattr(m, "file_type", "image") or "image",
                    "width": getattr(m, "width", None),
                    "height": getattr(m, "height", None),
                }
                for m in sorted_media
            ]
            layout = build_layout(media_list, title, project_id=str(project_id))
        emotion = get_dominant_emotion(getattr(project, "media_files", None) or []) if _is_ai_mode(project) else ""
        bgm_path = select_bgm_path(emotion, ROOT)
        layout["dominant_emotion"] = emotion or ""
        try:
            layout["bgm_path"] = str(bgm_path.relative_to(ROOT))
        except ValueError:
            layout["bgm_path"] = "static/audio/" + bgm_path.name
        final_dir = get_project_final_dir(project_id, base_dir=ROOT)
        save_album_layout(layout, final_dir)
        output_path_str = str(Path("storage") / "final" / str(project_id) / "album_layout.json")
        db = SessionLocal()
        try:
            update_project_output_path(db, project_id, output_path_str)
            update_project_status(db, project_id, "COMPLETED")
            task = get_latest_video_task_by_project(db, project_id)
            if task:
                mark_video_task_status(
                    db,
                    task.task_id,
                    status="COMPLETED",
                    current_msg="생성이 완료되었습니다.",
                )
                try:
                    send_task_completion_alert(task.task_id, task.notify_target)
                except Exception:
                    logger.exception("완료 알림 로그 처리 실패: task_id=%s", task.task_id)
        finally:
            db.close()
        logger.info("앨범 설계도 생성 완료: project_id=%s", project_id)
    except Exception:
        logger.exception("앨범 설계도 생성 중 오류: project_id=%s", project_id_str)
        db = SessionLocal()
        try:
            update_project_status(db, project_id, "FAILED")
            task = get_latest_video_task_by_project(db, project_id)
            if task:
                mark_video_task_status(
                    db,
                    task.task_id,
                    status="FAILED",
                    current_msg="작업 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
                )
        except Exception:
            pass
        finally:
            db.close()
        raise


def _ai_analysis_incomplete(project) -> bool:
    """AI 모드일 때 이미지 미디어 중 ai_analysis가 없는 항목이 하나라도 있으면 True."""
    if not project or not _is_ai_mode(project):
        return False
    image_files = [mf for mf in (project.media_files or []) if mf.file_type == "image"]
    if not image_files:
        return False
    return any(mf for mf in image_files if not mf.ai_analysis)


@router.get("/projects/{project_id}/media-readiness")
async def api_project_media_readiness(project_id: str):
    """프로젝트 미디어 트랜스코딩 준비 여부 (progress 페이지·외부 클라이언트용 JSON)."""
    try:
        uid = UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid project_id")
    db = SessionLocal()
    try:
        project = get_project(db, uid)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        r = get_project_media_readiness(db, uid)
        return {
            "project_id": project_id,
            "is_media_ready": r["is_media_ready"],
            "has_media_failure": r["has_media_failure"],
            "pending_count": r["pending_count"],
            "failed_count": r["failed_count"],
            "total_count": r["total_count"],
        }
    finally:
        db.close()


@router.post("/projects/{project_id}/generate")
async def api_generate(
    project_id: str,
    background_tasks: BackgroundTasks,
    merge_mode: str | None = None,
    debug_mode: bool = False,
    current_user=Depends(get_current_user_optional),
):
    """
    하이라이트 영상 생성 요청. AI 모드면 ai_analysis가 모두 채워진 뒤에만 렌더링 단계로 진입.
    """
    try:
        uid = UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid project_id")
    if debug_mode and not _is_debug_admin_email(getattr(current_user, "email", None)):
        logger.warning(
            "Unauthorized debug mode attempt by user: %s",
            getattr(current_user, "email", "Anonymous") if current_user else "Anonymous",
        )
        debug_mode = False
    db = SessionLocal()
    try:
        project = get_project(db, uid)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        readiness = get_project_media_readiness(db, uid)
        if not readiness["is_media_ready"]:
            if readiness["has_media_failure"]:
                raise HTTPException(
                    status_code=400,
                    detail="미디어 최적화에 실패한 파일이 있습니다. 파일을 확인 후 다시 시도해 주세요.",
                )
            raise HTTPException(
                status_code=409,
                detail="미디어 최적화가 완료될 때까지 잠시 후 다시 시도해 주세요.",
            )
        status = (project.status or "PENDING").upper()

        if _is_ai_mode(project) and _ai_analysis_incomplete(project):
            if status not in ("ANALYZING", "COMPOSING", "GENERATING", "COMPLETED"):
                update_project_status(db, uid, "ANALYZING")
                background_tasks.add_task(run_ai_analysis, uid)
                logger.info(
                    "AI 분석 단계: project_id=%s mode=ai (렌더링은 분석 완료 후 진행)",
                    project_id,
                )
                return {
                    "status": "accepted",
                    "message": "AI 분석을 시작합니다.",
                    "project_id": project_id,
                    "phase": "analyzing",
                }
            logger.info(
                "AI 분석 단계: project_id=%s mode=ai (분석 중, 렌더 대기)",
                project_id,
            )
            return {
                "status": "accepted",
                "message": "AI가 사진을 분석 중입니다.",
                "project_id": project_id,
                "phase": "analyzing",
            }
    finally:
        db.close()

    mode_val = _mode_value(project) if project else "rule_based"
    raw_mode = getattr(project, "mode", None) if project else None
    logger.info(
        "영상 렌더링 태스크 등록: project_id=%s mode=%s merge_mode_request=%s "
        "(raw type=%s value=%s, 다음 로그에서 use_ai 확인)",
        project_id,
        mode_val,
        merge_mode,
        type(raw_mode).__name__ if raw_mode is not None else "None",
        getattr(raw_mode, "value", raw_mode) if raw_mode is not None else None,
    )
    background_tasks.add_task(_run_generate_task, project_id, merge_mode)
    return {
        "status": "accepted",
        "message": "영상 생성이 시작되었습니다.",
        "project_id": project_id,
        "phase": "generating",
    }
