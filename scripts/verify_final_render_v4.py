#!/usr/bin/env python3
"""
Flairy v4 하이라이트 최종 출력 검증: ffprobe 메타, render_timeline.json 대조,
(선택) 오디오 레벨 샘플(ebur128).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HIGH_HOLD_SEC = 10.0


def _run(cmd: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout or "", r.stderr or ""


def ffprobe_video_basic(path: Path) -> dict:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,r_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    code, out, err = _run(cmd)
    if code != 0:
        raise RuntimeError(f"ffprobe 실패: {err or out}")
    data = json.loads(out)
    streams = data.get("streams") or []
    if not streams:
        raise RuntimeError("비디오 스트림 없음")
    s = streams[0]
    w = int(s.get("width", 0))
    h = int(s.get("height", 0))
    rfr = str(s.get("r_frame_rate") or "0/1")
    num, _, den = rfr.partition("/")
    fps = float(num) / float(den) if den and float(den) != 0 else 0.0
    return {"width": w, "height": h, "fps": fps, "r_frame_rate": rfr}


def ffprobe_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    code, out, err = _run(cmd)
    if code != 0:
        raise RuntimeError(f"duration 실패: {err or out}")
    return float((out or "").strip() or 0.0)


def ebur128_sample(path: Path) -> str:
    """전체 길이에 대해 ebur128 한 줄 요약(로그용)."""
    cmd = [
        "ffmpeg",
        "-nostats",
        "-i",
        str(path),
        "-af",
        "ebur128=peak=true",
        "-f",
        "null",
        "-",
    ]
    code, _out, err = _run(cmd)
    # ebur128는 보통 stderr에 통계 출력
    return (err or "")[-4000:]


def print_timeline_image_report(timeline_path: Path) -> None:
    """image 세그먼트별 duration·score_100 출력. ~10s 노출은 박자 스냅으로 약간 어긋날 수 있음."""
    data = json.loads(timeline_path.read_text(encoding="utf-8"))
    segs = data.get("segments") or []
    for seg in segs:
        if seg.get("kind") != "image":
            continue
        d = float(seg.get("duration_sec", 0.0))
        sc = seg.get("score_100")
        mid = seg.get("media_id")
        line = f"  image media_id={mid} duration={d:.3f}s score_100={sc}"
        if d >= 9.0:
            if abs(d - HIGH_HOLD_SEC) <= 0.35:
                line += "  (~10s 고노출 구간)"
            else:
                line += f"  (10s 목표와 Δ={abs(d - HIGH_HOLD_SEC):.3f}s — Beat 스냅 가능)"
        print(line)


def main() -> int:
    ap = argparse.ArgumentParser(description="Flairy v4 최종 렌더 검증")
    ap.add_argument("output_mp4", type=Path, help="storage/final/<project>/output.mp4")
    ap.add_argument(
        "--timeline",
        type=Path,
        default=None,
        help="render_timeline.json (없으면 같은 디렉터리에서 자동 탐색)",
    )
    ap.add_argument("--audio-log", action="store_true", help="ebur128 로그 일부 출력")
    args = ap.parse_args()

    mp4 = args.output_mp4
    if not mp4.is_file():
        print(f"ERR: 파일 없음: {mp4}", file=sys.stderr)
        return 2

    timeline = args.timeline
    if timeline is None:
        cand = mp4.parent / "render_timeline.json"
        timeline = cand if cand.is_file() else None

    ok = True
    try:
        v = ffprobe_video_basic(mp4)
    except RuntimeError as e:
        print(f"ERR: {e}", file=sys.stderr)
        return 2

    if v["width"] != 1080 or v["height"] != 1920:
        print(f"ERR: 해상도 기대 1080x1920, 실제 {v['width']}x{v['height']}")
        ok = False
    else:
        print(f"OK: 해상도 {v['width']}x{v['height']}")

    if abs(v["fps"] - 30.0) > 0.02:
        print(f"WARN: 프레임레이트 기대 ~30, 실제 {v['fps']:.3f} ({v['r_frame_rate']})")
    else:
        print(f"OK: fps ≈ 30 ({v['r_frame_rate']})")

    dur = ffprobe_duration(mp4)
    print(f"INFO: 총 길이 {dur:.3f}s")

    if timeline and timeline.is_file():
        print(f"INFO: 타임라인 {timeline}")
        try:
            print("INFO: 본편 이미지 클립(타임라인 세그먼트)")
            print_timeline_image_report(timeline)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            print(f"WARN: 타임라인 해석 실패: {e}")
    else:
        print("WARN: render_timeline.json 없음 — 타임라인 대조 생략")

    if args.audio_log:
        print("INFO: ebur128 stderr tail (오디오 레벨 참고)")
        print(ebur128_sample(mp4)[-2000:])

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
