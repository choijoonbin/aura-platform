"""
HITL 조치 확정 시 인사이트·알림 전용 서비스 (DB 직접 쓰기 없음).

- Aura는 case_action_history / fi_doc_header에 INSERT/UPDATE하지 않습니다.
- 백엔드에서 조치가 확정되었다는 신호를 받으면:
  1. HITL 피드백으로 로그(가중치 업데이트용) 기록
  2. Redis Pub/Sub으로 조치 완료 알림 발행 (워크벤치 Refetch 등 후속 프로세스)
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from core.config import get_settings
from core.memory.redis_store import get_redis_store

logger = logging.getLogger(__name__)

# HITL 피드백 전용 로거 (재학습/가중치 업데이트용 로그 수집)
HITL_FEEDBACK_LOGGER = "hitl_feedback"

ACTION_APPROVE = "APPROVE"
ACTION_REJECT = "REJECT"
STATUS_APPROVED = "APPROVED"
STATUS_REJECTED = "REJECTED"


def _log_hitl_feedback(
    case_id: str,
    request_id: str,
    executor_id: str,
    action_type: str,
    approved: bool,
    comment: str | None,
    doc_key: str | None,
) -> None:
    """
    조치 확정 결과를 HITL 피드백으로 기록 (향후 분석 정확도·가중치 업데이트용).
    DB가 아닌 구조화 로그/파일로만 남깁니다.
    """
    # comment: 백엔드 API 전달값 — UTF-8 안전 문자열로 정규화 (한글 깨짐 방지)
    comment_str: str
    if comment is None:
        comment_str = ""
    elif isinstance(comment, bytes):
        comment_str = comment.decode("utf-8", errors="replace")
    else:
        comment_str = str(comment)

    payload = {
        "event": "hitl_feedback",
        "case_id": case_id,
        "request_id": request_id,
        "executor_id": executor_id,
        "action_type": action_type,
        "approved": approved,
        "comment": comment_str,
        "doc_key": doc_key,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    feedback_logger = logging.getLogger(HITL_FEEDBACK_LOGGER)
    feedback_logger.info("%s", json.dumps(payload, ensure_ascii=False))

    # 선택: JSONL 파일로도 적재 (설정 시). UTF-8 인코딩으로 한글 등 비ASCII 보존
    log_path = getattr(get_settings(), "hitl_feedback_log_path", None)
    if log_path:
        try:
            os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug("HITL feedback file append skipped: %s", e)


async def record_case_action(
    case_id: str,
    request_id: str,
    executor_id: str,
    action_type: str,
    approved: bool,
    *,
    comment: str | None = None,
    doc_key: str | None = None,
) -> dict[str, Any]:
    """
    조치 확정 신호를 HITL 피드백으로 기록하고 Redis로 알림만 발행합니다.

    - DB 쓰기 없음: case_action_history / fi_doc_header는 백엔드가 관리합니다.
    - HITL 피드백: 구조화 로그 및 (설정 시) JSONL 파일에 기록 → 향후 가중치 업데이트용.
    - Redis: workbench:case:action 채널로 발행 → 워크벤치 Refetch 등 후속 프로세스.

    Returns:
        {"ok": True, "logged": True} 또는 {"ok": False, "error": str}
    """
    status_code = STATUS_APPROVED if approved else STATUS_REJECTED
    action_label = ACTION_APPROVE if approved else ACTION_REJECT

    try:
        # 1) HITL 피드백 로그 (가중치 업데이트용)
        _log_hitl_feedback(
            case_id=case_id,
            request_id=request_id,
            executor_id=executor_id,
            action_type=action_label,
            approved=approved,
            comment=comment,
            doc_key=doc_key,
        )

        # 2) Redis Pub/Sub 발행 (통일 포맷: type=NOTIFICATION, category=CASE_ACTION — 백엔드 NotificationService 규격)
        settings = get_settings()
        from core.notifications import REDIS_CHANNEL_WORKBENCH_CASE_ACTION
        channel = getattr(settings, "case_action_redis_channel", REDIS_CHANNEL_WORKBENCH_CASE_ACTION)
        from core.notifications import build_notification_payload, NOTIFICATION_CATEGORY_CASE_ACTION
        message = "조치 승인됨" if approved else "조치 거절됨"
        payload = build_notification_payload(
            NOTIFICATION_CATEGORY_CASE_ACTION,
            message,
            case_id=case_id,
            request_id=request_id,
            executor_id=executor_id,
            action_type=action_label,
            approved=approved,
            status_code=status_code,
        )
        try:
            store = await get_redis_store()
            payload_str = json.dumps(payload, ensure_ascii=False)
            await store.client.publish(channel, payload_str.encode("utf-8"))
            logger.info("HITL feedback logged and published: case_id=%s approved=%s channel=%s", case_id, approved, channel)
        except Exception as e:
            logger.warning("Redis publish for case action failed: %s", e)

        return {"ok": True, "logged": True}
    except Exception as e:
        logger.exception("record_case_action (feedback-only) failed: case_id=%s", case_id)
        return {"ok": False, "error": str(e)}
