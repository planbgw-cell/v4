from __future__ import annotations

import os
import subprocess
import threading
from collections.abc import Sequence
from typing import Any

GPU_MAX_SESSIONS = int(os.environ.get("FLAIRY_GPU_MAX_SESSIONS", "3"))
GPU_SEMAPHORE_TIMEOUT_SEC = int(os.environ.get("FLAIRY_GPU_SEMAPHORE_TIMEOUT_SEC", "2"))
_GPU_SEMAPHORE = threading.BoundedSemaphore(max(1, GPU_MAX_SESSIONS))

_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
_GPU_ENCODERS = {"h264_nvenc", "hevc_nvenc", "av1_nvenc"}
_HWACCEL_FAIL_PATTERNS = (
    "decoder not found",
    "unsupported codec",
    "device type cuda needed for codec",
    "no device available for decoder",
)
_GPU_FAIL_PATTERNS = (
    "cannot load libcuda",
    "no nvenc capable devices found",
    "driver does not support the required nvenc api version",
    "openencode session failed",
    "cannot init encoder",
    "resource temporarily unavailable",
    "out of memory",
)


def build_h264_encoder_args(*, prefer_gpu: bool, cq: int, cpu_crf: int = 25) -> list[str]:
    if prefer_gpu:
        return ["-c:v", "h264_nvenc", "-rc", "vbr", "-cq", str(cq), "-preset", "p4"]
    return ["-c:v", "libx264", "-crf", str(cpu_crf), "-preset", "fast"]


def _has_nvenc(cmd: Sequence[str]) -> bool:
    return any(tok in _GPU_ENCODERS for tok in cmd)


def _is_video_input(path: str) -> bool:
    return any(path.lower().endswith(ext) for ext in _VIDEO_EXTS)


def _insert_hwaccel_cuda(cmd: Sequence[str]) -> list[str]:
    out = list(cmd)
    if "-hwaccel" in out:
        return out
    for idx, tok in enumerate(out):
        if tok == "-i" and idx + 1 < len(out) and _is_video_input(str(out[idx + 1])):
            out[idx:idx] = ["-hwaccel", "cuda"]
            return out
    return out


def _strip_hwaccel(cmd: Sequence[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(cmd):
        if cmd[i] == "-hwaccel":
            i += 2
            continue
        out.append(cmd[i])
        i += 1
    return out


def _to_cpu_fallback(cmd: Sequence[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(cmd):
        tok = cmd[i]
        if tok == "-c:v" and i + 1 < len(cmd) and cmd[i + 1] in _GPU_ENCODERS:
            out.extend(["-c:v", "libx264"])
            i += 2
            continue
        if tok == "-rc" and i + 1 < len(cmd):
            i += 2
            continue
        if tok == "-cq" and i + 1 < len(cmd):
            out.extend(["-crf", cmd[i + 1]])
            i += 2
            continue
        if tok == "-preset" and i + 1 < len(cmd) and cmd[i + 1].startswith("p"):
            out.extend(["-preset", "fast"])
            i += 2
            continue
        out.append(tok)
        i += 1
    return _strip_hwaccel(out)


def _stderr_text(cp: subprocess.CompletedProcess[str]) -> str:
    return ((cp.stderr or "") + "\n" + (cp.stdout or "")).lower()


def _contains_any(text: str, needles: Sequence[str]) -> bool:
    return any(n in text for n in needles)


def run_ffmpeg_with_fallback(
    cmd: Sequence[str],
    *,
    timeout_sec: int,
    logger: Any,
    conditional_hwaccel_cuda: bool = False,
) -> subprocess.CompletedProcess[str]:
    cmd_gpu = list(cmd)
    if conditional_hwaccel_cuda and _has_nvenc(cmd_gpu):
        cmd_gpu = _insert_hwaccel_cuda(cmd_gpu)

    if _has_nvenc(cmd_gpu):
        acquired = _GPU_SEMAPHORE.acquire(timeout=max(0, GPU_SEMAPHORE_TIMEOUT_SEC))
        if not acquired:
            logger.warning("GPU_SLOT_UNAVAILABLE -> FALLBACK_CPU")
            cmd_cpu = _to_cpu_fallback(cmd_gpu)
            return subprocess.run(cmd_cpu, capture_output=True, text=True, timeout=timeout_sec, check=False)
        logger.info("GPU_SLOT_ACQUIRED")
        try:
            r = subprocess.run(cmd_gpu, capture_output=True, text=True, timeout=timeout_sec, check=False)
            if r.returncode == 0:
                return r
            err = _stderr_text(r)
            if conditional_hwaccel_cuda and _contains_any(err, _HWACCEL_FAIL_PATTERNS):
                logger.warning("HWACCEL_AUTO_SKIP -> retry without -hwaccel cuda")
                r2 = subprocess.run(_strip_hwaccel(cmd_gpu), capture_output=True, text=True, timeout=timeout_sec, check=False)
                if r2.returncode == 0:
                    return r2
                err = _stderr_text(r2)
                r = r2
            if _contains_any(err, _GPU_FAIL_PATTERNS) or _has_nvenc(cmd_gpu):
                logger.warning("FALLBACK_CPU due to GPU error")
                return subprocess.run(_to_cpu_fallback(cmd_gpu), capture_output=True, text=True, timeout=timeout_sec, check=False)
            return r
        finally:
            _GPU_SEMAPHORE.release()
            logger.info("GPU_SLOT_RELEASED")

    return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout_sec, check=False)
