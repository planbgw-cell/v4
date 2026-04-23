import logging
from urllib.parse import quote
from uuid import UUID

logger = logging.getLogger(__name__)

MAGIC_LINK_ORIGIN = "http://121.133.47.184:8000"


def _build_magic_link(task_id: UUID | str) -> str:
    return f"{MAGIC_LINK_ORIGIN}/?task_id={quote(str(task_id))}"


def send_task_completion_alert(task_id: UUID | str, notify_target: str | None) -> None:
    """알림톡 연동 전 스텁. notify_target이 있을 때만 완료 알림 로그를 남긴다."""
    target = str(notify_target or "").strip()
    if not target:
        return
    magic_link = _build_magic_link(task_id)
    logger.info("[알림 전송] 앨범 완성! 매직링크: %s (target=%s)", magic_link, target)
