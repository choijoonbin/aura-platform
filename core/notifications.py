"""
Redis 워크벤치 알림 발행 (통일 포맷).

백엔드 수신용 메시지 포맷: { "type": "NOTIFICATION", "category": "...", "message": "...", "timestamp": "...", ... }
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

NOTIFICATION_TYPE = "NOTIFICATION"

# 백엔드 NotificationService 규격과 대소문자 일치 (문자열 상수로 고정)
NOTIFICATION_CATEGORY_AI_DETECT = "AI_DETECT"
NOTIFICATION_CATEGORY_RAG_STATUS = "RAG_STATUS"
NOTIFICATION_CATEGORY_CASE_ACTION = "CASE_ACTION"

# 백엔드 구독 채널과 토씨 하나 틀리지 않게 일치 (core/config.py 기본값과 동일)
REDIS_CHANNEL_WORKBENCH_ALERT = "workbench:alert"
REDIS_CHANNEL_WORKBENCH_RAG_STATUS = "workbench:rag:status"
REDIS_CHANNEL_WORKBENCH_CASE_ACTION = "workbench:case:action"


def build_notification_payload(
    category: str,
    message: str,
    *,
    timestamp: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """
    백엔드 수신용 통일 알림 페이로드 생성.

    Args:
        category: NOTIFICATION category (예: CASE_ACTION, RAG_STATUS, AI_DETECT)
        message: 사용자/시스템용 메시지
        timestamp: ISO timestamp (None이면 현재 UTC)
        **extra: 추가 필드 (case_id, request_id, score 등)

    Returns:
        {"type": "NOTIFICATION", "category": "...", "message": "...", "timestamp": "...", **extra}
    """
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "type": NOTIFICATION_TYPE,
        "category": category,
        "message": message,
        "timestamp": ts,
    }
    payload.update(extra)
    return payload


async def publish_workbench_notification(
    channel: str,
    category: str,
    message: str,
    *,
    **extra: Any,
) -> bool:
    """
    Redis 채널로 통일 포맷 알림 발행 (async).

    Returns:
        발행 성공 여부
    """
    try:
        from core.memory.redis_store import get_redis_store
        payload = build_notification_payload(category, message, **extra)
        payload_str = json.dumps(payload, ensure_ascii=False)
        store = await get_redis_store()
        await store.client.publish(channel, payload_str.encode("utf-8"))
        logger.info("Notification published: channel=%s category=%s", channel, category)
        return True
    except Exception as e:
        logger.warning("Notification publish failed: channel=%s %s", channel, e)
        return False


def publish_workbench_notification_sync(
    channel: str,
    category: str,
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
        url = redis_url or getattr(get_settings(), "redis_url", "redis://localhost:6379/0")
        client = redis.Redis.from_url(url, decode_responses=False)
        payload = build_notification_payload(category, message, **extra)
        payload_str = json.dumps(payload, ensure_ascii=False)
        client.publish(channel, payload_str.encode("utf-8"))
        client.close()
        logger.info("Notification published (sync): channel=%s category=%s", channel, category)
        return True
    except Exception as e:
        logger.warning("Notification publish (sync) failed: channel=%s %s", channel, e)
        return False
