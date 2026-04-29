import os
import time
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

_CACHE_TTL_SEC = 600
_user_storage_cache: dict[str, tuple[float, int]] = {}


def _safe_dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists() or not path.is_dir():
        return 0
    try:
        for root, _dirs, files in os.walk(path):
            for name in files:
                fp = Path(root) / name
                try:
                    total += fp.stat().st_size
                except OSError:
                    continue
    except OSError:
        return 0
    return total


def _storage_raw_root() -> Path:
    return Path(__file__).resolve().parents[2] / "storage" / "raw"


def invalidate_user_storage_cache(user_id: UUID | str) -> None:
    _user_storage_cache.pop(str(user_id), None)


def get_user_storage_usage_bytes(
    db: Session,
    user_id: UUID | str,
    *,
    force_refresh: bool = False,
    update_db: bool = True,
) -> int:
    key = str(user_id)
    now = time.time()
    if not force_refresh:
        cached = _user_storage_cache.get(key)
        if cached and (now - cached[0] <= _CACHE_TTL_SEC):
            return int(cached[1])

    rows = db.execute(
        text("SELECT id FROM projects WHERE user_id::text = :user_id"),
        {"user_id": key},
    ).mappings().all()
    raw_root = _storage_raw_root()
    total = 0
    for row in rows:
        total += _safe_dir_size_bytes(raw_root / str(row["id"]))

    _user_storage_cache[key] = (now, int(total))
    if update_db:
        db.execute(
            text(
                "UPDATE users "
                "SET storage_usage_bytes = :bytes "
                "WHERE id::text = :user_id"
            ),
            {"bytes": int(total), "user_id": key},
        )
    return int(total)

