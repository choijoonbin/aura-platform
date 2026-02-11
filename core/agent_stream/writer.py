"""
Agent Stream Writer (Prompt C)

Aura → Synapse REST push: POST /api/synapse/agent/events (batch 가능)
Dashboard GET /dashboard/agent-stream?range=6h 가 이 이벤트를 조회하여 반환.
"""

import asyncio
import logging
from typing import Any

from core.agent_stream.schemas import AgentEvent
from core.config import settings
from core.context import get_synapse_headers
from core.http_client import post_json

logger = logging.getLogger(__name__)

# AuditEvent event_type → AgentStream stage 매핑
_AUDIT_TO_STAGE: dict[str, str] = {
    "AGENT/SCAN_STARTED": "SCAN",
    "AGENT/SCAN_COMPLETED": "SCAN",
    "AGENT/DETECTION_FOUND": "DETECT",
    "AGENT/RAG_QUERIED": "ANALYZE",
    "AGENT/REASONING_COMPOSED": "ANALYZE",
    "ACTION/SIMULATION_RUN": "SIMULATE",
    "ACTION/ACTION_PROPOSED": "EXECUTE",
    "ACTION/ACTION_APPROVED": "EXECUTE",
    "ACTION/ACTION_EXECUTED": "EXECUTE",
    "ACTION/ACTION_FAILED": "EXECUTE",
    "ACTION/ACTION_ROLLED_BACK": "EXECUTE",
    "INTEGRATION/SAP_WRITE_SUCCESS": "EXECUTE",
    "INTEGRATION/SAP_WRITE_FAILED": "EXECUTE",
    "CASE/CASE_CREATED": "EXECUTE",
    "CASE/CASE_STATUS_CHANGED": "EXECUTE",
    "CASE/CASE_ASSIGNED": "EXECUTE",
}


def _audit_event_to_agent_event(audit_event: Any) -> AgentEvent:
    """AuditEvent → AgentEvent 변환"""
    from datetime import datetime

    data = audit_event.model_dump(mode="json") if hasattr(audit_event, "model_dump") else dict(audit_event)
    ev: dict = data.get("evidence_json") or {}

    event_type = data.get("event_type", "")
    stage = _AUDIT_TO_STAGE.get(event_type, "EXECUTE" if "ACTION" in event_type or "CASE" in event_type else "ANALYZE")

    message = ev.get("message") or event_type or "Event"
    if isinstance(message, dict):
        message = str(message)

    rt, rid = data.get("resource_type"), data.get("resource_id")
    case_id = ev.get("caseId") or (rid if rt == "CASE" else None)
    action_id = ev.get("actionId") or (rid if rt == "AGENT_ACTION" else None)

    return AgentEvent(
        tenantId=data.get("tenant_id", "1"),
        timestamp=data.get("timestamp") or datetime.utcnow(),
        stage=stage,
        message=str(message),
        caseKey=ev.get("caseKey"),
        caseId=case_id,
        severity=data.get("severity", "INFO"),
        traceId=ev.get("traceId") or data.get("trace_id"),
        actionId=action_id,
        payload={k: v for k, v in ev.items() if k not in ("message", "caseKey", "caseId", "traceId", "actionId")},
    )


def _get_push_url() -> str:
    """Agent Stream push URL (Gateway 8080 경유)"""
    url = getattr(settings, "agent_stream_push_url", None)
    if url:
        return url.rstrip("/")
    # synapse_base_url이 agent-tools 경로면 agent/events는 별도 URL
    base = settings.synapse_base_url.rstrip("/")
    if "agent-tools" in base:
        return "http://localhost:8080/api/synapse/agent/events"
    return f"{base}/api/synapse/agent/events"


def _get_headers() -> dict[str, str]:
    """Push 요청 헤더 (context 기반)"""
    try:
        return get_synapse_headers()
    except LookupError:
        return {"Content-Type": "application/json", "Accept": "application/json"}


class AgentStreamWriter:
    """
    Agent Stream 이벤트 전송기 (C2: REST push)

    POST /api/synapse/agent/events (batch 가능)
    Fire-and-forget, 실패 시 로그만 남김.
    """

    def __init__(
        self,
        push_url: str | None = None,
        enabled: bool = True,
    ):
        self._push_url = push_url or _get_push_url()
        self._enabled = enabled and getattr(settings, "agent_stream_events_enabled", True)
        self._batch: list[AgentEvent] = []
        self._batch_max = 10
        self._flush_interval = 2.0  # 초

    def _event_to_payload(self, event: AgentEvent) -> dict[str, Any]:
        """AgentEvent → API payload"""
        d = event.model_dump(mode="json")
        ts = d.get("timestamp")
        if ts and hasattr(ts, "isoformat"):
            d["timestamp"] = ts.isoformat()
        return d

    async def push(self, events: list[AgentEvent]) -> bool:
        """배치 push"""
        if not self._enabled or not events:
            return True

        payload = [self._event_to_payload(e) for e in events]
        body: dict = {"events": payload}
        ok, status_code, text = await post_json(
            self._push_url,
            body,
            headers=_get_headers(),
            timeout=10.0,
        )
        if not ok:
            logger.warning(
                "Agent stream push failed: %s - %s",
                status_code,
                (text[:200] if text else ""),
            )
        return ok

    async def push_one(self, event: AgentEvent) -> bool:
        """단일 이벤트 push"""
        return await self.push([event])

    def emit_from_audit(self, audit_event: Any) -> None:
        """AuditEvent를 AgentEvent로 변환하여 push (fire-and-forget)"""
        if not self._enabled:
            return
        try:
            agent_event = _audit_event_to_agent_event(audit_event)
            asyncio.create_task(self._safe_push_one(agent_event))
        except Exception as e:
            logger.debug(f"Agent stream emit skipped: {e}")

    async def _safe_push_one(self, event: AgentEvent) -> None:
        try:
            await self.push_one(event)
        except Exception as e:
            logger.warning(f"Agent stream fire-and-forget failed: {e}")


_agent_stream_writer: AgentStreamWriter | None = None


def get_agent_stream_writer() -> AgentStreamWriter:
    """AgentStreamWriter 싱글톤"""
    global _agent_stream_writer
    if _agent_stream_writer is None:
        _agent_stream_writer = AgentStreamWriter()
    return _agent_stream_writer
