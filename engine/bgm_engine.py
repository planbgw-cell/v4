"""
BGM 엔진. 프로젝트 미디어의 주된 감정(emotion)을 집계하고, 해당 감정에 맞는 BGM 경로 반환.
"""
import logging
from collections import Counter
from pathlib import Path

from app.models import MediaFile

logger = logging.getLogger(__name__)

DEFAULT_BGM = "default_bgm.mp3"
JOY_BGM = "joy_bgm.mp3"
PEACEFUL_BGM = "peaceful_bgm.mp3"
SAD_BGM = "sad_bgm.mp3"

# 감정 → BGM 파일명 (select_bgm_path에서 사용)
EMOTION_TO_BGM: dict[str, str] = {
    "Excited": JOY_BGM,
    "Joy": JOY_BGM,
    "Energetic": JOY_BGM,
    "Peaceful": PEACEFUL_BGM,
    "Romantic": PEACEFUL_BGM,
    "Calm": PEACEFUL_BGM,
    "Sad": SAD_BGM,
    "Nostalgic": SAD_BGM,
}


def get_dominant_emotion(media_files: list[MediaFile]) -> str:
    """
    이미지 미디어의 ai_analysis.emotion을 수집해 가장 많이 나온 감정 1개 반환.
    없으면 빈 문자열.
    """
    if not media_files:
        return ""
    emotions: list[str] = []
    for mf in media_files:
        if mf.file_type != "image" or not mf.ai_analysis:
            continue
        e = (mf.ai_analysis or {}).get("emotion")
        if isinstance(e, str) and e.strip():
            emotions.append(e.strip())
    if not emotions:
        return ""
    most = Counter(emotions).most_common(1)
    return most[0][0] if most else ""


def select_bgm_path(emotion: str, base_dir: Path) -> Path:
    """
    감정에 맞는 BGM 경로. Excited/Joy → joy, Peaceful/Romantic/Calm → peaceful, Sad/Nostalgic → sad.
    해당 파일이 없으면 default_bgm.mp3로 fallback.
    """
    base_dir = Path(base_dir)
    audio_dir = base_dir / "static" / "audio"
    if emotion and emotion.strip():
        key = emotion.strip()
        filename = EMOTION_TO_BGM.get(key) or EMOTION_TO_BGM.get(key.lower().capitalize())
        if filename and (audio_dir / filename).exists():
            return audio_dir / filename
    return audio_dir / DEFAULT_BGM
