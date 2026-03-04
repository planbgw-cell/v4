#!/usr/bin/env python3
"""
database.py를 사용해 DB 연결이 성공하는지 확인하는 스크립트.
실행: 프로젝트 루트(v4/)에서 python app/test_db_conn.py 또는 python -m app.test_db_conn
"""
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가 (v4/)
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from sqlalchemy import text
from app.database import engine


def main():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("DB 연결 성공")
        return 0
    except Exception as e:
        print("DB 연결 실패:", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
