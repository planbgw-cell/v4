"""
rule vs AI 세로사진 렌더 원인 비교 — 확인 절차 1, 4, 5 실행.

사용:
  python scripts/check_orientation_deps.py [project_id_1 [project_id_2]]
  - 인자 없음: 의존성만 확인.
  - project_id 1개: 해당 프로젝트 raw 파일 확장자 통계.
  - project_id 2개: 두 프로젝트(예: rule / AI) 확장자 비교.

렌더 후 로그 확인(수동):
  - EXIF 미적용: 서버 로그에서 "EXIF orientation 미적용: path=... (reason: ...)"
  - 916_vf: "916_vf: file=... raw_wh=(W,H) rotation=... is_portrait=..."
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_BASE = ROOT / "storage" / "raw"


def check_deps() -> bool:
    """pillow_heif, piexif import 가능 여부. 성공 시 True."""
    ok = True
    try:
        import pillow_heif
        print("pillow_heif: ok")
    except ImportError as e:
        print("pillow_heif: FAIL —", e)
        ok = False
    try:
        import piexif
        print("piexif: ok")
    except ImportError as e:
        print("piexif: FAIL —", e)
        ok = False
    return ok


def extensions_in_dir(dir_path: Path) -> dict[str, int]:
    """디렉터리 내 파일 확장자별 개수 (소문자)."""
    counts: dict[str, int] = {}
    if not dir_path.is_dir():
        return counts
    for f in dir_path.iterdir():
        if f.is_file():
            ext = f.suffix.lower() or "(no ext)"
            counts[ext] = counts.get(ext, 0) + 1
    return counts


def main() -> None:
    print("=== 의존성 확인 (확인 절차 4) ===")
    deps_ok = check_deps()
    print()

    ids = [a.strip() for a in sys.argv[1:3]]
    if not ids:
        print("프로젝트 ID 없음. 파일 확장자 확인 생략.")
        print("사용 예: python scripts/check_orientation_deps.py <project_id> [project_id2]")
        sys.exit(0 if deps_ok else 1)

    print("=== 프로젝트 raw 파일 확장자 (확인 절차 1, 5) ===")
    for i, pid in enumerate(ids):
        raw_dir = RAW_BASE / pid
        counts = extensions_in_dir(raw_dir)
        if not counts:
            print(f"[{pid}] (디렉터리 없음 또는 비어 있음): {raw_dir}")
        else:
            total = sum(counts.values())
            print(f"[{pid}] 총 {total}개: {dict(sorted(counts.items()))}")
    print()
    if not deps_ok:
        print("HEIC 사용 시 pillow-heif, piexif 설치 필요: pip3 install pillow-heif piexif")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
