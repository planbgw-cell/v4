#!/usr/bin/env python3
"""
스키마 생성 및 JSONB 입출력 검증.
- 테이블 생성 (projects, media_files)
- 프로젝트 생성 후 MediaFile에 ai_analysis(JSON) 저장/조회
실행: 프로젝트 루트에서 python test_db_schema.py
"""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from app.database import Base, SessionLocal, engine
from app import models  # noqa: F401
from app.models import ProjectMode
from app.crud import create_project, create_media_file, get_project, get_media_files_by_project


def main():
    # 1) 테이블 생성
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # 2) 프로젝트 생성
        project = create_project(db, title="JSONB 테스트 프로젝트", mode=ProjectMode.AI)
        project_id = project.id

        # 3) MediaFile에 ai_analysis(JSON) 삽입
        sample_analysis = {
            "model": "gemini-1.5-flash",
            "summary": "바다와 하늘",
            "tags": ["landscape", "ocean"],
            "confidence": 0.92,
        }
        media = create_media_file(
            db,
            project_id=project_id,
            file_path=f"storage/raw/{project_id}/sample.jpg",
            file_type="image",
            order_index=0,
            ai_analysis=sample_analysis,
        )

        # 4) 조회하여 JSON 일치 여부 검증
        loaded = get_media_files_by_project(db, project_id)
        if not loaded:
            print("FAIL: MediaFile 조회 없음")
            return 1
        m = loaded[0]
        if m.ai_analysis != sample_analysis:
            print("FAIL: ai_analysis JSON 불일치")
            print("  기대:", sample_analysis)
            print("  실제:", m.ai_analysis)
            return 1

        # 5) relationship으로 프로젝트 조회 시 미디어 포함 여부
        proj = get_project(db, project_id)
        if not proj or len(proj.media_files) != 1:
            print("FAIL: 프로젝트 조회 또는 media_files 관계 없음")
            return 1

        print("스키마 생성 및 JSONB 입출력 테스트 성공")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
