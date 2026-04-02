"""
AI 디지털 앨범 전처리 서비스.

Non-invasive 원칙:
- AlbumEngine 로직은 변경하지 않는다.
- AI 모드에서만 미디어 리스트를 큐레이션해 엔진 입력을 정제한다.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services import narrative_service

logger = logging.getLogger(__name__)

PHASH_SIMILARITY_THRESHOLD = 0.90


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


class AlbumAIService:
    @staticmethod
    def preprocess_media_for_ai_mode(
        media_files: list[Any],
        *,
        score_threshold: int = 60,
        phash_similarity_threshold: float = PHASH_SIMILARITY_THRESHOLD,
        narrative_scores: dict[str, float] | None = None,
    ) -> list[Any]:
        """
        AI 모드 전처리(중복 제거 -> 서사 정렬 -> 표지 배치).
        반환: AlbumEngine에 전달 가능한 정렬된 MediaFile 리스트.
        """
        if not media_files:
            return []

        image_only = [m for m in media_files if (getattr(m, "file_type", "") or "").lower() == "image"]
        if not image_only:
            return []

        # 0) 사전 필터: is_selected + score_threshold
        base_candidates: list[Any] = []
        for m in image_only:
            selected = bool(getattr(m, "is_selected", True))
            keep = selected and (_score_100(m) >= float(score_threshold))
            setattr(m, "is_selected", keep)
            if keep:
                base_candidates.append(m)

        if not base_candidates:
            return []

        # 1) Deduplication (pHash 유사도 임계치 기반 그룹 중 최고점 1개 유지)
        n = len(base_candidates)
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

        phashes = [_get_phash_str(m) for m in base_candidates]
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

        deduped: list[Any] = []
        for members in groups.values():
            best_idx = max(
                members,
                key=lambda k: (_score_100(base_candidates[k]), -int(getattr(base_candidates[k], "order_index", 0))),
            )
            for k in members:
                keep = (k == best_idx)
                setattr(base_candidates[k], "is_selected", keep)
            deduped.append(base_candidates[best_idx])

        deduped = sorted(deduped, key=lambda m: int(getattr(m, "order_index", 0)))
        logger.info(
            "[Album AI] Deduplication applied: input=%d kept=%d threshold=%.2f",
            len(base_candidates),
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
        return deduped

