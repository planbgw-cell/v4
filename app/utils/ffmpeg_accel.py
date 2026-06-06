from __future__ import annotations

import os
import re
import subprocess
import threading
from collections.abc import Sequence
from typing import Any

from app.config import (
    get_gpu_max_sessions,
    get_gpu_semaphore_timeout_sec,
    get_video_accel_type,
)

GPU_MAX_SESSIONS = get_gpu_max_sessions()
GPU_SEMAPHORE_TIMEOUT_SEC = get_gpu_semaphore_timeout_sec()
_GPU_SEMAPHORE = threading.BoundedSemaphore(max(1, GPU_MAX_SESSIONS))
_DETECT_LOCK = threading.Lock()
_ACCEL_CACHE: str | None = None
_ENCODER_CACHE: set[str] | None = None
_LOGGED_ACCEL_TYPES: set[str] = set()
_LOGGED_ACCEL_DIAG: set[str] = set()

_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
_GPU_ENCODERS = {"h264_nvenc", "hevc_nvenc", "av1_nvenc"}
_VAAPI_ENCODERS = {"h264_vaapi", "hevc_vaapi"}
_ALL_HW_ENCODERS = _GPU_ENCODERS | _VAAPI_ENCODERS
_VAAPI_DEVICE = os.environ.get("VAAPI_DEVICE", "/dev/dri/renderD128")
_GPU_FAIL_PATTERNS = (
    "cannot load libcuda",
    "no nvenc capable devices found",
    "driver does not support the required nvenc api version",
    "openencode session failed",
    "cannot init encoder",
    "resource temporarily unavailable",
    "out of memory",
)
_VAAPI_FAIL_PATTERNS = (
    "device creation failed",
    "failed to initialise vaapi connection",
    "no usable encoding entrypoint found",
    "resource busy",
    "permission denied",
    "invalid vaapi profile",
)
_FILTER_GRAPH_FAIL_PATTERNS = (
    "invalid color space",
    "error reinitializing filters",
    "error parsing filter",
    "failed to inject frame into filter network",
    "function not implemented",
)
_HW_ENCODER_FAIL_EXIT_CODES = frozenset({218, 234})


def build_h264_encoder_args(*, prefer_gpu: bool, cq: int, cpu_crf: int = 25) -> list[str]:
    if not prefer_gpu:
        return ["-c:v", "libx264", "-crf", str(cpu_crf), "-preset", "fast"]
    accel = get_accel_type()
    if accel == "vaapi":
        return ["-c:v", "h264_vaapi", "-rc_mode", "1", "-qp", str(cq), "-preset:v", "fast"]
    if accel == "nvenc":
        return ["-c:v", "h264_nvenc", "-rc", "vbr", "-cq", str(cq), "-preset", "p4"]
    return ["-c:v", "libx264", "-crf", str(cpu_crf), "-preset", "fast"]


def _run_capture(cmd: Sequence[str], timeout_sec: int = 4) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )


def _get_ffmpeg_encoders() -> set[str]:
    global _ENCODER_CACHE
    if _ENCODER_CACHE is not None:
        return _ENCODER_CACHE
    try:
        r = _run_capture(["ffmpeg", "-hide_banner", "-encoders"], timeout_sec=6)
        names: set[str] = set()
        for line in (r.stdout or "").splitlines():
            parts = line.split()
            if len(parts) >= 2:
                names.add(parts[1].strip())
        _ENCODER_CACHE = names
    except Exception:
        _ENCODER_CACHE = set()
    return _ENCODER_CACHE


def _detect_nvidia() -> bool:
    if "h264_nvenc" not in _get_ffmpeg_encoders():
        return False
    try:
        r = _run_capture(["nvidia-smi", "-L"], timeout_sec=3)
        return r.returncode == 0 and bool((r.stdout or "").strip())
    except Exception:
        return False


def _detect_amd_vaapi() -> bool:
    if "h264_vaapi" not in _get_ffmpeg_encoders():
        return False
    if not os.path.exists(_VAAPI_DEVICE):
        return False
    if not os.access(_VAAPI_DEVICE, os.R_OK | os.W_OK):
        return False
    vendor_path = "/sys/class/drm/renderD128/device/vendor"
    try:
        if os.path.exists(vendor_path):
            vendor = (open(vendor_path, encoding="utf-8").read().strip() or "").lower()
            # AMD PCI vendor id: 0x1002
            if vendor == "0x1002":
                return True
    except Exception:
        pass
    return True


def _is_video_input(path: str) -> bool:
    return any(path.lower().endswith(ext) for ext in _VIDEO_EXTS)


def get_accel_type() -> str:
    global _ACCEL_CACHE
    forced = get_video_accel_type()
    if forced in {"vaapi", "nvenc", "cpu"}:
        return forced
    if _ACCEL_CACHE is not None:
        return _ACCEL_CACHE
    with _DETECT_LOCK:
        if _ACCEL_CACHE is not None:
            return _ACCEL_CACHE
        if _detect_amd_vaapi():
            _ACCEL_CACHE = "vaapi"
        elif _detect_nvidia():
            _ACCEL_CACHE = "nvenc"
        else:
            _ACCEL_CACHE = "cpu"
    return _ACCEL_CACHE


def _has_hw_encoder(cmd: Sequence[str]) -> bool:
    return any(tok in _ALL_HW_ENCODERS for tok in cmd)


def _is_vaapi_cmd(cmd: Sequence[str]) -> bool:
    return any(tok in _VAAPI_ENCODERS for tok in cmd)


def _is_nvenc_cmd(cmd: Sequence[str]) -> bool:
    return any(tok in _GPU_ENCODERS for tok in cmd)


def _insert_vaapi_hwaccel(cmd: Sequence[str]) -> list[str]:
    out = list(cmd)
    if "-vaapi_device" not in out:
        if out and out[0] == "ffmpeg":
            out = [out[0], "-vaapi_device", _VAAPI_DEVICE, *out[1:]]
        else:
            out = ["-vaapi_device", _VAAPI_DEVICE, *out]
    if "-hwaccel" in out:
        return out
    for idx, tok in enumerate(out):
        if tok == "-i" and idx + 1 < len(out) and _is_video_input(str(out[idx + 1])):
            out[idx:idx] = [
                "-hwaccel",
                "vaapi",
                "-hwaccel_device",
                _VAAPI_DEVICE,
                "-hwaccel_output_format",
                "vaapi",
            ]
            return out
    return out


def _ensure_vaapi_upload(cmd: Sequence[str]) -> list[str]:
    out = list(cmd)
    if "-vf" in out:
        idx = out.index("-vf")
        if idx + 1 < len(out):
            vf = out[idx + 1]
            vf_trim = vf.rstrip()
            # 라벨 [vid] 뒤에 쉼표로 이어붙이면 FFmpeg가 파싱 실패 → 라벨 제거 후 업로드 연결
            if vf_trim.endswith("[vid]"):
                base = vf_trim[:-5].rstrip().rstrip(",")
                out[idx + 1] = base + ",format=nv12,hwupload"
            else:
                need_upload = ("hwupload" not in vf) or (
                    "hwdownload" in vf and not vf_trim.endswith("hwupload")
                )
                if need_upload:
                    out[idx + 1] = vf + ",format=nv12,hwupload"
    if "-filter_complex" in out:
        idx = out.index("-filter_complex")
        if idx + 1 < len(out):
            fc = out[idx + 1]
            if "[vout]" in fc and "hwupload" not in fc:
                out[idx + 1] = fc + ";[vout]format=nv12,hwupload[vout_hw]"
                for j in range(len(out) - 1):
                    if out[j] == "-map" and out[j + 1] == "[vout]":
                        out[j + 1] = "[vout_hw]"
                        break
    return out


def _strip_hwaccel_and_vaapi_device(cmd: Sequence[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(cmd):
        tok = cmd[i]
        if tok == "-vaapi_device":
            i += 2
            continue
        if tok == "-hwaccel":
            i += 2
            continue
        if tok in {"-hwaccel_device", "-hwaccel_output_format"}:
            i += 2
            continue
        out.append(tok)
        i += 1
    return out


def build_cpu_fallback_cmd(cmd: Sequence[str]) -> list[str]:
    """VAAPI/NVENC 명령을 libx264 CPU 경로로 변환."""
    return _to_cpu_fallback(cmd)


def extract_ffmpeg_failure_reason(
    cp: subprocess.CompletedProcess[str],
    *,
    source_label: str | None = None,
) -> str:
    text = ((cp.stderr or "") + "\n" + (cp.stdout or "")).strip()
    lowered = text.lower()
    detail = ""
    for line in text.splitlines():
        ll = line.lower()
        if any(
            marker in ll
            for marker in (
                "invalid color space",
                "error reinitializing filters",
                "conversion failed",
                "could not open encoder",
            )
        ):
            detail = line.strip()
            break
    if not detail:
        detail = text.splitlines()[-1].strip() if text else f"exit {cp.returncode}"
    label = source_label or "ffmpeg"
    return f"{detail} in {label}" if " in " not in detail else detail


def _should_fallback_to_cpu(cp: subprocess.CompletedProcess[str]) -> bool:
    if cp.returncode == 0:
        return False
    err = _stderr_text(cp)
    if cp.returncode in _HW_ENCODER_FAIL_EXIT_CODES:
        return True
    if _contains_any(err, _FILTER_GRAPH_FAIL_PATTERNS):
        return True
    if _contains_any(err, _VAAPI_FAIL_PATTERNS):
        return True
    if _contains_any(err, _GPU_FAIL_PATTERNS):
        return True
    return False


def _to_cpu_fallback(cmd: Sequence[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(cmd):
        tok = cmd[i]
        if tok == "-c:v" and i + 1 < len(cmd) and cmd[i + 1] in _ALL_HW_ENCODERS:
            out.extend(["-c:v", "libx264"])
            i += 2
            continue
        if tok == "-rc" and i + 1 < len(cmd):
            i += 2
            continue
        if tok == "-rc_mode" and i + 1 < len(cmd):
            i += 2
            continue
        if tok == "-cq" and i + 1 < len(cmd):
            out.extend(["-crf", cmd[i + 1]])
            i += 2
            continue
        if tok == "-qp" and i + 1 < len(cmd):
            out.extend(["-crf", cmd[i + 1]])
            i += 2
            continue
        if tok == "-preset" and i + 1 < len(cmd) and cmd[i + 1].startswith("p"):
            out.extend(["-preset", "fast"])
            i += 2
            continue
        out.append(tok)
        i += 1
    out = _strip_hwaccel_and_vaapi_device(out)
    # CPU 경로에서는 hwupload 필터 제거
    if "-vf" in out:
        idx = out.index("-vf")
        if idx + 1 < len(out):
            vf = out[idx + 1].replace(",format=nv12,hwupload", "")
            vf = vf.replace("format=nv12,hwupload,", "")
            vf = vf.replace(",hwupload", "").replace("format=nv12,", "")
            vf = vf.replace(",hwdownload,format=nv12", "")
            vf = vf.replace(",hwdownload,format=yuv420p", "")
            vf = re.sub(
                r"scale_vaapi=w=(\d+):h=(\d+):format=nv12",
                r"scale=\1:\2",
                vf,
            )
            out[idx + 1] = vf
    if "-filter_complex" in out:
        idx = out.index("-filter_complex")
        if idx + 1 < len(out):
            fc = out[idx + 1]
            fc = fc.replace(";[vout]format=nv12,hwupload[vout_hw]", "")
            out[idx + 1] = fc
            for j in range(len(out) - 1):
                if out[j] == "-map" and out[j + 1] == "[vout_hw]":
                    out[j + 1] = "[vout]"
                    break
    return out


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
    source_label: str | None = None,
    force_cpu: bool = False,
) -> subprocess.CompletedProcess[str]:
    accel = get_accel_type()
    if accel not in _LOGGED_ACCEL_TYPES:
        logger.info("ACCEL_TYPE: %s", accel.upper())
        _LOGGED_ACCEL_TYPES.add(accel)
    if accel == "vaapi" and accel not in _LOGGED_ACCEL_DIAG:
        logger.info(
            "ACCEL_DIAG: VAAPI device=%s exists=%s rw=%s",
            _VAAPI_DEVICE,
            os.path.exists(_VAAPI_DEVICE),
            os.access(_VAAPI_DEVICE, os.R_OK | os.W_OK),
        )
        _LOGGED_ACCEL_DIAG.add(accel)
    if accel == "nvenc" and accel not in _LOGGED_ACCEL_DIAG:
        logger.info("ACCEL_DIAG: NVENC selected by runtime detection")
        _LOGGED_ACCEL_DIAG.add(accel)
    if accel == "cpu" and accel not in _LOGGED_ACCEL_DIAG:
        logger.info("ACCEL_DIAG: CPU fallback selected by runtime detection")
        _LOGGED_ACCEL_DIAG.add(accel)
    cmd_hw = list(cmd)
    if accel == "vaapi" and _is_vaapi_cmd(cmd_hw):
        if not os.access(_VAAPI_DEVICE, os.R_OK | os.W_OK):
            logger.warning("ACCEL_TYPE: VAAPI 권한/장치 접근 불가 (%s) -> CPU fallback", _VAAPI_DEVICE)
            accel = "cpu"
        else:
            cmd_hw = _insert_vaapi_hwaccel(cmd_hw)
            cmd_hw = _ensure_vaapi_upload(cmd_hw)
    elif accel == "nvenc" and conditional_hwaccel_cuda and _is_nvenc_cmd(cmd_hw):
        # 기존 인터페이스와 호환: NVENC 경로에서만 cuda hwaccel 적용
        for idx, tok in enumerate(cmd_hw):
            if tok == "-i" and idx + 1 < len(cmd_hw) and _is_video_input(str(cmd_hw[idx + 1])):
                cmd_hw[idx:idx] = ["-hwaccel", "cuda"]
                break

    if force_cpu:
        cmd_cpu = _to_cpu_fallback(cmd_hw if _has_hw_encoder(cmd_hw) else cmd)
        logger.warning(
            "[Fallback] CPU(libx264) 강제 경로 사용%s",
            f" source={source_label}" if source_label else "",
        )
        return subprocess.run(cmd_cpu, capture_output=True, text=True, timeout=timeout_sec, check=False)

    if accel in {"vaapi", "nvenc"} and _has_hw_encoder(cmd_hw):
        acquired = _GPU_SEMAPHORE.acquire(timeout=max(0, GPU_SEMAPHORE_TIMEOUT_SEC))
        if not acquired:
            reason = "GPU slot unavailable"
            logger.warning(
                "[Fallback] %s -> CPU(libx264)%s",
                reason,
                f" source={source_label}" if source_label else "",
            )
            cmd_cpu = _to_cpu_fallback(cmd_hw)
            return subprocess.run(cmd_cpu, capture_output=True, text=True, timeout=timeout_sec, check=False)
        logger.info("GPU_SLOT_ACQUIRED")
        try:
            r = subprocess.run(cmd_hw, capture_output=True, text=True, timeout=timeout_sec, check=False)
            if r.returncode == 0:
                return r
            if not _should_fallback_to_cpu(r):
                return r
            reason = extract_ffmpeg_failure_reason(r, source_label=source_label)
            logger.warning(
                "[Fallback] VAAPI/필터 오류 감지 (%s). CPU(libx264) 우회 재시도를 시작합니다.",
                reason,
            )
            return subprocess.run(
                _to_cpu_fallback(cmd_hw),
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
        finally:
            _GPU_SEMAPHORE.release()
            logger.info("GPU_SLOT_RELEASED")

    return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout_sec, check=False)
