"""
BGM 엔진. 프로젝트 미디어의 주된 감정(emotion)을 집계하고, 해당 감정에 맞는 BGM 경로 반환.
"""
import logging
import random
from collections import Counter
from pathlib import Path

from app.models import MediaFile

logger = logging.getLogger(__name__)

DEFAULT_BGM = "default_bgm.mp3"
JOY_BGM = "happy_vibe.mp3"
PEACEFUL_BGM = "relaxed.mp3"
SAD_BGM = "piano_serenade.mp3"
ROMANTIC_BGM = "romantic.mp3"

# 감정별 고정 BGM과 BPM 매핑
# static/audio/bgm/<emotion>/ 구조가 없어도 동작하도록, 파일명 기반 fallback을 포함합니다.
BGM_BPM_MAP: dict[str, dict[str, object]] = {
    # Default
    "default": {"paths": [DEFAULT_BGM], "bpm": 100},
    # Joy / Energetic
    "joy": {"paths": [JOY_BGM], "bpm": 120},
    "excited": {"paths": [JOY_BGM], "bpm": 120},
    "energetic": {"paths": [JOY_BGM], "bpm": 120},
    # Calm / Peaceful / Romantic
    "calm": {"paths": [PEACEFUL_BGM], "bpm": 90},
    "peaceful": {"paths": [PEACEFUL_BGM], "bpm": 88},
    "romantic": {"paths": [ROMANTIC_BGM], "bpm": 92},
    # Sad / Nostalgic
    "sad": {"paths": [SAD_BGM], "bpm": 70},
    "nostalgic": {"paths": [SAD_BGM], "bpm": 72},
}


def GET_BGM_MAP() -> dict[str, dict[str, object]]:
    """외부에서 확장/대체할 수 있도록 accessor 제공."""
    return BGM_BPM_MAP


def pick_bgm_by_emotion(emotion_tag: str, base_dir: Path) -> dict[str, object]:
    """
    emotion_tag에 맞는 BGM을 랜덤 선택하고, (path, bpm)을 함께 반환한다.

    반환 예:
      {"path": Path(...), "bpm": 128}
    """
    base_dir = Path(base_dir)
    audio_dir = base_dir / "static" / "audio"
    if not audio_dir.exists():
        raise FileNotFoundError(f"static/audio 폴더가 없습니다: {audio_dir}")

    emotion_key = (emotion_tag or "").strip().lower()
    if not emotion_key:
        emotion_key = "default"

    # 1) 선택된 감정에 대한 고정 맵(기본값)
    entry = GET_BGM_MAP().get(emotion_key)

    # 2) (선택) static/audio/bgm/<emotion>/ 폴더에서 랜덤 선택
    #    폴더가 없으면 1) fallback 사용
    folder_pick = None
    maybe_folder = audio_dir / "bgm" / emotion_key
    if maybe_folder.exists() and maybe_folder.is_dir():
        candidates = [
            p
            for p in maybe_folder.iterdir()
            if p.suffix.lower() in (".mp3", ".wav")
        ]
        if candidates:
            folder_pick = random.choice(candidates)

    chosen_path: Path
    chosen_bpm: float
    if folder_pick is not None:
        chosen_path = folder_pick
        # 폴더에 BPM 메타데이터가 없으므로, entry bpm을 우선 사용
        chosen_bpm = float(entry.get("bpm", 0.0)) if entry else 0.0
    elif entry:
        paths = entry.get("paths") or []
        candidates = [audio_dir / str(p) for p in paths if p]
        exist_cands = [p for p in candidates if p.is_file()]
        chosen_path = random.choice(exist_cands) if exist_cands else audio_dir / DEFAULT_BGM
        chosen_bpm = float(entry.get("bpm") or 0.0)
    else:
        chosen_path = audio_dir / DEFAULT_BGM
        chosen_bpm = 0.0

    if not chosen_path.is_file():
        chosen_path = audio_dir / DEFAULT_BGM
    if not chosen_path.is_file():
        raise FileNotFoundError(f"BGM 파일이 없습니다: {chosen_path}")

    return {"path": chosen_path, "bpm": chosen_bpm}


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
    picked = pick_bgm_by_emotion(emotion, base_dir)
    return picked["path"]  # type: ignore[return-value]
