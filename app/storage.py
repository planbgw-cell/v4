"""
프로젝트 단위 스토리지 경로 및 삭제 유틸.
storage/raw/{project_id}/, storage/final/{project_id}/, storage/temp/{project_id}/
"""
import logging
import shutil
from pathlib import Path
from uuid import UUID

logger = logging.getLogger(__name__)


def get_storage_root() -> Path:
    """v4 프로젝트 루트 (storage 상위)."""
    return Path(__file__).resolve().parent.parent


def get_project_raw_dir(project_id: UUID, base_dir: Path | None = None) -> Path:
    """storage/raw/{project_id}/ 경로."""
    root = base_dir or get_storage_root()
    return root / "storage" / "raw" / str(project_id)


def get_project_final_dir(project_id: UUID, base_dir: Path | None = None) -> Path:
    """storage/final/{project_id}/ 경로."""
    root = base_dir or get_storage_root()
    return root / "storage" / "final" / str(project_id)


def get_project_temp_dir(project_id: UUID, base_dir: Path | None = None) -> Path:
    """storage/temp/{project_id}/ 경로."""
    root = base_dir or get_storage_root()
    return root / "storage" / "temp" / str(project_id)


def delete_project_storage(project_id: UUID, base_dir: Path | None = None) -> None:
    """
    프로젝트 삭제 시 해당 project_id의 raw/final/temp 폴더를 안전하게 삭제.
    폴더가 없어도 예외를 던지지 않음.
    """
    root = base_dir or get_storage_root()
    for name, dir_path in [
        ("raw", root / "storage" / "raw" / str(project_id)),
        ("final", root / "storage" / "final" / str(project_id)),
        ("temp", root / "storage" / "temp" / str(project_id)),
    ]:
        if dir_path.exists() and dir_path.is_dir():
            try:
                shutil.rmtree(dir_path)
                logger.info("프로젝트 스토리지 삭제: %s (%s)", project_id, name)
            except OSError as e:
                logger.warning("프로젝트 스토리지 삭제 실패 %s %s: %s", project_id, name, e)
