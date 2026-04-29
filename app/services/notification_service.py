import logging
from uuid import UUID

logger = logging.getLogger(__name__)

MAGIC_LINK_ORIGIN = "http://121.133.47.184:8000"


def send_task_completion_alert(task_id: UUID | str, notify_target: str | None) -> None:
    """
    알림톡 연동 전 스텁.
    notify_target이 있을 때만 완료 알림 로그를 남긴다.
    """
    target = str(notify_target or "").strip()
    if not target:
        return
    task_id_str = str(task_id).strip()
    if not task_id_str:
        return
    magic_link = f"{MAGIC_LINK_ORIGIN}/?task_id={task_id_str}"
    logger.info("[알림 전송] 앨범 완성! 매직링크: %s (target=%s)", magic_link, target)
