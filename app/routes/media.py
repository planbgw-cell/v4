"""
앨범 뷰어용 리사이즈 이미지 서빙 (?w= 가로 최대, 디스크 캐시).
/raw StaticFiles와 분리해 쿼리 기반 리사이즈를 처리한다.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from PIL import Image

from app.storage import get_project_final_dir, get_project_raw_dir, get_storage_root
from app.utils.media_processor import IMAGE_EXTENSIONS, load_image_upright

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/media", tags=["media"])

# 가로 최대(모바일 상한과 동일)
_MAX_WIDTH = 1080
_DEFAULT_WIDTH = 1080

# 리사이즈 대상(원본 확장자)
_ALLOWED_SUFFIX = {ext.lower() for ext in IMAGE_EXTENSIONS}


_COLLAGE_SHARE_NAMES = ("collage_front.jpg", "collage_front.png", "collage_frame.png")


def _resolve_image_source(project_id: UUID, filename: str) -> Path | None:
    """원본 이미지 경로: raw 우선, AI 공유 표지는 final 디렉터리도 조회."""
    raw_dir = get_project_raw_dir(project_id)
    src = raw_dir / filename
    if src.is_file():
        return src
    if filename not in _COLLAGE_SHARE_NAMES:
        return None
    final_dir = get_project_final_dir(project_id)
    for name in _COLLAGE_SHARE_NAMES:
        candidate = final_dir / name
        if candidate.is_file():
            return candidate
    return None


def _safe_single_filename(name: str) -> bool:
    if not name or not name.strip():
        return False
    p = Path(name)
    if p.name != name or p.stem == "":
        return False
    if ".." in name or "/" in name or "\\" in name:
        return False
    return True


def _thumbnail_cache_path(project_id: UUID, filename: str, width: int) -> Path:
    root = get_storage_root()
    return root / "storage" / "thumbnails" / str(project_id) / f"w{width}" / f"{filename}.jpg"


def _resize_image_to_max_width(src_path: Path, max_width: int) -> Image.Image:
    img = load_image_upright(src_path)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        background = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        img = background
    elif img.mode == "P":
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    if w <= max_width:
        return img
    new_h = max(1, round(h * (max_width / float(w))))
    return img.resize((max_width, new_h), Image.Resampling.LANCZOS)


def _write_jpeg_atomic(img: Image.Image, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(suffix=".jpg", dir=str(dest.parent))
    tmp = Path(tmp_path)
    try:
        os.close(fd)
        img.save(tmp, format="JPEG", quality=85, optimize=True)
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


@router.get("/image/{project_id}/{filename}")
def serve_resized_album_image(
    project_id: UUID,
    filename: str,
    w: int = Query(default=_DEFAULT_WIDTH, ge=1, le=_MAX_WIDTH),
) -> FileResponse:
    if not _safe_single_filename(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIX:
        raise HTTPException(status_code=404, detail="Not an image file")

    raw_dir = get_project_raw_dir(project_id)
    src = _resolve_image_source(project_id, filename)
    raw_dir_exists = os.path.exists(str(raw_dir))
    src_exists = bool(src and src.is_file())
    if src is None or not src.is_file():
        logger.warning(
            "Album image source missing project_id=%s filename=%s raw_dir=%s raw_dir_exists=%s src_exists=%s",
            project_id,
            filename,
            raw_dir,
            raw_dir_exists,
            src_exists,
        )
        raise HTTPException(status_code=404, detail="Source not found")

    target_w = min(int(w), _MAX_WIDTH)
    cache_path = _thumbnail_cache_path(project_id, filename, target_w)
    try:
        os.makedirs(str(cache_path.parent), exist_ok=True)
    except OSError as e:
        logger.warning("Thumbnail cache dir create failed path=%s: %s", cache_path.parent, e)
        raise HTTPException(status_code=500, detail="Cache directory unavailable") from e

    if cache_path.is_file():
        return FileResponse(
            cache_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    try:
        resized = _resize_image_to_max_width(src, target_w)
    except Exception as e:  # noqa: BLE001
        logger.warning("Image resize failed project=%s file=%s: %s", project_id, filename, e)
        raise HTTPException(status_code=415, detail="Could not decode or resize image") from e

    try:
        _write_jpeg_atomic(resized, cache_path)
    except OSError as e:
        logger.warning("Thumbnail cache write failed: %s", e)
        raise HTTPException(status_code=500, detail="Cache write failed") from e

    if not cache_path.is_file():
        raise HTTPException(status_code=500, detail="Cache missing after write")

    return FileResponse(
        cache_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
