"""
Redis 워크벤치 알림 발행 (통일 포맷).

Redis 이벤트 type 필드는 BE NotificationType Enum 명칭과 대소문자까지 정확히 일치.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# BE NotificationType Enum 명칭 (type 필드 값, 대소문자 일치)
NOTIFICATION_TYPE_ANALYSIS_STARTED = "ANALYSIS_STARTED"
NOTIFICATION_TYPE_AI_DETECT = "AI_DETECT"
NOTIFICATION_TYPE_RAG_STATUS = "RAG_STATUS"
NOTIFICATION_TYPE_CASE_ACTION = "CASE_ACTION"

NOTIFICATION_CATEGORY_AI_DETECT = NOTIFICATION_TYPE_AI_DETECT
NOTIFICATION_CATEGORY_RAG_STATUS = NOTIFICATION_TYPE_RAG_STATUS
NOTIFICATION_CATEGORY_CASE_ACTION = NOTIFICATION_TYPE_CASE_ACTION

# 백엔드 구독 채널과 토씨 하나 틀리지 않게 일치 (core/config.py 기본값과 동일)
REDIS_CHANNEL_WORKBENCH_ALERT = "workbench:alert"
REDIS_CHANNEL_WORKBENCH_RAG_STATUS = "workbench:rag:status"
REDIS_CHANNEL_WORKBENCH_CASE_ACTION = "workbench:case:action"


def build_notification_payload(
    notification_type: str,
    message: str,
    *,
    timestamp: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """
    백엔드 수신용 통일 알림 페이로드 생성.
    type/category 모두 BE NotificationType Enum 명칭으로 설정.

    Args:
        notification_type: BE NotificationType (ANALYSIS_STARTED, AI_DETECT, RAG_STATUS, CASE_ACTION)
        message: 사용자/시스템용 메시지
        timestamp: ISO timestamp (None이면 현재 UTC)
        **extra: 추가 필드 (case_id, run_id 등)

    Returns:
        {"type": "<notification_type>", "category": "<notification_type>", "message": "...", "timestamp": "...", **extra}
    """
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "type": notification_type,
        "category": notification_type,
        "message": message,
        "timestamp": ts,
    }
    payload.update(extra)
    return payload


def _log_redis_publish(channel: str, payload: dict[str, Any]) -> None:
    """Redis 발행 직전: 채널명과 데이터 내용 로그 (추적용)."""
    data_preview = json.dumps(payload, ensure_ascii=False)
    if len(data_preview) > 500:
        data_preview = data_preview[:500] + "..."
    logger.info("Redis publish: channel=%s type=%s data=%s", channel, payload.get("type", ""), data_preview)


async def publish_analysis_started(
    case_id: str,
    run_id: str,
    *,
    stream_url: str | None = None,
) -> bool:
    """
    분석 시작 알림 발행 (BE-FE 인지용).
    workbench:case:action 채널에 type=ANALYSIS_STARTED 로 발행.
    데모/트리거 포함 비동기 분석 시작 시 반드시 호출.
    """
    from core.config import get_settings
    channel = getattr(get_settings(), "case_action_redis_channel", REDIS_CHANNEL_WORKBENCH_CASE_ACTION)
    return await publish_workbench_notification(
        channel,
        NOTIFICATION_TYPE_ANALYSIS_STARTED,
        "분석이 시작되었습니다.",
        case_id=case_id,
        run_id=run_id,
        stream_url=stream_url or "",
    )


async def publish_workbench_notification(
    channel: str,
    notification_type: str,
    message: str,
    *,
    **extra: Any,
) -> bool:
    """
    Redis 채널로 통일 포맷 알림 발행 (async).
    notification_type은 BE NotificationType Enum 명칭 (ANALYSIS_STARTED, AI_DETECT, RAG_STATUS, CASE_ACTION).

    Returns:
        발행 성공 여부
    """
    try:
        from core.memory.redis_store import get_redis_store
        payload = build_notification_payload(notification_type, message, **extra)
        payload_str = json.dumps(payload, ensure_ascii=False)
        _log_redis_publish(channel, payload)
        store = await get_redis_store()
        await store.client.publish(channel, payload_str.encode("utf-8"))
        logger.info("Notification published: channel=%s type=%s", channel, notification_type)
        return True
    except Exception as e:
        logger.warning("Notification publish failed: channel=%s %s", channel, e)
        return False


def publish_workbench_notification_sync(
    channel: str,
    notification_type: str,
    message: str,
    *,
    redis_url: str | None = None,
    **extra: Any,
) -> bool:
    """
    Redis 채널로 통일 포맷 알림 발행 (sync). 동기 컨텍스트(백그라운드 태스크 등)에서 사용.

    Returns:
        발행 성공 여부
    """
    try:
        from core.config import get_settings
        import redis
        payload = build_notification_payload(notification_type, message, **extra)
        payload_str = json.dumps(payload, ensure_ascii=False)
        _log_redis_publish(channel, payload)
        url = redis_url or getattr(get_settings(), "redis_url", "redis://localhost:6379/0")
        client = redis.Redis.from_url(url, decode_responses=False)
        client.publish(channel, payload_str.encode("utf-8"))
        client.close()
        logger.info("Notification published (sync): channel=%s type=%s", channel, notification_type)
        return True
    except Exception as e:
        logger.warning("Notification publish (sync) failed: channel=%s %s", channel, e)
        return False
