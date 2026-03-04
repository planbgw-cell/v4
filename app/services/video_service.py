"""
AI 분석 워크플로우: 프로젝트별 미디어 분석 실행, Curate(중복/저품질 제거), 상태 연동.
분석 완료 시 렌더링을 트리거하기 위해 generate API를 콜백으로 호출.
"""
import asyncio
import logging
import os
import urllib.request
from pathlib import Path
from uuid import UUID

import imagehash
from PIL import Image

from app.crud import (
    get_media_files_by_project,
    get_project,
    update_media_file_ai_analysis,
    update_media_file_dimensions,
    update_media_file_is_selected,
    update_project_ai_progress,
    update_project_status,
)
from app.database import SessionLocal
from app.services.ai_analyzer import FlairyAIAnalyzer

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent

# Curate: score 이하면 제외
SCORE_THRESHOLD = 0.25
# pHash 유사도 이상이면 중복으로 보고 한쪽은 제외 (0~1)
PHASH_SIMILARITY_THRESHOLD = 0.90


def _phash_similarity(h1: imagehash.ImageHash, h2: imagehash.ImageHash) -> float:
    """0~1, 1이 동일."""
    d = h1 - h2
    return 1.0 - (d / 64.0)


async def run_ai_analysis(project_id: UUID) -> None:
    """
    해당 프로젝트의 모든 이미지 MediaFile에 대해 Gemini 분석 실행 후 DB에 반영.
    분석 시작 시 상태를 ANALYZING으로 변경. Curate: 저득점·고유사 중복은 is_selected=False.
    경로: storage/raw/{project_id}/{filename}
    """
    db = SessionLocal()
    try:
        project = get_project(db, project_id)
        if not project:
            logger.warning("run_ai_analysis: 프로젝트 없음 %s", project_id)
            return
    finally:
        db.close()

    base_dir = ROOT
    media_files = []
    db = SessionLocal()
    try:
        media_files = get_media_files_by_project(db, project_id)
    finally:
        db.close()

    image_files = [mf for mf in media_files if mf.file_type == "image"]
    if not image_files:
        logger.info("run_ai_analysis: 이미지 없음 %s", project_id)
        db = SessionLocal()
        try:
            update_project_status(db, project_id, "PENDING")
        finally:
            db.close()
        return

    try:
        analyzer = FlairyAIAnalyzer()
    except ValueError as e:
        logger.warning("run_ai_analysis: Analyzer 초기화 실패 %s", e)
        db = SessionLocal()
        try:
            update_project_status(db, project_id, "PENDING")
        finally:
            db.close()
        return

    total = len(image_files)
    db = SessionLocal()
    try:
        update_project_ai_progress(db, project_id, total=total)
        update_project_status(db, project_id, "ANALYZING")
    finally:
        db.close()

    for idx, mf in enumerate(image_files):
        input_path = base_dir / mf.file_path
        try:
            if not input_path.is_file():
                logger.warning("run_ai_analysis: 파일 없음 %s", input_path)
            else:
                result = await asyncio.to_thread(analyzer.analyze_image, input_path)
                if result.get("upright_path"):
                    try:
                        result["upright_path"] = str(Path(result["upright_path"]).relative_to(base_dir))
                        logger.info("run_ai_analysis: upright_path 저장됨 %s", result["upright_path"])
                    except ValueError:
                        logger.warning("run_ai_analysis: upright_path 상대경로 변환 실패 (절대경로 유지) %s", result["upright_path"])
                db = SessionLocal()
                try:
                    update_media_file_ai_analysis(db, mf.id, result)
                    w_val, h_val = result.get("width"), result.get("height")
                    if w_val is not None and h_val is not None:
                        try:
                            update_media_file_dimensions(db, mf.id, int(w_val), int(h_val))
                        except Exception as dim_err:  # noqa: BLE001
                            logger.debug("media_file width/height 업데이트 스킵 (컬럼 없을 수 있음): %s", dim_err)
                finally:
                    db.close()
        except Exception as e:
            logger.warning("run_ai_analysis: 미디어 분석 실패 (건너뜀) %s: %s", mf.file_path, e)
        finally:
            db = SessionLocal()
            try:
                update_project_ai_progress(db, project_id, processed_increment=1)
            finally:
                db.close()
            current = idx + 1
            logger.info("Project %s: Analyzed %d/%d media", project_id, current, total)

    # 렌더링 전 유니크 리스트 확정: 중복 90% 이상은 is_selected=False로 제외.
    # 이후 엔진은 is_selected=True인 미디어만 사용(유니크 미디어 리스트).
    # Curate: score 낮은 항목 + pHash 유사도 90% 이상 중복
    db = SessionLocal()
    try:
        media_files = get_media_files_by_project(db, project_id)
        image_files = [mf for mf in media_files if mf.file_type == "image"]
    finally:
        db.close()

    # 1) score 임계값 이하 -> is_selected = False
    low_score_dropped = 0
    for mf in image_files:
        score = None
        if mf.ai_analysis and isinstance(mf.ai_analysis.get("score"), (int, float)):
            score = float(mf.ai_analysis["score"])
        if score is not None and score < SCORE_THRESHOLD:
            low_score_dropped += 1
            db = SessionLocal()
            try:
                update_media_file_is_selected(db, mf.id, False)
            finally:
                db.close()
    logger.debug("Curate: 저득점 제외 %d건 (score < %.2f)", low_score_dropped, SCORE_THRESHOLD)

    # 2) pHash 유사도 90% 이상 쌍: 한쪽만 남기기 (score 높은 쪽 유지)
    db = SessionLocal()
    try:
        image_files = [mf for mf in get_media_files_by_project(db, project_id) if mf.file_type == "image"]
    finally:
        db.close()

    hashes: list[tuple[int, imagehash.ImageHash, float]] = []  # (mf.id, hash, score)
    for mf in image_files:
        p = base_dir / mf.file_path
        if not p.is_file():
            continue
        try:
            with Image.open(p) as img:
                h = imagehash.phash(img)
        except Exception:
            continue
        score = 0.0
        if mf.ai_analysis and isinstance(mf.ai_analysis.get("score"), (int, float)):
            score = float(mf.ai_analysis["score"])
        hashes.append((mf.id, h, score))

    seen: set[int] = set()
    phash_pairs_dropped = 0
    for i, (id_a, h_a, score_a) in enumerate(hashes):
        if id_a in seen:
            continue
        for j, (id_b, h_b, score_b) in enumerate(hashes):
            if i >= j or id_b in seen:
                continue
            sim = _phash_similarity(h_a, h_b)
            if sim >= PHASH_SIMILARITY_THRESHOLD:
                drop_id = id_b if score_a >= score_b else id_a
                seen.add(drop_id)
                phash_pairs_dropped += 1
                db = SessionLocal()
                try:
                    update_media_file_is_selected(db, drop_id, False)
                finally:
                    db.close()
                if drop_id == id_a:
                    break
    logger.debug(
        "Curate: pHash 중복 제외 %d쌍 (유사도 >= %.0f%%)",
        phash_pairs_dropped,
        PHASH_SIMILARITY_THRESHOLD * 100,
    )

    db = SessionLocal()
    try:
        media_files = get_media_files_by_project(db, project_id)
        final_selected = len([mf for mf in media_files if mf.file_type == "image" and getattr(mf, "is_selected", True)])
        update_project_status(db, project_id, "COMPOSING")
    finally:
        db.close()
    logger.debug("Curate: 최종 선택 %d건 (이미지)", final_selected)
    logger.info("run_ai_analysis 완료: %s (이미지 %d건). 렌더링 트리거 호출.", project_id, len(image_files))

    def _trigger_generate() -> None:
        base = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        url = f"{base}/api/projects/{project_id}/generate"
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            logger.info("AI 분석 완료 후 generate 트리거 성공: %s", r.status)

    try:
        await asyncio.to_thread(_trigger_generate)
    except Exception as e:
        logger.warning("AI 분석 완료 후 generate 트리거 실패: %s", e)
