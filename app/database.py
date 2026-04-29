"""
SQLAlchemy 엔진 및 세션 설정.
.env의 DATABASE_URL으로 로컬 PostgreSQL 15 연결.
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


def ensure_project_type_column() -> None:
    """projects에 project_type 컬럼이 없으면 추가. 기존 행에는 DEFAULT 'video' 적용."""
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS project_type VARCHAR(50) NOT NULL DEFAULT 'video'"
            ))
    except Exception:
        pass


def ensure_ai_narrative_order_column() -> None:
    """projects에 ai_narrative_order(JSONB, 서사 가중치 dict 또는 구버전 순서 list)가 없으면 추가."""
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS ai_narrative_order JSONB"
            ))
    except Exception:
        pass


def ensure_user_id_column() -> None:
    """projects에 user_id FK 컬럼이 없으면 추가 (users 테이블 선행 필요)."""
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL"
            ))
    except Exception:
        pass


def ensure_video_tasks_table() -> None:
    """video_tasks 테이블/컬럼/인덱스를 보장한다."""
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS video_tasks (
                    task_id UUID PRIMARY KEY,
                    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
                    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
                    guest_token VARCHAR(64) NOT NULL,
                    notify_target VARCHAR(255),
                    current_msg VARCHAR(255) NOT NULL DEFAULT '작업 준비 중...',
                    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
                    task_type VARCHAR(50) NOT NULL DEFAULT 'VIDEO_AI',
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """))
            conn.execute(text(
                "ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS notify_target VARCHAR(255)"
            ))
            conn.execute(text(
                "ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS current_msg VARCHAR(255) NOT NULL DEFAULT '작업 준비 중...'"
            ))
            conn.execute(text(
                "ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS status VARCHAR(50) NOT NULL DEFAULT 'PENDING'"
            ))
            conn.execute(text(
                "ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS task_type VARCHAR(50) NOT NULL DEFAULT 'VIDEO_AI'"
            ))
            conn.execute(text(
                "ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ"
            ))
            conn.execute(text(
                "UPDATE video_tasks SET expires_at = now() + interval '48 hour' WHERE expires_at IS NULL"
            ))
            conn.execute(text(
                "ALTER TABLE video_tasks ALTER COLUMN expires_at SET NOT NULL"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_video_tasks_guest_token ON video_tasks (guest_token)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_video_tasks_expires_at ON video_tasks (expires_at)"
            ))
    except Exception:
        pass


def ensure_admin_users_table() -> None:
    """admin_users 테이블/인덱스를 보장한다."""
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS admin_users (
                    id UUID PRIMARY KEY,
                    username VARCHAR(64) NOT NULL UNIQUE,
                    hashed_password VARCHAR(255) NOT NULL,
                    role VARCHAR(50) NOT NULL DEFAULT 'super_admin',
                    last_login TIMESTAMPTZ NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_admin_users_username ON admin_users (username)"
            ))
    except Exception:
        pass


def ensure_board_tables() -> None:
    """공지/문의 테이블 및 인덱스를 보장한다."""
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS board_notices (
                    id UUID PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    content TEXT NOT NULL,
                    is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
                    view_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS board_inquiries (
                    id UUID PRIMARY KEY,
                    user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
                    guest_token VARCHAR(64) NULL,
                    title VARCHAR(255) NOT NULL,
                    content TEXT NOT NULL,
                    is_secret BOOLEAN NOT NULL DEFAULT FALSE,
                    answer_content TEXT NULL,
                    answered_at TIMESTAMPTZ NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_board_notices_pinned_created ON board_notices (is_pinned DESC, created_at DESC)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_board_inquiries_status_created ON board_inquiries (status, created_at DESC)"
            ))
    except Exception:
        pass


def ensure_users_table_addons() -> None:
    """users 테이블의 관리자 운영용 보조 컬럼을 보장한다."""
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE"
            ))
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ NULL"
            ))
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS storage_usage_bytes BIGINT NOT NULL DEFAULT 0"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_users_is_active_created ON users (is_active, created_at DESC)"
            ))
    except Exception:
        pass


def ensure_admin_action_logs_table() -> None:
    """관리자 감사 로그 테이블/인덱스를 보장한다."""
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS admin_action_logs (
                    id UUID PRIMARY KEY,
                    admin_id UUID NULL REFERENCES admin_users(id) ON DELETE SET NULL,
                    action_type VARCHAR(50) NOT NULL,
                    target_id VARCHAR(100) NOT NULL,
                    details JSONB NULL,
                    ip_address VARCHAR(64) NULL,
                    user_agent VARCHAR(512) NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """))
            conn.execute(text(
                "ALTER TABLE admin_action_logs ADD COLUMN IF NOT EXISTS ip_address VARCHAR(64)"
            ))
            conn.execute(text(
                "ALTER TABLE admin_action_logs ADD COLUMN IF NOT EXISTS user_agent VARCHAR(512)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_admin_action_logs_created_at ON admin_action_logs (created_at DESC)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_admin_action_logs_admin_id ON admin_action_logs (admin_id, created_at DESC)"
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
