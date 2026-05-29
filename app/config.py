from __future__ import annotations

import os
from pathlib import Path


def get_video_accel_type() -> str:
    return (os.getenv("VIDEO_ACCEL_TYPE", "auto") or "auto").strip().lower()


def get_highlight_merge_mode() -> str:
    return (os.getenv("HIGHLIGHT_MERGE_MODE", "xfade") or "xfade").strip().lower()


def get_gpu_max_sessions() -> int:
    try:
        return max(1, int(os.getenv("FLAIRY_GPU_MAX_SESSIONS", "3")))
    except ValueError:
        return 3


def get_gpu_semaphore_timeout_sec() -> int:
    try:
        return max(0, int(os.getenv("FLAIRY_GPU_SEMAPHORE_TIMEOUT_SEC", "2")))
    except ValueError:
        return 2


def get_video_render_max_workers() -> int:
    try:
        return max(1, int(os.getenv("VIDEO_RENDER_MAX_WORKERS", "4")))
    except ValueError:
        return 4


def get_flairy_temp_dir() -> Path | None:
    raw = (os.getenv("FLAIRY_TEMP_DIR", "") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def get_beta_max_project_quota() -> int:
    try:
        return max(1, int(os.getenv("BETA_MAX_PROJECT_QUOTA", "5")))
    except ValueError:
        return 5


def get_public_base_url() -> str:
    """외부 공유·매직 링크·알림에 쓰는 공개 사이트 URL (scheme+host, trailing slash 없음)."""
    raw = (os.getenv("PUBLIC_BASE_URL") or os.getenv("SITE_URL") or "https://flairy.kr").strip()
    return raw.rstrip("/")


def get_cookie_domain() -> str | None:
    """
    세션 쿠키 Domain (apex·www 공유).
    localhost/127.0.0.1/빈 값이면 None → 호스트 전용 쿠키(로컬 개발).
    """
    raw = (os.getenv("COOKIE_DOMAIN") or "flairy.kr").strip().lstrip(".")
    if not raw:
        return None
    lower = raw.lower()
    if lower in ("localhost", "127.0.0.1") or lower.endswith(".localhost"):
        return None
    return raw


def get_cookie_secure() -> bool:
    return os.getenv("COOKIE_SECURE", "false").strip().lower() in ("true", "1", "yes")

