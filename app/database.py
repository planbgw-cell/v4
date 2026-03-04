"""
SQLAlchemy 엔진 및 세션 설정.
.env의 DATABASE_URL을 사용하며, Supabase 등 다른 PostgreSQL 호스트로 전환 시 URL만 변경하면 됨.
"""
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://flairy_admin:flairy_secret@localhost:5432/flairy_v4")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=False,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def ensure_logs_column() -> None:
    """
    projects.logs 컬럼이 없을 경우 추가한다.
    PostgreSQL의 ALTER TABLE ... ADD COLUMN IF NOT EXISTS 사용.
    """
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS logs TEXT"))
    except Exception:
        # 컬럼 생성 실패는 렌더링을 막지 않도록 무시
        pass


def ensure_ai_progress_columns() -> None:
    """projects에 ai_total_count, ai_processed_count 컬럼이 없으면 추가."""
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS ai_total_count INTEGER NOT NULL DEFAULT 0"
            ))
            conn.execute(text(
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS ai_processed_count INTEGER NOT NULL DEFAULT 0"
            ))
    except Exception:
        pass


def get_db():
    """FastAPI 의존성용: 요청마다 세션 생성 후 종료 시 close."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
