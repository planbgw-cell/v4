#!/usr/bin/env python3
"""
특정 프로젝트 raw 폴더의 HEVC mp4를 H.264로 변환한다.
파일명은 유지하므로 album_layout.json 수정이 필요 없다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.web_video_compat import ensure_web_compatible_video, probe_video_codec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_id")
    args = ap.parse_args()

    raw_dir = ROOT / "storage" / "raw" / args.project_id
    if not raw_dir.exists():
        print(f"raw dir not found: {raw_dir}")
        return 1

    changed = 0
    for p in sorted(raw_dir.glob("*.mp4")):
        before = probe_video_codec(p)
        ensure_web_compatible_video(p)
        after = probe_video_codec(p)
        print(f"{p.name}: {before} -> {after}")
        if before != after:
            changed += 1
    print(f"done. changed={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
