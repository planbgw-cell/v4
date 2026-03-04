"""
BGM 엔진. 프로젝트 미디어의 주된 감정(emotion)을 집계하고, 해당 감정에 맞는 BGM 경로 반환.
"""
import logging
from collections import Counter
from pathlib import Path

from app.models import MediaFile

logger = logging.getLogger(__name__)

DEFAULT_BGM = "default_bgm.mp3"


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
    감정에 맞는 BGM 경로. 현재는 기본 BGM만 사용.
    추후 emotion별 파일(joy_bgm.mp3 등) 추가 시 분기 가능.
    """
    base_dir = Path(base_dir)
    return base_dir / "static" / "audio" / DEFAULT_BGM
