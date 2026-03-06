"""
하이라이트 영상 생성 API. AI 모드일 때는 ai_analysis가 모두 채워진 뒤에만 렌더링 시작.

🛡️ [Rule Set] Flairy v4.0 경로/프로세스 격리: project_type이 'album'이면 VideoEngine 호출 금지.
   album → album_engine.build_layout() / album_layout.json만 생성.
   video → FlairyVideoEngine.create_highlight() 만 사용.
"""
import logging
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.crud import get_project, update_project_output_path, update_project_status
from app.database import SessionLocal
from app.storage import get_project_final_dir
from app.services.video_service import run_ai_analysis
from engine.album_engine import build_layout, save_album_layout
from engine.video_engine import FlairyVideoEngine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["generate"])
ROOT = Path(__file__).resolve().parent.parent.parent


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


def _run_generate_task(project_id_str: str) -> None:
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
    finally:
        db.close()

    # 앨범 전용: VideoEngine 호출 금지. album_engine.build_layout() → album_layout.json만 생성
    if project_type == "album":
        logger.info("앨범 레이아웃 구성 중: project_id=%s (VideoEngine 미호출)", project_id)
        _run_album_task(project_id_str, project_id, project)
        return

    # 하이라이트 영상 전용: FlairyVideoEngine만 사용 (앨범 분기 위에서 return 되었음)
    use_ai = _is_ai_mode(project) if project else False
    if use_ai and project:
        valid, missing_ids = validate_ai_data(project)
        if not valid:
            logger.error(
                "Pre-render validation failed: AI data missing for media_ids=%s. Aborting.",
                missing_ids,
            )
            db = SessionLocal()
            try:
                update_project_status(db, project_id, "FAILED")
            finally:
                db.close()
            return
    logger.info("영상 생성 시작: project_id=%s use_ai=%s", project_id, use_ai)
    try:
        engine = FlairyVideoEngine(project_id, ROOT)
        final_path = engine.create_highlight(use_ai=use_ai)
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
            update_project_output_path(db, project_id, output_path_str)
            update_project_status(db, project_id, "COMPLETED")
        finally:
            db.close()
        logger.info("영상 생성 완료: %s", final_path)
    except Exception:
        logger.exception("영상 생성 중 오류: project_id=%s", project_id)
        db = SessionLocal()
        try:
            update_project_status(db, project_id, "FAILED")
        except Exception:
            pass
        finally:
            db.close()
        raise


def _run_album_task(project_id_str: str, project_id: UUID, project) -> None:
    """앨범 설계도 생성: order_index 정렬 미디어 → build_layout → album_layout.json 저장."""
    try:
        media_files = getattr(project, "media_files", None) or []
        sorted_media = sorted(media_files, key=lambda m: getattr(m, "order_index", 0))
        media_list = [
            {
                "file_path": getattr(m, "file_path", "") or "",
                "file_type": getattr(m, "file_type", "image") or "image",
                "width": getattr(m, "width", None),
                "height": getattr(m, "height", None),
            }
            for m in sorted_media
        ]
        title = getattr(project, "title", None) or "디지털 앨범"
        layout = build_layout(media_list, title, project_id=str(project_id))
        final_dir = get_project_final_dir(project_id, base_dir=ROOT)
        save_album_layout(layout, final_dir)
        output_path_str = str(Path("storage") / "final" / str(project_id) / "album_layout.json")
        db = SessionLocal()
        try:
            update_project_output_path(db, project_id, output_path_str)
            update_project_status(db, project_id, "COMPLETED")
        finally:
            db.close()
        logger.info("앨범 설계도 생성 완료: project_id=%s", project_id)
    except Exception:
        logger.exception("앨범 설계도 생성 중 오류: project_id=%s", project_id_str)
        db = SessionLocal()
        try:
            update_project_status(db, project_id, "FAILED")
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


@router.post("/projects/{project_id}/generate")
async def api_generate(project_id: str, background_tasks: BackgroundTasks):
    """
    하이라이트 영상 생성 요청. AI 모드면 ai_analysis가 모두 채워진 뒤에만 렌더링 단계로 진입.
    """
    try:
        uid = UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid project_id")
    db = SessionLocal()
    try:
        project = get_project(db, uid)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
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
        "영상 렌더링 태스크 등록: project_id=%s mode=%s (raw type=%s value=%s, 다음 로그에서 use_ai 확인)",
        project_id,
        mode_val,
        type(raw_mode).__name__ if raw_mode is not None else "None",
        getattr(raw_mode, "value", raw_mode) if raw_mode is not None else None,
    )
    background_tasks.add_task(_run_generate_task, project_id)
    return {
        "status": "accepted",
        "message": "영상 생성이 시작되었습니다.",
        "project_id": project_id,
        "phase": "generating",
    }
