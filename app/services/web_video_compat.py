"""
모바일 웹 호환을 위해 HEVC(H.265) 입력을 H.264 MP4로 변환한다.
"""
from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path

from app.utils.ffmpeg_accel import build_h264_encoder_args, run_ffmpeg_with_fallback

logger = logging.getLogger(__name__)

FFPROBE_TIMEOUT_SEC = 60
FFMPEG_TIMEOUT_SEC = 60 * 30


class VideoTranscodeError(RuntimeError):
    pass


def _run(cmd: list[str], timeout_sec: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except FileNotFoundError as e:
        raise VideoTranscodeError(f"명령을 찾을 수 없습니다: {cmd[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise VideoTranscodeError(f"명령 시간 초과({timeout_sec}s): {' '.join(cmd[:4])} ...") from e


def probe_video_codec(path: Path) -> str | None:
    if not path.is_file():
        return None
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name",
        "-of",
        "json",
        str(path),
    ]
    r = _run(cmd, FFPROBE_TIMEOUT_SEC)
    if r.returncode != 0:
        logger.error("ffprobe failed path=%s stderr=%s", path, (r.stderr or "").strip()[:1000])
        return None
    try:
        streams = (json.loads(r.stdout or "{}").get("streams") or [])
    except json.JSONDecodeError:
        return None
    if not streams:
        return None
    return (streams[0].get("codec_name") or "").strip().lower() or None


def _has_audio_stream(path: Path) -> bool:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "json",
        str(path),
    ]
    r = _run(cmd, FFPROBE_TIMEOUT_SEC)
    if r.returncode != 0:
        return False
    try:
        streams = (json.loads(r.stdout or "{}").get("streams") or [])
    except json.JSONDecodeError:
        return False
    return bool(streams)


def ensure_web_compatible_video(path: Path) -> Path:
    """
    HEVC(H.265) 입력이면 H.264(yuv420p, faststart, max 1920w)로 인플레이스 변환.
    그 외 코덱은 원본 유지.
    """
    codec = probe_video_codec(path)
    if codec != "hevc":
        return path

    logger.info("Transcoding HEVC to H264: %s", path)
    fd, tmp_name = tempfile.mkstemp(prefix="h264_", suffix=".mp4", dir=str(path.parent))
    Path(tmp_name).unlink(missing_ok=True)
    tmp_path = Path(tmp_name)

    cmd: list[str] = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        *build_h264_encoder_args(prefer_gpu=True, cq=23, cpu_crf=23),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-vf",
        "scale='min(1920,iw)':-2",
    ]
    if _has_audio_stream(path):
        cmd += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-an"]
    cmd += [str(tmp_path)]

    r = run_ffmpeg_with_fallback(
        cmd,
        timeout_sec=FFMPEG_TIMEOUT_SEC,
        logger=logger,
        conditional_hwaccel_cuda=True,
    )
    if r.returncode != 0 or not tmp_path.exists():
        err = (r.stderr or r.stdout or "").strip()[:2000]
        tmp_path.unlink(missing_ok=True)
        raise VideoTranscodeError(f"ffmpeg transcode 실패: {err}")

    path.unlink(missing_ok=True)
    tmp_path.replace(path)
    out_codec = probe_video_codec(path)
    if out_codec != "h264":
        raise VideoTranscodeError(f"변환 후 코덱 검증 실패: {path} codec={out_codec}")
    return path
