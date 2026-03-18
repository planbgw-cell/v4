"""
프로젝트의 영상 생성 로그(project.logs)를 출력.
사용: python scripts/show_project_logs.py <project_id>
"""
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.crud import get_project
from app.database import SessionLocal


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/show_project_logs.py <project_id>")
        return 1
    project_id_str = sys.argv[1].strip()
    try:
        project_id = UUID(project_id_str)
    except ValueError:
        print("Invalid project_id:", project_id_str)
        return 1

    db = SessionLocal()
    try:
        project = get_project(db, project_id)
    finally:
        db.close()

    if not project:
        print("Project not found:", project_id_str)
        return 1

    logs = getattr(project, "logs", None) or ""
    mode = getattr(getattr(project, "mode", None), "value", None) or getattr(project, "mode", None)
    print("Project:", project_id_str)
    print("Mode:", mode)
    print("Status:", getattr(project, "status", None))
    print("--- LOGS ---")
    print(logs if logs else "(empty)")
    print("--- END ---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
