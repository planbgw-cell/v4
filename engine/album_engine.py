"""
Rule-based 디지털 앨범 페이지 레이아웃 엔진.
미디어 리스트를 받아 앞표지·내지(스프레드)·뒷표지로 구성된 album_layout.json 설계도를 생성한다.
"""
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ASPECT_RATIO = "9/16"
DEFAULT_CAPTION = "최고의 순간"


def _is_landscape(width: int | None, height: int | None) -> bool:
    """가로 사진 여부. width/height가 없으면 False(블러 미적용)."""
    if width is None or height is None or height <= 0:
        return False
    return width > height


def _style_for_media(width: int | None, height: int | None) -> dict[str, Any]:
    """9:16 비율 맞추기용 스타일. 가로 사진이면 needs_blur 및 object_fit 포함."""
    if _is_landscape(width, height):
        return {
            "needs_blur": True,
            "object_fit": "contain",
            "background_blur": True,
        }
    return {}


def build_layout(
    media_list: list[dict[str, Any]],
    project_title: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    """
    미디어 리스트(순서 보장)와 프로젝트 타이틀로 앨범 설계도 생성.
    media_list 항목: file_path (str), file_type (str), width (int|None), height (int|None).
    반환: project_id, title, aspect_ratio, pages (front → spreads → back).
    """
    out: dict[str, Any] = {
        "title": project_title or "디지털 앨범",
        "aspect_ratio": ASPECT_RATIO,
        "pages": [],
    }
    if project_id is not None:
        out["project_id"] = project_id

    if not media_list:
        logger.warning("AlbumEngine: 미디어 0개, 빈 pages 반환")
        return out

    n = len(media_list)

    def path_at(i: int) -> str:
        return media_list[i].get("file_path") or ""

    def file_type_at(i: int) -> str:
        return (media_list[i].get("file_type") or "image").lower()

    def style_at(i: int) -> dict:
        w = media_list[i].get("width")
        h = media_list[i].get("height")
        return _style_for_media(w, h)

    # 앞표지: 스프레드 규격. left=빈 공간, right=표지 미디어 (물리적 사이즈 일정)
    out["pages"].append({
        "type": "front",
        "left": None,
        "right": path_at(0),
        "title": project_title or "디지털 앨범",
        "styles": {"left": None, "right": style_at(0)},
        "file_types": {"left": None, "right": file_type_at(0)},
    })

    # 내지(스프레드): 미디어 2개 이상일 때만. (0,1), (2,3), ... 마지막이 홀수면 (N-1, null)
    if n >= 2:
        i = 0
        while i < n:
            left_path = path_at(i)
            left_style = style_at(i)
            right_path: str | None = None
            right_style: dict | None = None
            right_caption = ""
            if i + 1 < n:
                right_path = path_at(i + 1)
                right_style = style_at(i + 1)
                right_caption = DEFAULT_CAPTION
            out["pages"].append({
                "type": "spread",
                "left": left_path,
                "right": right_path,
                "styles": {"left": left_style, "right": right_style},
                "captions": {"left": DEFAULT_CAPTION, "right": right_caption},
                "file_types": {"left": file_type_at(i), "right": file_type_at(i + 1) if i + 1 < n else None},
            })
            i += 2

    # 뒷표지: 스프레드 규격. left=마지막 미디어, right=빈 공간
    out["pages"].append({
        "type": "back",
        "left": path_at(n - 1),
        "right": None,
        "caption": DEFAULT_CAPTION,
        "styles": {"left": style_at(n - 1), "right": None},
        "file_types": {"left": file_type_at(n - 1), "right": None},
    })

    return out


def save_album_layout(layout: dict[str, Any], final_dir: Path) -> Path:
    """설계도를 final_dir/album_layout.json으로 저장. UTF-8, indent 2."""
    final_dir.mkdir(parents=True, exist_ok=True)
    out_path = final_dir / "album_layout.json"
    out_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("앨범 설계도 저장: %s", out_path)
    return out_path
