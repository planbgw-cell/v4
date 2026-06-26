"""
단일 HTML 포터블 앨범 export 컴파일러.
album_layout.json 풀 레이아웃 + 이미지 base64 내장 + 영상 스트리밍 URL 하이브리드.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

from PIL import Image

from app.config import get_public_base_url
from app.storage import get_project_final_dir, get_project_raw_dir, get_storage_root
from app.utils.media_processor import load_image_upright

logger = logging.getLogger(__name__)

ROOT = get_storage_root()
TEMPLATE_PATH = ROOT / "templates" / "portable_album_template.html"
PORTABLE_CSS_PATH = ROOT / "static" / "portable" / "portable-album.css"
PORTABLE_JS_PATH = ROOT / "static" / "portable" / "portable-album.js"

MAX_EXPORT_BYTES = 40 * 1024 * 1024
IMAGE_WIDTH_STEPS = (1080, 800, 640)
JPEG_QUALITY_STEPS = (82, 72, 60)

VIDEO_EXT = {".mp4", ".webm", ".mov", ".m4v"}


def _safe_export_basename(title: str, fallback: str) -> str:
    base = re.sub(r"[^\w\s가-힣\-]+", "", (title or fallback).strip())
    return re.sub(r"\s+", "_", base)[:80] or fallback


def safe_album_export_filename(title: str) -> str:
    """다운로드 attachment 및 HTML download 속성용 안전 파일명."""
    return f"{_safe_export_basename(title, 'flairy_album')}_album.html"


def safe_highlight_export_filename(title: str) -> str:
    """하이라이트 영상 다운로드용 안전 파일명."""
    return f"{_safe_export_basename(title, 'flairy_highlight')}_highlight.mp4"


def content_disposition_attachment(filename: str, *, default_name: str = "flairy_album.html") -> str:
    """RFC 5987 UTF-8 filename* + ASCII fallback."""
    safe = (filename or default_name).strip()
    default_ext = Path(default_name).suffix or ""
    if default_ext and not safe.lower().endswith(default_ext.lower()):
        safe = f"{safe}{default_ext}"
    ascii_fallback = re.sub(r"[^A-Za-z0-9.\-_]+", "_", safe).strip("._-")
    if not re.search(r"[A-Za-z0-9]", ascii_fallback or ""):
        ascii_fallback = Path(default_name).stem or "flairy"
    if default_ext and not ascii_fallback.lower().endswith(default_ext.lower()):
        ascii_fallback = f"{ascii_fallback}{default_ext}"
    encoded = quote(safe, safe="")
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'


def _normalize_storage_path(path: str | None) -> str:
    if not path:
        return ""
    return path.replace("\\", "/").strip()


def _filename_from_path(path: str) -> str:
    p = _normalize_storage_path(path)
    if not p:
        return ""
    return p.split("/")[-1]


def _is_video_path(path: str) -> bool:
    return Path(_filename_from_path(path)).suffix.lower() in VIDEO_EXT


def _collect_layout_paths(layout: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()

    def add(p: str | None) -> None:
        p = _normalize_storage_path(p)
        if p and p not in seen:
            seen.add(p)
            paths.append(p)

    for page in layout.get("pages") or []:
        if not page:
            continue
        add(page.get("left"))
        add(page.get("right"))
        for asset in page.get("cover_assets") or []:
            if isinstance(asset, dict):
                add(asset.get("path"))

    return paths


def _resolve_raw_file(project_id: UUID, storage_path: str) -> Path | None:
    fn = _filename_from_path(storage_path)
    if not fn:
        return None
    raw = get_project_raw_dir(project_id) / fn
    if raw.is_file():
        return raw
    return None


def _image_to_data_uri(src: Path, max_width: int, quality: int) -> str:
    img = load_image_upright(src)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    if w > max_width:
        new_h = max(1, round(h * (max_width / float(w))))
        img = img.resize((max_width, new_h), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _build_assets_and_streams(
    project_id: UUID,
    layout: dict[str, Any],
    public_base_url: str,
) -> tuple[dict[str, str], dict[str, str], int]:
    assets: dict[str, str] = {}
    streams: dict[str, str] = {}
    total_bytes = 0
    pid = str(project_id)
    base = public_base_url.rstrip("/")

    for path in _collect_layout_paths(layout):
        if _is_video_path(path):
            fn = _filename_from_path(path)
            if fn:
                streams[path] = f"{base}/raw/{pid}/{fn}"
            continue

        src = _resolve_raw_file(project_id, path)
        if not src or not src.is_file():
            logger.warning("Portable export: missing image %s project=%s", path, project_id)
            continue

        encoded = None
        for max_w in IMAGE_WIDTH_STEPS:
            for q in JPEG_QUALITY_STEPS:
                try:
                    uri = _image_to_data_uri(src, max_w, q)
                except Exception as e:  # noqa: BLE001
                    logger.warning("Encode failed %s: %s", src, e)
                    break
                size = len(uri)
                if total_bytes + size <= MAX_EXPORT_BYTES:
                    encoded = uri
                    total_bytes += size
                    break
                encoded = None
            if encoded:
                break

        if encoded:
            assets[path] = encoded
        else:
            logger.warning("Portable export: skipped oversized image %s", path)

    return assets, streams, total_bytes


def compile_portable_album_html(
    project_id: UUID,
    title: str,
    layout: dict[str, Any],
    public_base_url: str | None = None,
) -> tuple[str, str]:
    """Returns (html_content, attachment_filename)."""
    base_url = (public_base_url or get_public_base_url()).rstrip("/")
    assets, streams, _ = _build_assets_and_streams(project_id, layout, base_url)

    if not assets and not streams:
        raise ValueError("No embeddable assets found for portable album")

    flairy_data = {
        "title": title or "디지털 앨범",
        "projectId": str(project_id),
        "layout": layout,
        "assets": assets,
        "streams": streams,
        "offlineVideoHint": "영상 재생에는 인터넷 연결이 필요합니다.",
    }
    data_js = "const FlairyData = " + json.dumps(flairy_data, ensure_ascii=False) + ";"

    if not TEMPLATE_PATH.is_file():
        raise FileNotFoundError(f"Template missing: {TEMPLATE_PATH}")
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    css = ""
    if PORTABLE_CSS_PATH.is_file():
        css = PORTABLE_CSS_PATH.read_text(encoding="utf-8")

    js = ""
    if PORTABLE_JS_PATH.is_file():
        js = PORTABLE_JS_PATH.read_text(encoding="utf-8")

    html = template.replace("/* {{ INLINE_CSS }} */", css)
    html = html.replace("// {{ INLINE_JS }}", js)
    html = html.replace("// {{ ALBUM_DATA_INJECT }}", data_js)

    return html, safe_album_export_filename(title)


def load_album_layout(project_id: UUID) -> dict[str, Any]:
    layout_path = get_project_final_dir(project_id) / "album_layout.json"
    if not layout_path.is_file():
        raise FileNotFoundError("album_layout.json not found")
    with layout_path.open(encoding="utf-8") as f:
        return json.load(f)
