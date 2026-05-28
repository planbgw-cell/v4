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

