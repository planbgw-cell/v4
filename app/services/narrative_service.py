"""
앨범 감성 스토리텔링: Gemini 텍스트 전용 호출.
- 앨범 영문 감성 타이틀 생성
- description → 서정적 영문 자막(lyrical caption) 변환
- 하이라이트: 미디어별 서사 가중치 narrative_weight (0~10) JSON 맵
"""
import json
import logging
import os
import re
import time

logger = logging.getLogger(__name__)


try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None  # type: ignore[misc, assignment]
    genai_types = None  # type: ignore[misc, assignment]

GEMINI_MODEL = "gemini-2.5-flash"
MAX_RETRIES = 3
INITIAL_BACKOFF_SEC = 2.0

ALBUM_TITLE_PROMPT = """Given these short photo descriptions (one per line), suggest a single poetic English title that captures the mood of this album.
Reply with only the title phrase, no quotes or explanation. Example: Whispers of the Emerald Sea.
Keep it under 60 characters.

Descriptions:
"""
HIGHLIGHT_NARRATIVE_SCORING_PROMPT = """You are a film editor scoring clips for a vertical 9:16 highlight video.
Each item has: id (integer), type (image or video), emotion, summary (short scene description).

For EACH item id, assign a single number narrative_weight from 0.0 to 10.0 meaning "how important this clip is
for the overall story arc" (opening hook, emotional peaks, resolution moments score higher; filler lower).
You may give similar scores to multiple items. Do not output ordering lists.

Output ONLY one JSON object (no markdown fences), keys MUST be string decimal ids, values MUST be numbers:
{"965": 9.2, "966": 7.1, ...}

Include an entry for every id listed below. Keys must match these ids as strings.

Items (JSON array):
"""

LYRICAL_CAPTION_PROMPT = """Convert each of the following short photo descriptions into a single short lyrical English caption for a photo album.
One line per caption, poetic and evocative. Max 60 chars each.
Reply with exactly one caption per line, in the same order. No numbering or bullets.

Descriptions:
"""


def _get_client():
    if genai is None or genai_types is None:
        raise ValueError("google-genai 패키지가 필요합니다. pip install google-genai")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")
    return genai.Client(api_key=api_key)


def _call_gemini_text(prompt: str, *, max_output_tokens: int = 1024) -> str:
    """텍스트만으로 Gemini 호출. 재시도·fallback."""
    client = _get_client()
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.5,
                    max_output_tokens=max_output_tokens,
                ),
            )
            if response and getattr(response, "text", None):
                return (response.text or "").strip()
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(INITIAL_BACKOFF_SEC * (2**attempt))
    logger.warning("Gemini text call failed after %d retries: %s", MAX_RETRIES, last_err)
    return ""


def generate_album_title_english(descriptions: list[str], fallback: str = "Our Story") -> str:
    """
    프로젝트 전체 description 합본으로 서정적인 영문 앨범 제목 하나 생성.
    실패 시 fallback 반환.
    """
    if not descriptions:
        return fallback
    text = "\n".join((d or "").strip()[:200] for d in descriptions if (d or "").strip())[:3000]
    if not text.strip():
        return fallback
    prompt = ALBUM_TITLE_PROMPT + text
    result = _call_gemini_text(prompt)
    if not result:
        return fallback
    result = re.sub(r'^["\']|["\']\s*$', "", result.strip())
    return result[:80] if result else fallback


def _parse_highlight_order_json(text: str) -> dict[str, float] | None:
    """
    Gemini 응답에서 서사 가중치 맵 파싱. 순수 JSON: {"101": 9.5, "102": 4.0}
    (구버전 {"order":[...]} 는 더 이상 사용하지 않음.)
    """
    if not text:
        return None
    raw = text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```\s*$", "", raw).strip()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(obj, dict):
        return None
    out: dict[str, float] = {}
    for k, v in obj.items():
        try:
            sk = str(k).strip()
            int(sk)  # validate numeric id key
            fv = float(v)
            out[sk] = max(0.0, min(10.0, fv))
        except (TypeError, ValueError):
            continue
    return out if out else None


def _media_file_to_narrative_payload(mf) -> dict:
    """MediaFile → Gemini용 최소 필드 (ORM 속성만 사용)."""
    aid = getattr(mf, "ai_analysis", None) or {}
    if not isinstance(aid, dict):
        aid = {}
    summary = (aid.get("summary") or aid.get("description") or "").strip()[:200]
    emotion = (aid.get("emotion") or "").strip()[:80]
    return {
        "id": int(mf.id),
        "type": str(getattr(mf, "file_type", "image") or "image"),
        "emotion": emotion or "unknown",
        "summary": summary or "(no description)",
    }


def reorder_by_ai_scores(media_items: list, ai_scores: dict[str, float]) -> list:
    """
    narrative_weight 내림차순 정렬. 미입력 id는 0.0. 동점 시 order_index 오름차순.
    """
    return sorted(
        media_items,
        key=lambda x: (-float(ai_scores.get(str(x.id), 0.0)), x.order_index),
    )


def reorder_by_ai_narrative(media_items: list, ai_scores: dict[str, float]) -> list:
    """
    하이브리드 서사 재배치.
    - Intro: 고품질 + 비인물 중심(풍경/단체 느낌) 우선
    - Climax: joy/surprise 계열 + 인물 중심 우선
    - Outro: peaceful/calm/nostalgic/sad 계열 우선
    """
    if not media_items:
        return []
    if len(media_items) <= 2:
        return reorder_by_ai_scores(media_items, ai_scores)

    climax_emotions = {"joy", "surprise", "excited", "happy"}
    outro_emotions = {"peaceful", "calm", "nostalgic", "sad", "melancholy"}

    enriched = []
    for m in media_items:
        aid = getattr(m, "ai_analysis", None) or {}
        if not isinstance(aid, dict):
            aid = {}
        emotion = str(aid.get("emotion") or "").strip().lower()
        score = float(ai_scores.get(str(m.id), aid.get("score_100", 0.0) or 0.0))
        sb = aid.get("subject_box")
        is_person_focused = False
        if isinstance(sb, (list, tuple)) and len(sb) == 4:
            try:
                ymin, xmin, ymax, xmax = [float(v) for v in sb]
                if max(ymin, xmin, ymax, xmax) > 1.0:
                    ymin, xmin, ymax, xmax = ymin / 1000.0, xmin / 1000.0, ymax / 1000.0, xmax / 1000.0
                area = max(0.0, ymax - ymin) * max(0.0, xmax - xmin)
                is_person_focused = area >= 0.12
            except (TypeError, ValueError):
                is_person_focused = False

        intro_bias = score + (0.6 if not is_person_focused else -0.2)
        climax_bias = score + (1.0 if emotion in climax_emotions else 0.0) + (0.8 if is_person_focused else 0.0)
        outro_bias = score + (1.0 if emotion in outro_emotions else 0.0) + (0.4 if not is_person_focused else 0.0)
        enriched.append(
            {
                "media": m,
                "score": score,
                "emotion": emotion,
                "person": is_person_focused,
                "intro_bias": intro_bias,
                "climax_bias": climax_bias,
                "outro_bias": outro_bias,
            }
        )

    intro_n = 1 if len(enriched) < 6 else 2
    outro_n = 1 if len(enriched) < 7 else 2
    intro_sorted = sorted(enriched, key=lambda x: (-x["intro_bias"], x["media"].order_index))
    intro_pick = intro_sorted[:intro_n]
    picked_ids = {x["media"].id for x in intro_pick}

    remaining = [x for x in enriched if x["media"].id not in picked_ids]
    outro_sorted = sorted(remaining, key=lambda x: (-x["outro_bias"], x["media"].order_index))
    outro_pick = outro_sorted[:outro_n]
    picked_ids.update(x["media"].id for x in outro_pick)

    middle = [x for x in enriched if x["media"].id not in picked_ids]
    middle_sorted = sorted(middle, key=lambda x: (-x["climax_bias"], x["media"].order_index))

    ordered = [x["media"] for x in intro_pick + middle_sorted + outro_pick]
    logger.info(
        "[AI Narrative] reordered: intro=%s middle=%s outro=%s",
        [m.id for m in [x["media"] for x in intro_pick]],
        [m.id for m in [x["media"] for x in middle_sorted]],
        [m.id for m in [x["media"] for x in outro_pick]],
    )
    return ordered


def generate_highlight_narrative_scores(media_files: list) -> dict[str, float] | None:
    """
    선택 미디어마다 0~10 서사 가중치 맵 반환. 토큰·안정성: 순서 리스트 대신 짧은 JSON 맵.
    장애·파싱 실패 시 None (호출부에서 order_index 폴백).
    """
    if not media_files:
        return None
    ids = [int(m.id) for m in media_files]
    id_set = set(ids)
    if len(ids) == 1:
        return {str(ids[0]): 10.0}
    payloads = [_media_file_to_narrative_payload(m) for m in media_files]
    try:
        items_json = json.dumps(payloads, ensure_ascii=False)
    except (TypeError, ValueError):
        return None
    prompt = HIGHLIGHT_NARRATIVE_SCORING_PROMPT + items_json
    try:
        # 출력이 짧아도 2.5 flash 내부 추론 토큰으로 잘리는 것 방지
        result = _call_gemini_text(prompt, max_output_tokens=2048)
        parsed = _parse_highlight_order_json(result or "")
        if not parsed:
            logger.warning("highlight narrative scores parse failed or empty")
            return None
        # 요청 id에 해당하는 키만 유지; 부분 누락 허용 → 없는 id는 0.0으로 정렬 시 뒤로
        filtered: dict[str, float] = {}
        for sid in id_set:
            sk = str(sid)
            if sk in parsed:
                filtered[sk] = parsed[sk]
        if not filtered:
            logger.warning("highlight narrative scores: no matching ids in response %s", parsed.keys())
            return None
        # 전체 id에 대해 저장·정렬용 맵 완성
        merged = {str(mid): float(filtered.get(str(mid), 0.0)) for mid in id_set}
        logger.info("[AI Scoring] Assigned scores: %s", merged)
        return merged
    except Exception as e:  # noqa: BLE001
        logger.warning("generate_highlight_narrative_scores failed: %s", e)
        return None


def generate_lyrical_captions(descriptions: list[str]) -> list[str]:
    """
    각 description을 짧은 서정적 영문 자막으로 변환.
    반환 리스트 길이는 입력과 동일. 실패/빈 항목은 원본 또는 빈 문자열.
    """
    if not descriptions:
        return []
    n = len(descriptions)
    text = "\n".join(f"{i+1}. {(d or '').strip()[:150]}" for i, d in enumerate(descriptions))
    if not text.strip():
        return [""] * n
    prompt = LYRICAL_CAPTION_PROMPT + text
    result = _call_gemini_text(prompt)
    if not result:
        return [(d or "").strip()[:200] for d in descriptions]
    lines = [ln.strip() for ln in result.strip().split("\n") if ln.strip()]
    out = []
    for i in range(n):
        if i < len(lines):
            line = re.sub(r'^\d+[\.\)]\s*', "", lines[i]).strip()[:200]
            out.append(line)
        else:
            out.append((descriptions[i] or "").strip()[:200])
    return out
