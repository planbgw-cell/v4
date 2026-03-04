"""
프로젝트 및 MediaFiles 기본 CRUD.
JSONB ai_analysis 필드 읽기/쓰기 포함.
"""
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from app.models import MediaFile, Project, ProjectMode


# ---------- Projects ----------


def create_project(
    db: Session,
    title: str,
    mode: ProjectMode = ProjectMode.AI,
    status: str = "PENDING",
) -> Project:
    """새 프로젝트 생성."""
    project = Project(title=title, mode=mode, status=status)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def get_project(db: Session, project_id: UUID) -> Optional[Project]:
    """프로젝트 단건 조회 (관련 media_files 포함)."""
    return db.query(Project).options(joinedload(Project.media_files)).filter(Project.id == project_id).first()


def update_project_status(db: Session, project_id: UUID, status: str) -> Optional[Project]:
    """프로젝트 status 업데이트 (Mock/실제 파이프라인용)."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return None
    project.status = status
    db.commit()
    db.refresh(project)
    return project


def update_project_output_path(db: Session, project_id: UUID, output_path: str) -> Optional[Project]:
    """프로젝트 output_path 업데이트 (렌더 완료 시)."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return None
    project.output_path = output_path
    db.commit()
    db.refresh(project)
    return project


def update_project_ai_progress(
    db: Session,
    project_id: UUID,
    total: Optional[int] = None,
    processed_increment: Optional[int] = None,
) -> Optional[Project]:
    """AI 분석 진행률 업데이트. total 설정 및/또는 ai_processed_count 증가 후 즉시 커밋."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return None
    if total is not None:
        project.ai_total_count = total
    if processed_increment is not None:
        project.ai_processed_count = (project.ai_processed_count or 0) + processed_increment
    db.commit()
    db.refresh(project)
    return project


# ---------- MediaFiles ----------


def create_media_file(
    db: Session,
    project_id: UUID,
    file_path: str,
    file_type: str,
    order_index: int = 0,
    ai_analysis: Optional[dict[str, Any]] = None,
    is_selected: bool = True,
) -> MediaFile:
    """MediaFile 추가. ai_analysis는 JSONB에 저장."""
    m = MediaFile(
        project_id=project_id,
        file_path=file_path,
        file_type=file_type,
        order_index=order_index,
        ai_analysis=ai_analysis,
        is_selected=is_selected,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def update_media_file_ai_analysis(
    db: Session,
    media_file_id: int,
    ai_analysis: dict[str, Any],
) -> Optional[MediaFile]:
    """MediaFile의 ai_analysis(JSONB) 업데이트."""
    m = db.query(MediaFile).filter(MediaFile.id == media_file_id).first()
    if not m:
        return None
    m.ai_analysis = ai_analysis
    db.commit()
    db.refresh(m)
    return m


def update_media_file_is_selected(
    db: Session,
    media_file_id: int,
    is_selected: bool,
) -> Optional[MediaFile]:
    """MediaFile의 is_selected(Curate 결과) 업데이트."""
    m = db.query(MediaFile).filter(MediaFile.id == media_file_id).first()
    if not m:
        return None
    m.is_selected = is_selected
    db.commit()
    db.refresh(m)
    return m


def update_media_file_dimensions(
    db: Session,
    media_file_id: int,
    width: int | None,
    height: int | None,
) -> Optional[MediaFile]:
    """MediaFile의 width/height(물리 회전 후 규격) 업데이트."""
    m = db.query(MediaFile).filter(MediaFile.id == media_file_id).first()
    if not m:
        return None
    m.width = width
    m.height = height
    db.commit()
    db.refresh(m)
    return m


def get_media_files_by_project(db: Session, project_id: UUID) -> list[MediaFile]:
    """프로젝트별 MediaFile 목록 (order_index 순)."""
    return (
        db.query(MediaFile)
        .filter(MediaFile.project_id == project_id)
        .order_by(MediaFile.order_index)
        .all()
    )


def get_media_file(db: Session, media_file_id: int) -> Optional[MediaFile]:
    """MediaFile 단건 조회."""
    return db.query(MediaFile).filter(MediaFile.id == media_file_id).first()
