"""
Rule-based 디지털 앨범 페이지 레이아웃 엔진.
미디어 리스트를 받아 앞표지·내지(스프레드)·뒷표지로 구성된 album_layout.json 설계도를 생성한다.
AI 모드: build_layout_ai()로 1페이지 1미디어, 서사 재배치, focus_offset/ai_caption/bg_color_hex/theme_tone 지원.
"""
import colorsys
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ASPECT_RATIO = "9/16"
DEFAULT_CAPTION = "최고의 순간"

# AI 앨범: 하이라이트로 간주할 score_100 / emotion
AI_HIGHLIGHT_SCORE_MIN = 85
AI_HIGHLIGHT_EMOTIONS = ("Excited", "Joy")


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


def _compute_focus_offset(ai_analysis: dict | None) -> dict[str, str] | None:
    """
    subject_box [ymin, xmin, ymax, xmax] (0-1000) → object-position용 x%, y%.
    없으면 None (뷰어에서 center 유지).
    """
    if not ai_analysis or not isinstance(ai_analysis.get("subject_box"), (list, tuple)):
        return None
    box = ai_analysis["subject_box"]
    if len(box) != 4:
        return None
    try:
        ymin, xmin, ymax, xmax = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
    except (TypeError, ValueError):
        return None
    cx = (xmin + xmax) / 2.0
    cy = (ymin + ymax) / 2.0
    x_pct = round(cx / 10.0, 1)
    y_pct = round(cy / 10.0, 1)
    return {"x": f"{x_pct}%", "y": f"{y_pct}%"}


def _is_highlight(item: dict[str, Any]) -> bool:
    """score_100 >= 85 또는 emotion in (Excited, Joy)."""
    ai = item.get("ai_analysis") or {}
    score_100 = ai.get("score_100")
    if isinstance(score_100, (int, float)) and int(score_100) >= AI_HIGHLIGHT_SCORE_MIN:
        return True
    emotion = (ai.get("emotion") or "").strip()
    return emotion in AI_HIGHLIGHT_EMOTIONS


def _narrative_reorder(media_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    원래 순서 유지하되, 하이라이트를 n//4, n//2, 3*n//4에 배치하고 나머지는 시간순으로 채움.
    """
    if not media_list:
        return []
    n = len(media_list)
    ordered = list(media_list)
    highlight_indices = [i for i, m in enumerate(ordered) if _is_highlight(m)]
    target_slots = [n // 4, n // 2, (3 * n) // 4] if n >= 4 else []
    k = min(len(highlight_indices), len(target_slots))
    result: list[dict[str, Any] | None] = [None] * n
    for j in range(k):
        result[target_slots[j]] = ordered[highlight_indices[j]]
    used_highlight_indices = set(highlight_indices[:k])
    remaining_items = [ordered[i] for i in range(n) if i not in used_highlight_indices]
    remaining_positions = [i for i in range(n) if result[i] is None]
    for idx, pos in enumerate(remaining_positions):
        if idx < len(remaining_items):
            result[pos] = remaining_items[idx]
    return [x for x in result if x is not None]


def _parse_hex(hex_str: str | None) -> tuple[int, int, int] | None:
    """#RRGGBB 또는 RRGGBB → (r,g,b) 0-255. 실패 시 None."""
    if not hex_str or not isinstance(hex_str, str):
        return None
    h = re.sub(r"^#", "", hex_str.strip())
    if len(h) != 6 or not re.match(r"^[0-9A-Fa-f]+$", h):
        return None
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _soft_tint_hex(hex_str: str | None) -> str:
    """
    원색을 뮤트/파스텔 배경색으로 변환.
    채도 대폭 감소, 명도 상향 → #RRGGBB.
    """
    rgb = _parse_hex(hex_str) if hex_str else None
    if not rgb:
        return "#F5F5F5"
    r, g, b = (x / 255.0 for x in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    s = min(1.0, s * 0.22)
    v = max(0.92, min(1.0, v * 0.3 + 0.92))
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
    return f"#{int(r2*255):02x}{int(g2*255):02x}{int(b2*255):02x}"


def _theme_tone_from_hex(hex_str: str | None) -> str:
    """Hue 기준 warm(빨주노) / cool(초파보시안)."""
    rgb = _parse_hex(hex_str) if hex_str else None
    if not rgb:
        return "cool"
    r, g, b = (x / 255.0 for x in rgb)
    h, _s, _v = colorsys.rgb_to_hsv(r, g, b)
    # hue 0-360: 0=red, 60=yellow, 120=green, 180=cyan, 240=blue, 300=magenta
    if 35 <= h <= 70:
        return "warm"   # yellow
    if h < 35 or h > 320:
        return "warm"   # red / magenta-red
    if 70 < h <= 170:
        return "cool"   # green-cyan
    return "cool"       # blue, magenta


def _theme_tone_and_hint(emotion: str, tone: str) -> tuple[str, str | None]:
    """Emotion + tone → theme_tone, bg_tint_hint(선택)."""
    e = (emotion or "").strip().lower()
    if e in ("peaceful", "calm", "romantic") and tone == "warm":
        return ("warm", "beige")
    if e in ("excited", "joy", "energetic") and tone == "cool":
        return ("cool", "gray_blue")
    return (tone, None)


def _score_dict_item(item: dict[str, Any]) -> int:
    ai = item.get("ai_analysis") or {}
    s = ai.get("score_100")
    if s is None:
        return 0
    try:
        return int(s)
    except (TypeError, ValueError):
        return 0


def _style_for_curated_dict(
    item: dict[str, Any],
    median: int,
    *,
    include_caption: bool = True,
) -> dict[str, Any]:
    """curated 항목 dict → 뷰어용 styles (build_layout_ai 내부 style_at와 동일)."""
    w = item.get("width")
    h = item.get("height")
    base = _style_for_media(w, h)
    ai = item.get("ai_analysis") or {}
    focus = _compute_focus_offset(ai)
    if focus:
        base["focus_offset"] = focus
    emotion = (ai.get("emotion") or "").strip()
    if emotion:
        base["emotion"] = emotion
    lyrical = (item.get("lyrical_caption") or "").strip()
    s = _score_dict_item(item)
    show = s >= median
    if include_caption and show and lyrical:
        base["ai_caption"] = lyrical[:200]
    dominant_hex = item.get("dominant_color_hex") or ai.get("dominant_color")
    if not dominant_hex and isinstance(ai.get("colors"), (list, tuple)) and ai["colors"]:
        dominant_hex = ai["colors"][0]
    base["bg_color_hex"] = _soft_tint_hex(dominant_hex or "#cccccc")
    accent_hex = item.get("accent_color_hex") or ai.get("accent_color")
    if accent_hex:
        base["accent_color_hex"] = accent_hex
    tone = _theme_tone_from_hex(dominant_hex or "#888888")
    theme_tone, bg_hint = _theme_tone_and_hint(emotion, tone)
    base["theme_tone"] = theme_tone
    if bg_hint:
        base["bg_tint_hint"] = bg_hint
    return base


def build_layout_ai(
    curated_media_list: list[dict[str, Any]],
    project_title: str,
    project_id: str | None = None,
    english_title: str | None = None,
    cover_collage_paths: list[str] | None = None,
) -> dict[str, Any]:
    """
    AI 모드 전용: 1페이지 1미디어, 서사 재배치, focus_offset/ai_caption/emotion/bg_color_hex.
    curated_media_list 항목: file_path, file_type, width, height, ai_analysis, lyrical_caption(선택).
    english_title이 있으면 앞표지 title로 사용. score_100 >= median 인 슬롯에만 자막 노출.
    """
    logger.info(
        "[AlbumEngine] build_layout_ai entered: curated_count=%s project_id=%s title=%s",
        len(curated_media_list),
        project_id,
        (project_title or "")[:40],
    )
    out: dict[str, Any] = {
        "title": project_title or "디지털 앨범",
        "aspect_ratio": ASPECT_RATIO,
        "template_type": "standard",
        "pages": [],
    }
    if project_id is not None:
        out["project_id"] = project_id
    if english_title is not None:
        out["english_title"] = english_title

    ordered = _narrative_reorder(curated_media_list)
    if not ordered:
        logger.warning("AlbumEngine AI: 미디어 0개, 빈 pages 반환")
        return out

    n = len(ordered)
    scores = []
    for i in range(n):
        ai = ordered[i].get("ai_analysis") or {}
        s = ai.get("score_100")
        if s is not None:
            try:
                scores.append(int(s))
            except (TypeError, ValueError):
                pass
    median = sorted(scores)[len(scores) // 2] if scores else 0

    def path_at(i: int) -> str:
        return ordered[i].get("file_path") or ""

    def file_type_at(i: int) -> str:
        return (ordered[i].get("file_type") or "image").lower()

    def score_at(i: int) -> int:
        return _score_dict_item(ordered[i])

    def style_at(i: int) -> dict[str, Any]:
        return _style_for_curated_dict(ordered[i], median, include_caption=True)

    def caption_at(i: int) -> str:
        """score_100 >= median 일 때만 lyrical_caption 반환."""
        if score_at(i) < median:
            return ""
        return (ordered[i].get("lyrical_caption") or "").strip()[:200]

    def caption_for_item(item: dict[str, Any]) -> str:
        if _score_dict_item(item) < median:
            return ""
        return (item.get("lyrical_caption") or "").strip()[:200]

    cover_title = (english_title or project_title or "디지털 앨범").strip()

    use_collage = False
    interior: list[dict[str, Any]] = []
    cover_assets_out: list[dict[str, Any]] = []
    best_item: dict[str, Any] | None = None

    if (
        cover_collage_paths is not None
        and len(cover_collage_paths) == 3
        and len(set(cover_collage_paths)) == 3
        and n >= 4
    ):
        by_path: dict[str, dict[str, Any]] = {}
        for x in ordered:
            fp = (x.get("file_path") or "").strip()
            if fp:
                by_path[fp] = x
        cover_items = [by_path[p] for p in cover_collage_paths if p in by_path]
        if len(cover_items) == 3:
            # 내지: 서사 순서 ordered 전체 (중복 허용 정책)
            interior = list(ordered)
            sorted_by_score = sorted(cover_items, key=_score_dict_item, reverse=True)
            best_item, mid_item, low_item = sorted_by_score[0], sorted_by_score[1], sorted_by_score[2]
            layout_order = [mid_item, low_item, best_item]
            for asset in layout_order:
                row: dict[str, Any] = {
                    "path": asset.get("file_path") or "",
                    "file_type": (asset.get("file_type") or "image").lower(),
                    "styles": _style_for_curated_dict(asset, median, include_caption=False),
                }
                mid_id = asset.get("media_id")
                if mid_id is not None:
                    row["media_id"] = str(mid_id)
                cover_assets_out.append(row)
            use_collage = True

    if use_collage and best_item is not None:
        logger.info(
            "[AlbumEngine] build_layout_ai: cover collage (3) + interior spreads=%d (sequential pair fill)",
            len(interior),
        )
        out["pages"].append({
            "type": "front",
            "template_type": "standard",
            "layout_type": "collage",
            "left": None,
            "right": best_item.get("file_path") or "",
            "title": cover_title,
            "styles": {
                "left": None,
                "right": _style_for_curated_dict(best_item, median, include_caption=False),
            },
            "file_types": {"left": None, "right": (best_item.get("file_type") or "image").lower()},
            "cover_assets": cover_assets_out,
        })
        # Viewer(PC) 매핑은 pages[i].right(front) + pages[i+1].left(back)를 사용하므로,
        # 콜라주 이후 spread 페이지는 left/right를 "페어로" 채워야 특정 페이지가 null로 비지 않습니다.
        for k in range(0, len(interior), 2):
            left_item = interior[k]
            right_item = interior[k + 1] if k + 1 < len(interior) else None

            left_path = left_item.get("file_path") or ""
            left_ft = (left_item.get("file_type") or "image").lower()
            left_st = _style_for_curated_dict(left_item, median, include_caption=True)
            left_cap = caption_for_item(left_item)

            if right_item is None:
                out["pages"].append({
                    "type": "spread",
                    "template_type": "standard",
                    "left": left_path,
                    "right": None,
                    "styles": {"left": left_st, "right": None},
                    "captions": {"left": left_cap, "right": ""},
                    "file_types": {"left": left_ft, "right": None},
                })
            else:
                right_path = right_item.get("file_path") or ""
                right_ft = (right_item.get("file_type") or "image").lower()
                right_st = _style_for_curated_dict(right_item, median, include_caption=True)
                right_cap = caption_for_item(right_item)
                out["pages"].append({
                    "type": "spread",
                    "template_type": "standard",
                    "left": left_path,
                    "right": right_path,
                    "styles": {"left": left_st, "right": right_st},
                    "captions": {"left": left_cap, "right": right_cap},
                    "file_types": {"left": left_ft, "right": right_ft},
                })
    else:
        # 앞표지: right=첫 미디어 (단일 표지)
        out["pages"].append({
            "type": "front",
            "template_type": "standard",
            "left": None,
            "right": path_at(0),
            "title": cover_title,
            "styles": {"left": None, "right": style_at(0)},
            "file_types": {"left": None, "right": file_type_at(0)},
        })

        # 내지: 연속 두 장씩 한 spread에 left/right 동시 배치 (콜라주 분기와 동일, PC 썸네일·뷰어와 일치)
        logger.info(
            "[AlbumEngine] build_layout_ai: standard cover + interior sequential pair fill (n=%d)",
            n,
        )
        for k in range(1, n, 2):
            left_i = k
            right_i = k + 1 if k + 1 < n else None
            left_cap = caption_at(left_i)
            left_path = path_at(left_i)
            left_ft = file_type_at(left_i)
            left_st = style_at(left_i)
            if right_i is None:
                out["pages"].append({
                    "type": "spread",
                    "template_type": "standard",
                    "left": left_path,
                    "right": None,
                    "styles": {"left": left_st, "right": None},
                    "captions": {"left": left_cap, "right": ""},
                    "file_types": {"left": left_ft, "right": None},
                })
            else:
                right_cap = caption_at(right_i)
                right_path = path_at(right_i)
                right_ft = file_type_at(right_i)
                right_st = style_at(right_i)
                out["pages"].append({
                    "type": "spread",
                    "template_type": "standard",
                    "left": left_path,
                    "right": right_path,
                    "styles": {"left": left_st, "right": right_st},
                    "captions": {"left": left_cap, "right": right_cap},
                    "file_types": {"left": left_ft, "right": right_ft},
                })

    # 뒷표지: left=null (프리미엄 뒷표지 디자인만)
    out["pages"].append({
        "type": "back",
        "template_type": "standard",
        "left": None,
        "right": None,
        "caption": DEFAULT_CAPTION,
        "styles": {"left": None, "right": None},
        "file_types": {"left": None, "right": None},
    })

    return out


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
        "template_type": "standard",
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
        "template_type": "standard",
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
                "template_type": "standard",
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
        "template_type": "standard",
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
