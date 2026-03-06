"""
Flairy v4.0 DB 모델.
PostgreSQL 15 / Supabase 호환. UUID, JSONB 사용.
"""
import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


class ProjectMode(str, enum.Enum):
    AI = "ai"
    RULE_BASED = "rule_based"


class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    mode = Column(Enum(ProjectMode), nullable=False)
    status = Column(String(50), nullable=False, default="PENDING")
    project_type = Column(String(50), nullable=False, default="video")
    output_path = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    logs = Column(Text, nullable=True)
    ai_total_count = Column(Integer, default=0, nullable=False)
    ai_processed_count = Column(Integer, default=0, nullable=False)

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
    is_selected = Column(Boolean, default=True, nullable=False)
    # 물리 회전(Physical Baking) 후 규격. AI 전처리에서 exif_transpose 적용 후 측정한 width/height
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)

    project = relationship("Project", back_populates="media_files")
