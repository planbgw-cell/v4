"""
특정 프로젝트를 서버 원본 파일로 같은 방식(1+N, xfade) 재렌더링 테스트.
사용: .venv/bin/python scripts/rerender_project.py <project_id>
"""
import logging
import sys
from pathlib import Path
from uuid import UUID

# v4를 루트로
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.crud import get_project, update_project_output_path, update_project_status
from app.database import SessionLocal
from engine.video_engine import FlairyVideoEngine

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _is_ai_mode(project) -> bool:
    if not project or not getattr(project, "mode", None):
        return False
    m = project.mode
    if hasattr(m, "value"):
        return (m.value or "") == "ai"
    return m == "ai"


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/rerender_project.py <project_id>")
        sys.exit(1)
    project_id_str = sys.argv[1].strip()
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

    use_ai = _is_ai_mode(project)
    print(f"Project: {project_id}, mode={getattr(project.mode, 'value', project.mode)}, use_ai={use_ai}")
    media_count = len(getattr(project, "media_files", []) or [])
    selected = len([m for m in (project.media_files or []) if getattr(m, "is_selected", True)])
    print(f"Media: {media_count} total, {selected} selected")

    engine = FlairyVideoEngine(project_id, ROOT)
    print("Starting create_highlight (1+N, xfade)...")
    final_path = engine.create_highlight(use_ai=use_ai)
    if final_path is None:
        print("FAILED: create_highlight returned None")
        db = SessionLocal()
        try:
            update_project_status(db, project_id, "FAILED")
        finally:
            db.close()
        sys.exit(1)

    output_path_str = str(Path("storage") / "final" / str(project_id) / "output.mp4")
    db = SessionLocal()
    try:
        update_project_output_path(db, project_id, output_path_str)
        update_project_status(db, project_id, "COMPLETED")
    finally:
        db.close()
    print("OK: output", final_path)
    print("Viewer: http://127.0.0.1:8000/viewer/" + project_id_str)


if __name__ == "__main__":
    main()
