"""
기존 프로젝트에 대해 앨범 레이아웃(album_layout.json)만 생성하는 CLI.
하이라이트 영상 생성(rerender_project.py)과 동일한 사용 방식.

사용: .venv/bin/python scripts/generate_album.py <project_id> [--force]

- project_id: DB에 있고 storage/raw/{project_id}/ 에 미디어가 있는 프로젝트.
- project_type이 video인 프로젝트에 쓰려면 --force (앨범 레이아웃만 생성, DB project_type은 변경 안 함).
- 성공 시 storage/final/{project_id}/album_layout.json 생성 및 DB output_path·COMPLETED 갱신.
"""
import logging
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.crud import get_project, update_project_output_path, update_project_status
from app.database import SessionLocal
from app.storage import get_project_final_dir
from engine.album_engine import build_layout, save_album_layout

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    force = "--force" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--force"]
    if len(args) < 1:
        print("Usage: python scripts/generate_album.py <project_id> [--force]")
        print("  --force  project_type이 video여도 앨범 레이아웃만 생성 (DB project_type 미변경)")
        sys.exit(1)
    project_id_str = args[0].strip()
    try:
        project_id = UUID(project_id_str)
    except ValueError:
        print("Invalid project_id:", project_id_str)
        sys.exit(1)

    db = SessionLocal()
    try:
        project = get_project(db, project_id)
    finally:
        db.close()
    if not project:
        print("Project not found:", project_id_str)
        sys.exit(1)

    project_type = getattr(project, "project_type", None) or "video"
    if project_type != "album" and not force:
        print(
            f"Project {project_id_str} has project_type={project_type!r}. "
            "Use --force to generate album layout anyway (project_type unchanged)."
        )
        sys.exit(1)

    media_files = getattr(project, "media_files", None) or []
    sorted_media = sorted(media_files, key=lambda m: getattr(m, "order_index", 0))
    media_list = [
        {
            "file_path": getattr(m, "file_path", "") or "",
            "file_type": getattr(m, "file_type", "image") or "image",
            "width": getattr(m, "width", None),
            "height": getattr(m, "height", None),
        }
        for m in sorted_media
    ]
    if not media_list:
        print("No media files for project:", project_id_str)
        sys.exit(1)

    title = getattr(project, "title", None) or "디지털 앨범"
    logger.info("앨범 레이아웃 구성 중: project_id=%s (VideoEngine 미호출)", project_id_str)
    layout = build_layout(media_list, title, project_id=str(project_id))
    final_dir = get_project_final_dir(project_id, base_dir=ROOT)
    final_dir.mkdir(parents=True, exist_ok=True)
    out_path = save_album_layout(layout, final_dir)
    output_path_str = str(Path("storage") / "final" / str(project_id) / "album_layout.json")

    db = SessionLocal()
    try:
        update_project_output_path(db, project_id, output_path_str)
        update_project_status(db, project_id, "COMPLETED")
    finally:
        db.close()

    print("OK: album layout written to", out_path)
    print("Viewer: http://127.0.0.1:8000/viewer/album/" + project_id_str)


if __name__ == "__main__":
    main()
