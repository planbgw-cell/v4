"""
하이라이트 클립·concat 병합용 통일 오디오 스펙 (Admin 16).
이미지 무음·동영상·인트로 콜라주가 동일 AAC 프로파일이어야 concat -c copy가 안전하다.
"""
CLIP_AUDIO_SAMPLE_RATE = 48000
CLIP_AUDIO_CHANNELS = 2
CLIP_AUDIO_BITRATE = "128k"
CLIP_AUDIO_LAYOUT = "stereo"
CLIP_AUDIO_CODEC = "aac"


def clip_anullsrc_lavfi() -> str:
    return (
        f"anullsrc=channel_layout={CLIP_AUDIO_LAYOUT}:"
        f"sample_rate={CLIP_AUDIO_SAMPLE_RATE}"
    )


def clip_audio_encode_args() -> list[str]:
    return [
        "-c:a",
        CLIP_AUDIO_CODEC,
        "-ar",
        str(CLIP_AUDIO_SAMPLE_RATE),
        "-ac",
        str(CLIP_AUDIO_CHANNELS),
        "-b:a",
        CLIP_AUDIO_BITRATE,
    ]


def clip_audio_atrim_filter(duration_sec: float) -> str:
    """무음/원음 공통: 클립 길이에 맞춘 atrim."""
    d = max(0.04, float(duration_sec))
    return f"atrim=start=0:duration={d:.6f},asetpts=PTS-STARTPTS"
