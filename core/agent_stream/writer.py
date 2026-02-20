"""
Agent Stream Writer (Prompt C)

Aura → Synapse REST push: POST /api/synapse/agent/events (batch 가능)
Dashboard GET /dashboard/agent-stream?range=6h 가 이 이벤트를 조회하여 반환.
"""

import asyncio
import logging
from typing import Any

from core.agent_stream.constants import (
    METADATA_STATUS_ERROR,
    METADATA_STATUS_SUCCESS,
    METADATA_STATUS_WARNING,
    STAGE_ANALYZE,
    STAGE_DETECT,
    STAGE_EXECUTE,
    STAGE_MATCH,
    STAGE_SCAN,
    STAGE_SIMULATE,
)
from core.agent_stream.metadata import format_metadata
from core.agent_stream.schemas import AgentEvent
from core.config import settings
from core.context import get_synapse_headers
from core.http_client import post_json

logger = logging.getLogger(__name__)

# AuditEvent event_type → AgentStream stage (STAGE_* 상수 사용, 프론트 필터링 가능)
_AUDIT_TO_STAGE: dict[str, str] = {
    "AGENT/SCAN_STARTED": STAGE_SCAN,
    "AGENT/SCAN_COMPLETED": STAGE_SCAN,
    "AGENT/DETECTION_FOUND": STAGE_DETECT,
    "AGENT/RAG_QUERIED": STAGE_ANALYZE,
    "AGENT/REASONING_COMPOSED": STAGE_ANALYZE,
    "ACTION/SIMULATION_RUN": STAGE_SIMULATE,
    "ACTION/ACTION_PROPOSED": STAGE_EXECUTE,
    "ACTION/ACTION_APPROVED": STAGE_EXECUTE,
    "ACTION/ACTION_EXECUTED": STAGE_EXECUTE,
    "ACTION/ACTION_FAILED": STAGE_EXECUTE,
    "ACTION/ACTION_ROLLED_BACK": STAGE_EXECUTE,
    "INTEGRATION/SAP_WRITE_SUCCESS": STAGE_EXECUTE,
    "INTEGRATION/SAP_WRITE_FAILED": STAGE_EXECUTE,
    "CASE/CASE_CREATED": STAGE_EXECUTE,
    "CASE/CASE_STATUS_CHANGED": STAGE_EXECUTE,
    "CASE/CASE_ASSIGNED": STAGE_EXECUTE,
}


def _outcome_to_status(outcome: str) -> str:
    """audit outcome → metadata_json.status (SUCCESS|WARNING|ERROR)."""
    if not outcome:
        return METADATA_STATUS_SUCCESS
    o = outcome.upper()
    if o in ("SUCCESS", "PASS", "PENDING", "NOOP"):
        return METADATA_STATUS_SUCCESS
    if o in ("FAIL", "FAILED", "ERROR", "DENIED"):
        return METADATA_STATUS_ERROR
    return METADATA_STATUS_SUCCESS


def _severity_to_metadata_status(severity: str, outcome: str) -> str:
    """severity + outcome → metadata_json.status (SUCCESS|WARNING|ERROR)."""
    status_from_outcome = _outcome_to_status(outcome)
    if status_from_outcome == METADATA_STATUS_ERROR:
        return METADATA_STATUS_ERROR
    sev = (severity or "").upper()
    if sev == "WARN":
        return METADATA_STATUS_WARNING
    if sev == "ERROR":
        return METADATA_STATUS_ERROR
    return METADATA_STATUS_SUCCESS


def _stage_to_title(stage: str, event_type: str) -> str:
    """stage/event_type → 타임라인용 한 줄 title (STAGE_* 상수와 매핑)"""
    titles: dict[str, str] = {
        STAGE_SCAN: "스캔",
        STAGE_DETECT: "위험 탐지",
        STAGE_ANALYZE: "추론·분석",
        STAGE_SIMULATE: "시뮬레이션",
        STAGE_EXECUTE: "조치 실행",
        STAGE_MATCH: "유사 케이스 매칭",
    }
    return titles.get(stage, stage or "이벤트")


def _audit_event_to_agent_event(audit_event: Any) -> AgentEvent:
    """AuditEvent → AgentEvent 변환. case_id 보강, payload에 title/description/status 포함 (통합 워크벤치 타임라인용)."""
    from datetime import datetime

    data = audit_event.model_dump(mode="json") if hasattr(audit_event, "model_dump") else dict(audit_event)
    ev: dict = data.get("evidence_json") or {}

    event_type = data.get("event_type", "")
    stage = _AUDIT_TO_STAGE.get(
        event_type,
        STAGE_EXECUTE if "ACTION" in event_type or "CASE" in event_type else STAGE_ANALYZE,
    )

    message = ev.get("message") or event_type or "Event"
    if isinstance(message, dict):
        message = str(message)

    rt, rid = data.get("resource_type"), data.get("resource_id")
    case_id = ev.get("caseId") or (rid if rt == "CASE" else None)
    if case_id is None:
        try:
            from core.context import get_request_context
            case_id = get_request_context().get("case_id")
        except LookupError:
            pass
    action_id = ev.get("actionId") or (rid if rt == "AGENT_ACTION" else None)

    # metadata_json 규격 강제: format_metadata 사용
    outcome = data.get("outcome", "")
    severity = data.get("severity", "INFO")
    status = _severity_to_metadata_status(severity, outcome)
    evidence = {k: v for k, v in ev.items() if k not in ("message", "caseKey", "caseId", "traceId", "actionId")}
    metadata_json = format_metadata(
        title=_stage_to_title(stage, event_type),
        reasoning=str(message),
        evidence=evidence,
        status=status,
    )

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
        payload=metadata_json,
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
        
        # 디버그: Agent Event 페이로드 로깅
        event_summaries = [
            {"stage": e.get("stage"), "title": e.get("title"), "caseId": e.get("caseId")}
            for e in payload
        ]
        logger.info("Agent stream push: url=%s count=%d events=%s", self._push_url[:60], len(payload), event_summaries)
        
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
        else:
            logger.debug("Agent stream push ok: status_code=%s", status_code)
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
