"""
Audit Writer

Synapse 백엔드로 Audit 이벤트를 전달합니다.
- 2안(권장): Redis Pub/Sub → Synapse가 구독하여 AuditWriter로 audit_event_log 저장
- 1안: POST /api/synapse/audit/events/ingest (HTTP API)
"""

import asyncio
import json
import logging
from typing import Any

from core.audit.schemas import AuditEvent
from core.config import settings
from core.context import get_request_context, get_synapse_headers
from core.http_client import post_json

logger = logging.getLogger(__name__)

AUDIT_CHANNEL = getattr(settings, "audit_redis_channel", "audit:events:ingest")

# 에이전트 스트림(thought/AGENT_STREAM/step) 전용 이벤트 → REST만 사용, Redis로 보내지 않음 (AURA_CASE_PER_CALL_PROMPT)
# 현재 thought/스트림 내용은 모두 reasoning_composed()로만 발행되며 event_type="AGENT/REASONING_COMPOSED" 사용.
# SSE 이벤트 이름(thought_pending, AGENT_STREAM, step)이 추후 AuditEvent.event_type으로 쓰일 경우를 대비해 함께 포함.
AGENT_STREAM_ONLY_EVENT_TYPES = ("REASONING_COMPOSED", "AGENT_STREAM", "step", "thought_pending")


def _get_audit_url() -> str:
    """Audit API URL (audit_delivery_mode=http 시)"""
    if getattr(settings, "audit_ingest_url", None):
        return settings.audit_ingest_url
    base = settings.synapse_base_url.rstrip("/")
    return f"{base}/api/synapse/audit/events/ingest"


def _get_headers() -> dict[str, str]:
    """Audit API 호출용 헤더 (context 기반)"""
    try:
        return get_synapse_headers()
    except LookupError:
        return {"Content-Type": "application/json", "Accept": "application/json"}


def _event_to_payload(event: AuditEvent) -> dict[str, Any]:
    """
    AuditEvent를 Synapse audit_event_log 규격 JSON으로 변환.
    C-2: evidence_json/tags에 correlation 키(traceId, gatewayRequestId, caseId, caseKey, actionId) 보장.
    """
    payload = event.model_dump(mode="json")
    # timestamp → created_at (ISO 8601)
    ts = payload.pop("timestamp", None)
    if ts and hasattr(ts, "isoformat"):
        payload["created_at"] = ts.isoformat()
    elif ts:
        payload["created_at"] = str(ts)
    # event_type: "AGENT/SCAN_STARTED" → "SCAN_STARTED" (event_category와 분리)
    et = payload.get("event_type", "")
    if "/" in et:
        payload["event_type"] = et.split("/", 1)[1]
    # outcome: FAIL → FAILED (audit_event_log 규격)
    if payload.get("outcome") == "FAIL":
        payload["outcome"] = "FAILED"
    # channel: AGENT (에이전트 발행)
    payload.setdefault("channel", "AGENT")
    # C-2: correlation 키 enrichment (traceId, gatewayRequestId, caseId, caseKey, actionId)
    try:
        ctx = get_request_context()
        ev = payload.get("evidence_json") or {}
        if ctx.get("trace_id") and "traceId" not in ev:
            ev["traceId"] = ctx["trace_id"]
        if ctx.get("gateway_request_id") and "gatewayRequestId" not in ev:
            ev["gatewayRequestId"] = ctx["gateway_request_id"]
        if ctx.get("case_key") and "caseKey" not in ev:
            ev["caseKey"] = ctx["case_key"]
        rt, rid = payload.get("resource_type"), payload.get("resource_id")
        if rid and "caseId" not in ev and rt in ("CASE", "AGENT_CASE"):
            ev["caseId"] = rid
        if ctx.get("case_id") and "caseId" not in ev:
            ev["caseId"] = ctx["case_id"]
        if rid and "actionId" not in ev and rt == "AGENT_ACTION":
            ev["actionId"] = rid
        payload["evidence_json"] = ev
    except LookupError:
        pass
    return payload


class AuditWriter:
    """
    Audit 이벤트 전송기
    
    2안(권장): Redis Pub/Sub으로 발행 → Synapse 내부 AuditWriter가 구독하여 audit_event_log 저장
    1안: HTTP POST로 Synapse API 호출
    
    Fire-and-forget 방식, 실패 시 로그만 남깁니다.
    """

    def __init__(
        self,
        delivery_mode: str | None = None,
        redis_channel: str | None = None,
        http_url: str | None = None,
        enabled: bool = True,
    ):
        self._delivery_mode = (delivery_mode or getattr(settings, "audit_delivery_mode", "redis")).lower()
        self._redis_channel = redis_channel or getattr(settings, "audit_redis_channel", AUDIT_CHANNEL)
        self._http_url = http_url or _get_audit_url()
        self._enabled = enabled and getattr(settings, "audit_events_enabled", True)

    async def ingest(self, event: AuditEvent) -> bool:
        """
        단일 이벤트 전송
        
        Returns:
            성공 여부
        """
        if not self._enabled:
            return True

        payload = _event_to_payload(event)
        payload_str = json.dumps(payload, ensure_ascii=False)

        if self._delivery_mode == "redis":
            return await self._ingest_via_redis(payload_str)
        return await self._ingest_via_http(payload)

    async def _ingest_via_redis(self, payload_str: str) -> bool:
        """Redis Pub/Sub으로 발행 (2안)"""
        try:
            from core.memory.redis_store import get_redis_store
            store = await get_redis_store()
            channel = self._redis_channel
            logger.debug("Redis publish: channel=%s data=%s", channel, payload_str[:500] + ("..." if len(payload_str) > 500 else ""))
            await store.client.publish(channel, payload_str.encode("utf-8"))
            return True
        except Exception as e:
            logger.warning(f"Audit Redis publish failed: {e}")
            return False

    async def _ingest_via_http(self, payload: dict[str, Any]) -> bool:
        """HTTP POST로 전송 (1안)"""
        ok, status_code, text = await post_json(
            self._http_url,
            payload,
            headers=_get_headers(),
            timeout=10.0,
        )
        if not ok:
            logger.warning(
                "Audit HTTP ingest failed: %s - %s",
                status_code,
                (text[:200] if text else ""),
            )
        return ok

    def ingest_fire_and_forget(self, event: AuditEvent) -> None:
        """
        비동기 전송 (블로킹 없음)
        백그라운드 태스크로 실행.

        케이스별 호출 규칙 (AURA_CASE_PER_CALL_PROMPT):
        - 에이전트 스트림(thought/AGENT_STREAM/step, REASONING_COMPOSED): REST만 사용 → emit_from_audit만 호출, Redis 미발행.
        - 그 외 감사 이벤트(RAG_QUERIED, SCAN_* 등): Redis만 사용 → _safe_ingest만 호출, REST agent/events 미호출.
        동일 이벤트를 REST와 Redis 양쪽에 보내지 않음.
        """
        if not self._enabled:
            return
        et = getattr(event, "event_type", "") or ""
        is_agent_stream_only = any(t in et for t in AGENT_STREAM_ONLY_EVENT_TYPES)
        if is_agent_stream_only:
            # 에이전트 스트림 → REST만 (동일 내용 Redis로 보내지 않음)
            try:
                from core.agent_stream.writer import get_agent_stream_writer
                get_agent_stream_writer().emit_from_audit(event)
            except Exception as e:
                logger.debug(f"Agent stream emit skipped: {e}")
            return
        # 감사 이벤트 → Redis(또는 HTTP audit)만
        asyncio.create_task(self._safe_ingest(event))

    async def _safe_ingest(self, event: AuditEvent) -> None:
        try:
            await self.ingest(event)
        except Exception as e:
            logger.warning(f"Audit fire-and-forget failed ({event.event_type}): {e}")


_audit_writer: AuditWriter | None = None


def get_audit_writer() -> AuditWriter:
    """AuditWriter 싱글톤 인스턴스 (2안=redis 기본)"""
    global _audit_writer
    if _audit_writer is None:
        _audit_writer = AuditWriter()
    return _audit_writer
