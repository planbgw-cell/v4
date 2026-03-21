"""
프로젝트 및 MediaFiles 기본 CRUD.
JSONB ai_analysis 필드 읽기/쓰기 포함.
"""
from typing import Any, Optional, Union
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from app.models import MediaFile, Project, ProjectMode, User


# ---------- Users ----------


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """이메일로 유저 조회."""
    return db.query(User).filter(User.email == email).first()


def get_user_by_id(db: Session, user_id: UUID) -> Optional[User]:
    """ID로 유저 조회."""
    return db.query(User).filter(User.id == user_id).first()


def create_user(
    db: Session,
    email: str,
    hashed_password: str | None,
    provider: str = "local",
) -> User:
    """유저 생성 (회원가입)."""
    user = User(email=email, hashed_password=hashed_password, provider=provider)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------- Projects ----------


def create_project(
    db: Session,
    title: str,
    mode: ProjectMode = ProjectMode.AI,
    status: str = "PENDING",
    project_type: str = "video",
) -> Project:
    """새 프로젝트 생성."""
    project = Project(title=title, mode=mode, status=status, project_type=project_type)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def get_project(db: Session, project_id: UUID) -> Optional[Project]:
    """프로젝트 단건 조회 (관련 media_files 포함)."""
    return db.query(Project).options(joinedload(Project.media_files)).filter(Project.id == project_id).first()


def claim_project(db: Session, project_id: UUID, user_id: UUID) -> Optional[Project]:
    """게스트 프로젝트를 로그인 사용자 소유로 변경. user_id가 이미 있으면 변경하지 않고 그대로 반환."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return None
    if project.user_id is not None:
        return project
    project.user_id = user_id
    db.commit()
    db.refresh(project)
    return project


def get_projects_by_user_id(db: Session, user_id: UUID) -> list[Project]:
    """로그인 유저의 프로젝트 목록. created_at 내림차순."""
    return (
        db.query(Project)
        .options(joinedload(Project.media_files))
        .filter(Project.user_id == user_id)
        .order_by(Project.created_at.desc())
        .all()
    )


def delete_project(db: Session, project_id: UUID) -> bool:
    """프로젝트 삭제(DB만). 소유 확인은 호출부에서. 성공 시 True, 없으면 False."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return False
    db.delete(project)
    db.commit()
    return True


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


def update_project_ai_narrative_order(
    db: Session,
    project_id: UUID,
    order_data: Optional[Union[list[int], dict[str, float]]],
) -> Optional[Project]:
    """AI 하이라이트 서사 데이터 저장. dict[str,float]=가중치(권장), list[int]=구버전 순서. None이면 초기화."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return None
    project.ai_narrative_order = order_data
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
