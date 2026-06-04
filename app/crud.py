"""
프로젝트/태스크 및 MediaFiles 기본 CRUD.
JSONB ai_analysis 필드 읽기/쓰기 포함.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, TypedDict, Union
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models import MediaFile, Project, ProjectMode, User, VideoTask, VisitorLog, VisitorSession


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


def count_projects_for_owner(
    db: Session,
    *,
    user_id: UUID | None = None,
    guest_token: str | None = None,
) -> int:
    """
    베타 쿼터용 프로젝트 수.
    회원: projects.user_id 또는 video_tasks.user_id로 연결된 distinct project.
    비회원: video_tasks.guest_token 기준 distinct project_id.
    """
    if user_id is not None:
        owned_ids = {
            row[0]
            for row in db.query(Project.id).filter(Project.user_id == user_id).all()
        }
        task_project_ids = {
            row[0]
            for row in db.query(VideoTask.project_id)
            .filter(
                VideoTask.user_id == user_id,
                VideoTask.project_id.isnot(None),
            )
            .distinct()
            .all()
            if row[0] is not None
        }
        return len(owned_ids | task_project_ids)

    token = (guest_token or "").strip()
    if not token:
        return 0
    return int(
        db.query(func.count(func.distinct(VideoTask.project_id)))
        .filter(
            VideoTask.guest_token == token,
            VideoTask.project_id.isnot(None),
        )
        .scalar()
        or 0
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
    processing_status: str = "PENDING",
    is_selected: bool = True,
) -> MediaFile:
    """MediaFile 추가. ai_analysis는 JSONB에 저장."""
    m = MediaFile(
        project_id=project_id,
        file_path=file_path,
        file_type=file_type,
        order_index=order_index,
        ai_analysis=ai_analysis,
        processing_status=processing_status,
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


class ProjectMediaReadiness(TypedDict):
    """프로젝트 미디어 트랜스코딩·준비 상태 요약."""

    is_media_ready: bool
    has_media_failure: bool
    pending_count: int
    failed_count: int
    total_count: int


def get_project_media_readiness(db: Session, project_id: UUID) -> ProjectMediaReadiness:
    """모든 파일이 READY일 때만 is_media_ready. 미디어 없음은 준비 안 됨으로 간주."""
    rows = get_media_files_by_project(db, project_id)
    if not rows:
        return ProjectMediaReadiness(
            is_media_ready=False,
            has_media_failure=False,
            pending_count=0,
            failed_count=0,
            total_count=0,
        )
    pending = 0
    failed = 0
    for m in rows:
        s = (m.processing_status or "").strip().upper()
        if s == "FAILED":
            failed += 1
        elif s != "READY":
            pending += 1
    return ProjectMediaReadiness(
        is_media_ready=(pending == 0 and failed == 0),
        has_media_failure=(failed > 0),
        pending_count=pending,
        failed_count=failed,
        total_count=len(rows),
    )


def get_media_file(db: Session, media_file_id: int) -> Optional[MediaFile]:
    """MediaFile 단건 조회."""
    return db.query(MediaFile).filter(MediaFile.id == media_file_id).first()


def update_media_file_processing_status(
    db: Session,
    media_file_id: int,
    processing_status: str,
) -> Optional[MediaFile]:
    """MediaFile의 처리 상태를 업데이트."""
    m = db.query(MediaFile).filter(MediaFile.id == media_file_id).first()
    if not m:
        return None
    m.processing_status = processing_status
    db.commit()
    db.refresh(m)
    return m


# ---------- VideoTasks ----------


def create_video_task(
    db: Session,
    *,
    guest_token: str,
    user_id: UUID | None = None,
    project_id: UUID | None = None,
    notify_target: str | None = None,
    status: str = "PENDING",
    task_type: str = "VIDEO_AI",
    current_msg: str = "작업 준비 중...",
) -> VideoTask:
    task = VideoTask(
        guest_token=guest_token,
        user_id=user_id,
        project_id=project_id,
        notify_target=notify_target,
        status=status,
        task_type=task_type,
        current_msg=current_msg,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=48),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def attach_video_task_project(db: Session, task_id: UUID, project_id: UUID) -> Optional[VideoTask]:
    task = db.query(VideoTask).filter(VideoTask.task_id == task_id).first()
    if not task:
        return None
    task.project_id = project_id
    db.commit()
    db.refresh(task)
    return task


def mark_video_task_status(
    db: Session,
    task_id: UUID,
    *,
    status: str | None = None,
    current_msg: str | None = None,
) -> Optional[VideoTask]:
    task = db.query(VideoTask).filter(VideoTask.task_id == task_id).first()
    if not task:
        return None
    if status is not None:
        task.status = status
    if current_msg is not None:
        task.current_msg = current_msg
    db.commit()
    db.refresh(task)
    return task


def get_video_task(db: Session, task_id: UUID) -> Optional[VideoTask]:
    return db.query(VideoTask).filter(VideoTask.task_id == task_id).first()


def get_video_task_any(db: Session, task_id: UUID) -> Optional[VideoTask]:
    """만료 여부와 무관하게 task를 조회한다."""
    return get_video_task(db, task_id)


def get_video_task_active(db: Session, task_id: UUID) -> Optional[VideoTask]:
    """만료되지 않은 task만 조회한다."""
    now = datetime.now(timezone.utc)
    return (
        db.query(VideoTask)
        .filter(VideoTask.task_id == task_id)
        .filter(VideoTask.expires_at > now)
        .first()
    )


def get_latest_video_task_by_project(
    db: Session,
    project_id: UUID,
    include_expired: bool = False,
) -> Optional[VideoTask]:
    q = db.query(VideoTask).filter(VideoTask.project_id == project_id)
    if not include_expired:
        q = q.filter(VideoTask.expires_at > datetime.now(timezone.utc))
    return q.order_by(VideoTask.created_at.desc()).first()


def update_video_task_notify(
    db: Session,
    task_id: UUID,
    notify_target: str,
) -> Optional[VideoTask]:
    task = db.query(VideoTask).filter(VideoTask.task_id == task_id).first()
    if not task:
        return None
    task.notify_target = notify_target
    db.commit()
    db.refresh(task)
    return task


def claim_video_task(
    db: Session,
    *,
    task_id: UUID,
    user_id: UUID,
) -> Optional[VideoTask]:
    """
    Task를 현재 유저에게 귀속하고, 연결된 프로젝트 소유자도 함께 이전한다.
    이미 다른 유저 소유인 task/project면 변경하지 않고 기존 레코드를 반환한다.
    """
    task = db.query(VideoTask).filter(VideoTask.task_id == task_id).first()
    if not task:
        return None

    if task.user_id is not None and task.user_id != user_id:
        return task

    project = None
    if task.project_id:
        project = db.query(Project).filter(Project.id == task.project_id).first()
        if project and project.user_id is not None and project.user_id != user_id:
            return task

    task.user_id = user_id
    task.guest_token = ""
    if project and (project.user_id is None or project.user_id == user_id):
        project.user_id = user_id

    db.commit()
    db.refresh(task)
    return task


def upsert_visitor_session(
    db: Session,
    *,
    session_id: str,
    inflow_channel: str,
    landing_page: str | None,
    referrer_url: str | None,
    utm_source: str | None,
    utm_medium: str | None,
    utm_campaign: str | None,
    utm_term: str | None,
    utm_content: str | None,
    device_type: str,
    os_name: str,
    browser_name: str,
    ip_hash: str | None,
) -> VisitorSession:
    row = db.query(VisitorSession).filter(VisitorSession.session_id == session_id).first()
    if row is None:
        row = VisitorSession(
            session_id=session_id,
            latest_inflow_channel=inflow_channel,
            landing_page=landing_page,
            referrer_url=referrer_url,
            utm_source=utm_source,
            utm_medium=utm_medium,
            utm_campaign=utm_campaign,
            utm_term=utm_term,
            utm_content=utm_content,
            device_type=device_type,
            os_name=os_name,
            browser_name=browser_name,
            ip_hash=ip_hash,
        )
        db.add(row)
    else:
        row.last_active_at = datetime.now(timezone.utc)
        row.latest_inflow_channel = inflow_channel or row.latest_inflow_channel
        row.landing_page = landing_page or row.landing_page
        row.referrer_url = referrer_url or row.referrer_url
        row.utm_source = utm_source or row.utm_source
        row.utm_medium = utm_medium or row.utm_medium
        row.utm_campaign = utm_campaign or row.utm_campaign
        row.utm_term = utm_term or row.utm_term
        row.utm_content = utm_content or row.utm_content
        row.device_type = device_type or row.device_type
        row.os_name = os_name or row.os_name
        row.browser_name = browser_name or row.browser_name
        row.ip_hash = ip_hash or row.ip_hash
    db.commit()
    db.refresh(row)
    return row


def create_visitor_log(
    db: Session,
    *,
    session_id: str,
    inflow_channel: str,
    referrer_url: str | None,
    landing_page: str | None,
    utm_source: str | None,
    utm_medium: str | None,
    utm_campaign: str | None,
    utm_term: str | None,
    utm_content: str | None,
    ip_hash: str | None,
    user_agent: str | None,
    device_type: str,
    os_name: str,
    browser_name: str,
) -> VisitorLog:
    row = VisitorLog(
        session_id=session_id,
        inflow_channel=inflow_channel,
        referrer_url=referrer_url,
        landing_page=landing_page,
        utm_source=utm_source,
        utm_medium=utm_medium,
        utm_campaign=utm_campaign,
        utm_term=utm_term,
        utm_content=utm_content,
        ip_hash=ip_hash,
        user_agent=user_agent,
        device_type=device_type,
        os_name=os_name,
        browser_name=browser_name,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def add_session_stay_duration(db: Session, *, session_id: str, duration_seconds: int) -> VisitorSession | None:
    row = db.query(VisitorSession).filter(VisitorSession.session_id == session_id).first()
    if row is None:
        return None
    row.total_stay_duration = int(row.total_stay_duration or 0) + max(0, int(duration_seconds))
    row.last_active_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def mark_session_signup_conversion(db: Session, *, session_id: str) -> VisitorSession | None:
    row = db.query(VisitorSession).filter(VisitorSession.session_id == session_id).first()
    if row is None:
        return None
    row.is_converted_signup = True
    row.last_active_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def mark_session_video_conversion(db: Session, *, session_id: str) -> VisitorSession | None:
    row = db.query(VisitorSession).filter(VisitorSession.session_id == session_id).first()
    if row is None:
        return None
    row.is_converted_video = True
    row.last_active_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row
