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

import httpx

from core.audit.schemas import AuditEvent
from core.config import settings
from core.context import get_request_context

logger = logging.getLogger(__name__)

AUDIT_CHANNEL = getattr(settings, "audit_redis_channel", "audit:events:ingest")


def _get_audit_url() -> str:
    """Audit API URL (audit_delivery_mode=http 시)"""
    if getattr(settings, "audit_ingest_url", None):
        return settings.audit_ingest_url
    base = settings.synapse_base_url.rstrip("/")
    return f"{base}/api/synapse/audit/events/ingest"


def _get_headers() -> dict[str, str]:
    """Audit API 호출용 헤더 (HTTP 모드)"""
    try:
        ctx = get_request_context()
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if ctx.get("tenant_id"):
            headers["X-Tenant-ID"] = ctx["tenant_id"]
        if ctx.get("user_id"):
            headers["X-User-ID"] = ctx["user_id"]
        if ctx.get("trace_id"):
            headers["X-Trace-ID"] = ctx["trace_id"]
        if ctx.get("auth_token"):
            token = ctx["auth_token"]
            if not token.startswith("Bearer "):
                token = f"Bearer {token}"
            headers["Authorization"] = token
        return headers
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
            # Redis PUBLISH: decode_responses=False인 client는 bytes 필요
            channel = self._redis_channel
            await store.client.publish(channel, payload_str.encode("utf-8"))
            return True
        except Exception as e:
            logger.warning(f"Audit Redis publish failed: {e}")
            return False

    async def _ingest_via_http(self, payload: dict[str, Any]) -> bool:
        """HTTP POST로 전송 (1안)"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    self._http_url,
                    json=payload,
                    headers=_get_headers(),
                )
                if resp.status_code >= 400:
                    logger.warning(
                        f"Audit HTTP ingest failed: {resp.status_code} - {resp.text[:200]}"
                    )
                    return False
                return True
        except Exception as e:
            logger.warning(f"Audit HTTP ingest error: {e}")
            return False

    def ingest_fire_and_forget(self, event: AuditEvent) -> None:
        """
        비동기 전송 (블로킹 없음)
        백그라운드 태스크로 실행.
        Agent Stream push도 함께 수행 (Prompt C: agent_stream_events_enabled 시).
        """
        if not self._enabled:
            return
        asyncio.create_task(self._safe_ingest(event))
        # Prompt C: Audit 발행 시 Agent Stream에도 push
        try:
            from core.agent_stream.writer import get_agent_stream_writer
            get_agent_stream_writer().emit_from_audit(event)
        except Exception as e:
            logger.debug(f"Agent stream emit skipped: {e}")

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
