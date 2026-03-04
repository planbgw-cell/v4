#!/usr/bin/env python3
"""
기존 storage/raw/ 평면 구조를 storage/raw/{project_id}/ 로 이전하는 마이그레이션 스크립트.
실행 전 반드시 storage 폴더를 백업하세요.

사용: cd v4 && python scripts/migrate_storage.py
     또는 PYTHONPATH=v4 python scripts/migrate_storage.py (프로젝트 루트에서)
"""
import sys
from pathlib import Path

# v4 루트를 path에 추가
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import shutil
from uuid import UUID

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import MediaFile

STORAGE_DIR = ROOT / "storage"
RAW_BASE = ROOT / "storage" / "raw"


def _is_legacy_path(file_path: str) -> bool:
    """storage/raw/파일명 (슬래시 없음) 형태면 레거시."""
    if not (file_path or "").startswith("storage/raw/"):
        return False
    rest = file_path.replace("storage/raw/", "", 1)
    return "/" not in rest and len(rest) > 0


def run_migration(dry_run: bool = False) -> None:
    print("=" * 60)
    print("  [중요] 실행 전에 storage 폴더를 백업해 두세요.")
    print("  예: cp -r storage storage.backup.$(date +%Y%m%d)")
    print("=" * 60)
    if dry_run:
        print("(dry_run: 실제 이동/DB 변경 없이 시뮬레이션만 수행)\n")

    db: Session = SessionLocal()
    try:
        media_files = db.query(MediaFile).all()
        migrated = 0
        skipped = 0
        errors = []

        for mf in media_files:
            fp = (mf.file_path or "").strip()
            if not _is_legacy_path(fp):
                skipped += 1
                continue

            project_id = mf.project_id
            filename = Path(fp).name
            old_path = ROOT / fp
            new_dir = RAW_BASE / str(project_id)
            new_path = new_dir / filename
            new_file_path_str = f"storage/raw/{project_id}/{filename}"

            if not old_path.exists():
                errors.append(f"원본 없음 project_id={project_id} path={fp}")
                continue
            if new_path.exists() and new_path.resolve() == old_path.resolve():
                # 이미 같은 파일(심링크 등)
                if mf.file_path != new_file_path_str:
                    if not dry_run:
                        mf.file_path = new_file_path_str
                    migrated += 1
                continue
            if new_path.exists():
                errors.append(f"대상 이미 존재 project_id={project_id} new={new_path}")
                continue

            if dry_run:
                print(f"  [이동 예정] {fp} -> {new_file_path_str}")
                migrated += 1
                continue

            try:
                new_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old_path), str(new_path))
                mf.file_path = new_file_path_str
                migrated += 1
            except Exception as e:
                errors.append(f"이동 실패 {fp}: {e}")

        if not dry_run and migrated > 0:
            db.commit()

        print(f"처리: 이전 완료 {migrated}건, 스킵 {skipped}건")
        if errors:
            print("오류/경고:")
            for e in errors[:20]:
                print(f"  - {e}")
            if len(errors) > 20:
                print(f"  ... 외 {len(errors) - 20}건")
    finally:
        db.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv or "-n" in sys.argv
    run_migration(dry_run=dry)
