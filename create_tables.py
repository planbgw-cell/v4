#!/usr/bin/env python3
"""
Base.metadata에 등록된 모델로 PostgreSQL 테이블 생성.
실행: 프로젝트 루트에서 python create_tables.py
"""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from app.database import Base, engine
from app import models  # noqa: F401 - register models with Base.metadata

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    print("테이블 생성 완료: projects, media_files")
