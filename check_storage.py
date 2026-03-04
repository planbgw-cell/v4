#!/usr/bin/env python3
"""
storage/ 폴더에 대한 읽기/쓰기 권한을 확인하는 스크립트.
Zero-Wait I/O 원칙에 따라 pathlib 사용.
"""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
STORAGE = PROJECT_ROOT / "storage"
RAW = STORAGE / "raw"
FINAL = STORAGE / "final"


def check_storage() -> bool:
    ok = True
    for name, base in [("storage", STORAGE), ("storage/raw", RAW), ("storage/final", FINAL)]:
        if not base.exists():
            print(f"[FAIL] {name}: 디렉터리가 없습니다.")
            ok = False
            continue
        if not base.is_dir():
            print(f"[FAIL] {name}: 디렉터리가 아닙니다.")
            ok = False
            continue
        try:
            test_file = base / ".write_test"
            test_file.write_text("ok")
            test_file.read_text()
            test_file.unlink()
            print(f"[OK] {name}: 읽기/쓰기 가능")
        except OSError as e:
            print(f"[FAIL] {name}: {e}")
            ok = False
    return ok


if __name__ == "__main__":
    success = check_storage()
    sys.exit(0 if success else 1)
