#!/usr/bin/env python3
"""
Quick VA-API visibility check for flairy v4 runtime.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from typing import List


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def run(cmd: List[str]) -> tuple[int, str]:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        return 0, out.strip()
    except subprocess.CalledProcessError as exc:
        return exc.returncode, (exc.output or "").strip()
    except FileNotFoundError:
        return 127, f"command not found: {cmd[0]}"


def main() -> int:
    print("== Python media module check ==")
    for mod in ["cv2", "av"]:
        print(f"{mod}: {'installed' if has_module(mod) else 'not-installed'}")

    if has_module("cv2"):
        import cv2  # type: ignore

        info = cv2.getBuildInformation()
        keys = ["FFMPEG", "VA", "GStreamer", "Video I/O"]
        print("\n== OpenCV build info (selected lines) ==")
        for line in info.splitlines():
            if any(k in line for k in keys):
                print(line)
    else:
        print("\nOpenCV not installed; skipping cv2 build inspection.")

    print("\n== System VA-API check (vainfo) ==")
    rc, out = run(["vainfo"])
    print(f"vainfo exit_code={rc}")
    if out:
        for line in out.splitlines()[:40]:
            print(line)

    print("\n== ffmpeg encoder check ==")
    rc, out = run(["ffmpeg", "-encoders"])
    if rc == 0:
        matched = [ln for ln in out.splitlines() if "vaapi" in ln.lower()]
        if matched:
            for line in matched:
                print(line)
        else:
            print("No VAAPI encoders listed.")
    else:
        print(out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
