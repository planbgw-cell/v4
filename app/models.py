"""
Flairy v4.0 DB 모델.
PostgreSQL 15. UUID, JSONB 사용. SQLAlchemy + 로컬 PostgreSQL.
"""
import enum
import uuid

from datetime import datetime, timedelta, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


class ProjectMode(str, enum.Enum):
    AI = "ai"
    RULE_BASED = "rule_based"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=True)  # 소셜 로그인 시 null
    provider = Column(String(20), nullable=False, default="local")  # local | google | kakao
    is_active = Column(Boolean, nullable=False, default=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    storage_usage_bytes = Column(BigInteger, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    projects = relationship("Project", back_populates="user")


class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    title = Column(String(255), nullable=False)
    mode = Column(Enum(ProjectMode), nullable=False)
    status = Column(String(50), nullable=False, default="PENDING")
    project_type = Column(String(50), nullable=False, default="video")
    output_path = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    logs = Column(Text, nullable=True)
    ai_total_count = Column(Integer, default=0, nullable=False)
    ai_processed_count = Column(Integer, default=0, nullable=False)
    # AI 하이라이트: 서사 가중치. JSONB dict[str, float] id→narrative_weight(0~10). 구버전 list[int] 순서만 허용(호환).
    ai_narrative_order = Column(JSONB, nullable=True)

    user = relationship("User", back_populates="projects")
    media_files = relationship("MediaFile", back_populates="project", cascade="all, delete-orphan")


class MediaFile(Base):
    __tablename__ = "media_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_path = Column(String(512), nullable=False)
    file_type = Column(String(50), nullable=False)
    order_index = Column(Integer, nullable=False, default=0)
    ai_analysis = Column(JSONB, nullable=True)
    processing_status = Column(String(20), nullable=False, default="PENDING")
    is_selected = Column(Boolean, default=True, nullable=False)
    # 물리 회전(Physical Baking) 후 규격. AI 전처리에서 exif_transpose 적용 후 측정한 width/height
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)

    project = relationship("Project", back_populates="media_files")


def _default_expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=48)


class VideoTask(Base):
    __tablename__ = "video_tasks"

    task_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    guest_token = Column(String(64), nullable=False, index=True)
    notify_target = Column(String(255), nullable=True)
    current_msg = Column(String(255), nullable=False, default="작업 준비 중...")
    status = Column(String(50), nullable=False, default="PENDING")
    task_type = Column(String(50), nullable=False, default="VIDEO_AI")
    expires_at = Column(DateTime(timezone=True), nullable=False, default=_default_expires_at)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(64), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="super_admin")
    last_login = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AdminActionLog(Base):
    __tablename__ = "admin_action_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admin_id = Column(UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)
    action_type = Column(String(50), nullable=False)
    target_id = Column(String(100), nullable=False)
    details = Column(JSONB, nullable=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Notice(Base):
    __tablename__ = "board_notices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    is_pinned = Column(Boolean, nullable=False, default=False)
    view_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Inquiry(Base):
    __tablename__ = "board_inquiries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    guest_token = Column(String(64), nullable=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    is_secret = Column(Boolean, nullable=False, default=False)
    answer_content = Column(Text, nullable=True)
    answered_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), nullable=False, default="PENDING")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
