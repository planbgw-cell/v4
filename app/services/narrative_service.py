"""
앨범 감성 스토리텔링: Gemini 텍스트 전용 호출.
- 앨범 영문 감성 타이틀 생성
- description → 서정적 영문 자막(lyrical caption) 변환
"""
import logging
import os
import re
import time

logger = logging.getLogger(__name__)


try:
    import google.generativeai as genai
except ImportError:
    genai = None  # type: ignore[misc, assignment]

GEMINI_MODEL = "gemini-2.5-flash"
MAX_RETRIES = 3
INITIAL_BACKOFF_SEC = 2.0

ALBUM_TITLE_PROMPT = """Given these short photo descriptions (one per line), suggest a single poetic English title that captures the mood of this album.
Reply with only the title phrase, no quotes or explanation. Example: Whispers of the Emerald Sea.
Keep it under 60 characters.

Descriptions:
"""
LYRICAL_CAPTION_PROMPT = """Convert each of the following short photo descriptions into a single short lyrical English caption for a photo album.
One line per caption, poetic and evocative. Max 60 chars each.
Reply with exactly one caption per line, in the same order. No numbering or bullets.

Descriptions:
"""


def _get_model():
    if genai is None:
        raise ValueError("google-generativeai 패키지가 필요합니다. pip install google-generativeai")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(
        GEMINI_MODEL,
        generation_config=genai.types.GenerationConfig(
            temperature=0.7,
            max_output_tokens=1024,
        ),
    )


def _call_gemini_text(prompt: str) -> str:
    """텍스트만으로 Gemini 호출. 재시도·fallback."""
    model = _get_model()
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            response = model.generate_content(prompt)
            if response and response.text:
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
