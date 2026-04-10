"""
AI 디지털 앨범 전처리 서비스.

Non-invasive 원칙:
- AlbumEngine 로직은 변경하지 않는다.
- AI 모드에서만 미디어 리스트를 큐레이션해 엔진 입력을 정제한다.
"""
from __future__ import annotations

import logging
import math
import random
import re
from typing import Any

from app.services import narrative_service

logger = logging.getLogger(__name__)

PHASH_SIMILARITY_THRESHOLD = 0.90
CAPTION_RATIO = 0.15


def _score_100(media: Any) -> float:
    """MediaFile(ai_analysis.score_100/score) -> 0~100 점수."""
    ai = getattr(media, "ai_analysis", None) or {}
    if not isinstance(ai, dict):
        return 0.0
    score100 = ai.get("score_100")
    if isinstance(score100, (int, float)):
        return float(score100)
    score01 = ai.get("score")
    if isinstance(score01, (int, float)):
        s = float(score01)
        if 0.0 <= s <= 1.0:
            return s * 100.0
        return max(0.0, min(100.0, s))
    return 0.0


def _get_phash_str(media: Any) -> str | None:
    """ai_analysis 내 pHash/phash 값을 문자열로 추출."""
    ai = getattr(media, "ai_analysis", None) or {}
    if not isinstance(ai, dict):
        return None
    v = ai.get("pHash")
    if v is None:
        v = ai.get("phash")
    if v is None:
        return None
    s = str(v).strip().lower()
    return s or None


def _to_bitstring(phash: str) -> str | None:
    """
    pHash 문자열을 비트 문자열로 정규화.
    - hex(일반적인 imagehash 포맷) 또는 0/1 문자열 지원
    """
    h = (phash or "").strip().lower()
    if not h:
        return None
    if all(c in "01" for c in h):
        return h
    try:
        n = int(h, 16)
    except ValueError:
        return None
    bits = len(h) * 4
    return format(n, f"0{bits}b")


def _phash_similarity(a: str | None, b: str | None) -> float:
    """pHash 유사도(0~1). 길이 다르면 짧은 쪽 기준으로 비교."""
    if not a or not b:
        return 0.0
    ba = _to_bitstring(a)
    bb = _to_bitstring(b)
    if not ba or not bb:
        return 0.0
    n = min(len(ba), len(bb))
    if n <= 0:
        return 0.0
    diff = sum(1 for i in range(n) if ba[i] != bb[i])
    return 1.0 - (diff / float(n))


def _subject_center_norm(media: Any) -> tuple[float, float] | None:
    """subject_box [ymin,xmin,ymax,xmax] 0~1000 → 중심 (cx, cy). 없으면 None."""
    ai = getattr(media, "ai_analysis", None) or {}
    if not isinstance(ai, dict):
        return None
    box = ai.get("subject_box")
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        ymin, xmin, ymax, xmax = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
    except (TypeError, ValueError):
        return None
    return ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0)


def _combined_rank_score(media: Any, narrative_scores: dict[str, float] | None) -> float:
    """서사 가중치 우선, 없으면 score_100."""
    mid = str(getattr(media, "id", "") or "")
    nw = 0.0
    if narrative_scores and mid:
        nw = float(narrative_scores.get(mid, 0.0))
    s100 = _score_100(media)
    return nw * 10.0 + s100 * 0.1


def _is_korean_text(text: str) -> bool:
    return bool(re.search(r"[가-힣]", text or ""))


def _safe_description(media: Any) -> str:
    ai = getattr(media, "ai_analysis", None) or {}
    if not isinstance(ai, dict):
        return ""
    return str(ai.get("description") or "").strip()


def _safe_emotion(media: Any) -> str:
    ai = getattr(media, "ai_analysis", None) or {}
    if not isinstance(ai, dict):
        return ""
    return str(ai.get("emotion") or "").strip()


def _subject_center_y_ratio(media: Any) -> float | None:
    ai = getattr(media, "ai_analysis", None) or {}
    if not isinstance(ai, dict):
        return None
    box = ai.get("subject_box")
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        ymin = float(box[0]) / 1000.0
        ymax = float(box[2]) / 1000.0
    except (TypeError, ValueError):
        return None
    cy = (ymin + ymax) / 2.0
    return max(0.0, min(1.0, cy))


def _build_emotional_caption(media: Any) -> str:
    desc = _safe_description(media)
    emo = _safe_emotion(media).lower()
    is_ko = _is_korean_text(desc)
    if is_ko:
        ko_by_emotion = {
            "joy": "작은 웃음, 큰 행복",
            "excited": "설렘이 번지는 순간",
            "romantic": "따뜻한 시선 한 장면",
            "peaceful": "고요한 오늘의 빛",
            "calm": "잔잔히 스민 온기",
            "sad": "조용히 안아준 하루",
        }
        text = ko_by_emotion.get(emo, "")
        if text:
            return text[:15]
        if desc:
            return desc[:15]
        return "오늘의 작은 기적"

    en_by_emotion = {
        "joy": "Softly in bloom",
        "excited": "A bright heartbeat",
        "romantic": "Held by warm light",
        "peaceful": "Quietly we glow",
        "calm": "A gentle pause",
        "sad": "Still, we stay close",
    }
    text_en = en_by_emotion.get(emo, "")
    if text_en:
        return text_en[:18]
    if desc:
        compact = " ".join(desc.split())[:18]
        return compact or "A tender frame"
    return "A tender frame"


def _apply_emotional_caption_metadata(
    ordered_media: list[Any],
    *,
    project_seed: str | None,
) -> None:
    if not ordered_media:
        return
    # 앞표지는 제외. 나머지 슬롯 중 15% 내외만 노출.
    eligible_indices = [i for i in range(1, len(ordered_media))]
    if not eligible_indices:
        return

    seed_text = (project_seed or "caption-seed").strip()
    rng = random.Random(seed_text)

    desired = int(round(len(eligible_indices) * CAPTION_RATIO))
    caption_count = max(1, min(len(eligible_indices), desired))
    picked = set(rng.sample(eligible_indices, caption_count))
    delay_pool = (520, 640, 780)

    for i, media in enumerate(ordered_media):
        show = i in picked
        setattr(media, "show_caption", show)
        if not show:
            setattr(media, "caption_position", "")
            setattr(media, "emotional_caption", "")
            setattr(media, "caption_delay_ms", 0)
            continue

        position = "top" if rng.random() < 0.5 else "bottom"
        cy = _subject_center_y_ratio(media)
        # 피사체 중심과 겹치기 쉬운 방향은 반대편으로 스왑.
        if cy is not None:
            if position == "top" and cy <= 0.35:
                position = "bottom"
            elif position == "bottom" and cy >= 0.65:
                position = "top"

        caption_text = _build_emotional_caption(media)
        setattr(media, "caption_position", position)
        setattr(media, "emotional_caption", caption_text)
        setattr(media, "caption_delay_ms", rng.choice(delay_pool))


def select_cover_collage_candidates(
    media_files: list[Any],
    *,
    narrative_scores: dict[str, float] | None = None,
    min_total_for_collage: int = 4,
) -> list[Any] | None:
    """
    커버 폴라로이드 콜라주용 이미지 3장 선정.
    - narrative_weight(맵) + score 보조 점수로 상위 후보를 고른 뒤,
      subject_box 중심 간 거리가 멀수록 겹침이 적다고 보고 탐욕적으로 3장 선택.
    - 전체 미디어가 min_total_for_collage 미만이면 None (단일 표지 폴백).
    """
    imgs = [m for m in media_files if (getattr(m, "file_type", "") or "").lower() == "image"]
    if len(imgs) < min_total_for_collage:
        return None

    ranked = sorted(
        imgs,
        key=lambda m: (-_combined_rank_score(m, narrative_scores), int(getattr(m, "order_index", 0))),
    )
    pool = ranked[: min(12, len(ranked))]

    def _mid(m: Any) -> Any:
        return getattr(m, "id", None)

    picked: list[Any] = []
    picked_ids: set[Any] = set()
    for _ in range(3):
        best_m: Any | None = None
        best_key: tuple[float, float] = (-1.0, -1.0)
        for cand in pool:
            if _mid(cand) in picked_ids:
                continue
            centers = [_subject_center_norm(x) for x in picked + [cand]]
            centers = [c for c in centers if c is not None]
            if len(centers) < 2:
                score = _combined_rank_score(cand, narrative_scores)
            else:
                min_d = min(
                    math.hypot(centers[-1][0] - c[0], centers[-1][1] - c[1])
                    for c in centers[:-1]
                    if c is not None
                )
                score = min_d * 100.0 + _combined_rank_score(cand, narrative_scores) * 0.01
            key = (score, _combined_rank_score(cand, narrative_scores))
            if key > best_key:
                best_key = key
                best_m = cand
        if best_m is not None:
            picked.append(best_m)
            picked_ids.add(_mid(best_m))

    if len(picked) < 3:
        picked = ranked[:3]

    out = picked[:3]
    logger.info(
        "[Cover Collage] selected media_ids=%s",
        [getattr(m, "id", None) for m in out],
    )
    return out


class AlbumAIService:
    @staticmethod
    def select_cover_collage_candidates(
        media_files: list[Any],
        *,
        narrative_scores: dict[str, float] | None = None,
    ) -> list[Any] | None:
        return select_cover_collage_candidates(media_files, narrative_scores=narrative_scores)

    @staticmethod
    def preprocess_media_for_ai_mode(
        media_files: list[Any],
        *,
        phash_similarity_threshold: float = PHASH_SIMILARITY_THRESHOLD,
        narrative_scores: dict[str, float] | None = None,
        project_seed: str | None = None,
    ) -> list[Any]:
        """
        AI 모드 전처리(이미지 dedup -> 서사 정렬 -> 표지 배치).
        반환: AlbumEngine에 전달 가능한 정렬된 MediaFile 리스트.
        """
        if not media_files:
            return []

        selected_candidates = [m for m in media_files if bool(getattr(m, "is_selected", True))]
        if not selected_candidates:
            return []

        # 비이미지는 dedup 대상에서 제외하고 그대로 유지(동영상 포함).
        image_candidates = [
            m for m in selected_candidates if (getattr(m, "file_type", "") or "").lower() == "image"
        ]
        non_image_candidates = [
            m for m in selected_candidates if (getattr(m, "file_type", "") or "").lower() != "image"
        ]

        # 이미지가 하나도 없으면(동영상만 있는 경우) 그대로 반환.
        if not image_candidates:
            out = sorted(non_image_candidates, key=lambda m: int(getattr(m, "order_index", 0)))
            logger.info("[Album AI] Image dedup skipped: no images, kept=%d", len(out))
            return out

        # 1) Deduplication (pHash 유사도 임계치 기반 그룹 중 최고점 1개 유지)
        n = len(image_candidates)
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        phashes = [_get_phash_str(m) for m in image_candidates]
        for i in range(n):
            if not phashes[i]:
                continue
            for j in range(i + 1, n):
                if not phashes[j]:
                    continue
                sim = _phash_similarity(phashes[i], phashes[j])
                if sim >= phash_similarity_threshold:
                    union(i, j)

        groups: dict[int, list[int]] = {}
        for idx in range(n):
            groups.setdefault(find(idx), []).append(idx)

        deduped_images: list[Any] = []
        for members in groups.values():
            best_idx = max(
                members,
                key=lambda k: (_score_100(image_candidates[k]), -int(getattr(image_candidates[k], "order_index", 0))),
            )
            for k in members:
                keep = (k == best_idx)
                setattr(image_candidates[k], "is_selected", keep)
            deduped_images.append(image_candidates[best_idx])

        deduped = sorted(
            deduped_images + non_image_candidates,
            key=lambda m: int(getattr(m, "order_index", 0)),
        )
        logger.info(
            "[Album AI] Deduplication applied: images_input=%d images_kept=%d non_images_kept=%d total_kept=%d threshold=%.2f",
            len(image_candidates),
            len(deduped_images),
            len(non_image_candidates),
            len(deduped),
            phash_similarity_threshold,
        )

        if not deduped:
            return []

        # 2) Narrative Sequencing (Option 2: score map 기반 정렬)
        score_map = narrative_scores
        if score_map is None:
            score_map = narrative_service.generate_highlight_narrative_scores(deduped)

        if score_map:
            deduped = sorted(
                deduped,
                key=lambda m: (
                    -float(score_map.get(str(getattr(m, "id", "")), 0.0)),
                    int(getattr(m, "order_index", 0)),
                ),
            )
            logger.info("[AI Sequencing] Narrative weights applied.")
        else:
            deduped = sorted(deduped, key=lambda m: int(getattr(m, "order_index", 0)))
            logger.info("[AI Sequencing] Fallback to order_index.")

        # 3) Cover Assignment (best -> front, second best -> back)
        if len(deduped) >= 1:
            by_score = sorted(
                deduped,
                key=lambda m: (_score_100(m), -int(getattr(m, "order_index", 0))),
                reverse=True,
            )
            best = by_score[0]
            ordered = [m for m in deduped if m is not best]
            ordered.insert(0, best)
            if len(by_score) >= 2 and ordered:
                second = by_score[1]
                ordered = [m for m in ordered if m is not second]
                ordered.append(second)
            deduped = ordered

        logger.info(
            "[Album AI] Cover assignment done: total=%d front_id=%s back_id=%s",
            len(deduped),
            getattr(deduped[0], "id", None) if deduped else None,
            getattr(deduped[-1], "id", None) if deduped else None,
        )
        _apply_emotional_caption_metadata(deduped, project_seed=project_seed)
        return deduped

