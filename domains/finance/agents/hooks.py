"""
Finance Agent SSE Hooks

Finance 에이전트 노드 실행 시 SSE 이벤트를 발행하는 Hook입니다.
Audit 이벤트(SCAN_STARTED, SCAN_COMPLETED, REASONING_COMPOSED)도 발행합니다.
"""

import logging
import time
from typing import Any

from api.schemas.events import (
    ThoughtEvent,
    PlanStepEvent,
    ToolExecutionEvent,
    ContentEvent,
    ThoughtType,
    PlanStepStatus,
    ToolExecutionStatus,
)

logger = logging.getLogger(__name__)


def _case_context(state: dict[str, Any]) -> tuple[str | None, str | None]:
    """state에서 caseId, caseKey 추출 (audit traceability용)"""
    ctx = state.get("context") or {}
    case_id = ctx.get("caseId") or ctx.get("case_id")
    case_key = ctx.get("caseKey") or ctx.get("case_key")
    return case_id, case_key


class FinanceSSEHook:
    """Finance 에이전트용 SSE 이벤트 Hook"""
    
    def __init__(self, event_queue: list[dict[str, Any]]):
        self.event_queue = event_queue
        self._scan_started_at: float | None = None
        self._scan_completed_emitted: bool = False
    
    def _emit_audit(self, event: Any) -> None:
        """Audit 이벤트 발행 (fire-and-forget)"""
        try:
            from core.audit.writer import get_audit_writer
            get_audit_writer().ingest_fire_and_forget(event)
        except Exception as e:
            logger.debug(f"Audit emit skipped: {e}")
    
    async def on_node_start(self, node_name: str, state: dict[str, Any]) -> None:
        """노드 시작 시 호출"""
        logger.debug(f"Finance node started: {node_name}")
        
        if node_name == "analyze":
            self._scan_started_at = time.perf_counter()
            try:
                from core.audit import AgentAuditEvent
                tenant_id = state.get("tenant_id") or "default"
                trace_id = state.get("trace_id")
                case_id, case_key = _case_context(state)
                ev: dict[str, Any] = {}
                if case_id:
                    ev["caseId"] = case_id
                if case_key:
                    ev["caseKey"] = case_key
                event = AgentAuditEvent.scan_started(
                    tenant_id=tenant_id,
                    trace_id=trace_id,
                    **ev,
                )
                if case_id:
                    event.resource_type = "CASE"
                    event.resource_id = case_id
                self._emit_audit(event)
            except Exception:
                pass
            evidence_refs = [{"type": e.get("type"), "source": e.get("source"), "ref": e.get("ref")} for e in state.get("evidence", [])]
            self.event_queue.append(
                ThoughtEvent(
                    thoughtType=ThoughtType.ANALYSIS,
                    content="케이스 목표 및 컨텍스트 분석을 시작합니다.",
                    sources=[e.get("source", "") for e in state.get("evidence", [])],
                    metadata={"evidence_refs": evidence_refs} if evidence_refs else {},
                ).model_dump()
            )
        elif node_name == "evidence_gather":
            evidence_refs = [{"type": e.get("type"), "source": e.get("source"), "ref": e.get("ref")} for e in state.get("evidence", [])]
            self.event_queue.append(
                ThoughtEvent(
                    thoughtType=ThoughtType.ANALYSIS,
                    content=f"evidence_refs {len(evidence_refs)}종 수집 완료 (case, documents, open_items, lineage)",
                    sources=[e.get("source", "") for e in state.get("evidence", [])],
                    metadata={"evidence_refs": evidence_refs} if evidence_refs else {},
                ).model_dump()
            )
        elif node_name == "plan":
            evidence_refs = [{"type": e.get("type"), "source": e.get("source"), "ref": e.get("ref")} for e in state.get("evidence", [])]
            self.event_queue.append(
                ThoughtEvent(
                    thoughtType=ThoughtType.PLANNING,
                    content="조사 및 조치 계획을 수립합니다.",
                    sources=[e.get("source", "") for e in state.get("evidence", [])],
                    metadata={"evidence_refs": evidence_refs} if evidence_refs else {},
                ).model_dump()
            )
        elif node_name == "execute":
            self.event_queue.append(
                ThoughtEvent(
                    thoughtType=ThoughtType.REASONING,
                    content="Synapse 도구 선택 및 실행을 준비합니다.",
                    sources=[],
                ).model_dump()
            )
        elif node_name == "tools":
            execution_logs = state.get("execution_logs", [])
            if execution_logs:
                last_log = execution_logs[-1]
                self.event_queue.append(
                    ToolExecutionEvent(
                        toolName=last_log.get("toolName", ""),
                        toolArgs=last_log.get("toolArgs", {}),
                        status=ToolExecutionStatus.RUNNING,
                        requiresApproval=last_log.get("requiresApproval", False),
                    ).model_dump()
                )
        elif node_name == "reflect":
            self.event_queue.append(
                ThoughtEvent(
                    thoughtType=ThoughtType.REFLECTION,
                    content="조사 결과를 검토합니다.",
                    sources=[e.get("source", "") for e in state.get("evidence", [])],
                ).model_dump()
            )
    
    async def on_node_end(self, node_name: str, state: dict[str, Any]) -> None:
        """노드 종료 시 호출"""
        logger.debug(f"Finance node ended: {node_name}")
        
        if node_name == "plan":
            evidence_refs = [{"type": e.get("type"), "source": e.get("source"), "ref": e.get("ref")} for e in state.get("evidence", [])]
            for step in state.get("plan_steps", []):
                self.event_queue.append(
                    PlanStepEvent(
                        stepId=step.get("stepId", ""),
                        description=step.get("description", ""),
                        status=PlanStepStatus(step.get("status", "pending")),
                        confidence=step.get("confidence", 0.7),
                        metadata={"evidence_refs": step.get("evidence_refs", evidence_refs)},
                    ).model_dump()
                )
        elif node_name == "tools":
            execution_logs = state.get("execution_logs", [])
            if execution_logs:
                last_log = execution_logs[-1]
                self.event_queue.append(
                    ToolExecutionEvent(
                        toolName=last_log.get("toolName", ""),
                        toolArgs=last_log.get("toolArgs", {}),
                        status=ToolExecutionStatus.SUCCESS,
                        result=last_log.get("result"),
                        requiresApproval=last_log.get("requiresApproval", False),
                    ).model_dump()
                )
            try:
                from core.audit import AgentAuditEvent
                from core.context import get_request_context
                tenant_id = state.get("tenant_id") or "default"
                trace_id = get_request_context().get("trace_id") or state.get("trace_id")
                case_id, case_key = _case_context(state)
                duration_ms = int((time.perf_counter() - (self._scan_started_at or time.perf_counter())) * 1000)
                ev: dict[str, Any] = {}
                if case_id:
                    ev["caseId"] = case_id
                if case_key:
                    ev["caseKey"] = case_key
                event = AgentAuditEvent.scan_completed(
                    tenant_id=tenant_id,
                    processed_count=len(execution_logs),
                    duration_ms=duration_ms,
                    trace_id=trace_id,
                    **ev,
                )
                if case_id:
                    event.resource_type = "CASE"
                    event.resource_id = case_id
                self._emit_audit(event)
                self._scan_completed_emitted = True
            except Exception:
                pass
        elif node_name == "reflect":
            messages = state.get("messages", [])
            if messages:
                last_message = messages[-1]
                if hasattr(last_message, "content"):
                    self.event_queue.append(
                        ContentEvent(content=last_message.content, chunk=False).model_dump()
                    )
            # SCAN_COMPLETED: tools 노드 미경유 시 reflect에서 발행 (audit traceability)
            if not self._scan_completed_emitted:
                try:
                    from core.audit import AgentAuditEvent
                    from core.context import get_request_context
                    tenant_id = state.get("tenant_id") or "default"
                    trace_id = get_request_context().get("trace_id") or state.get("trace_id")
                    case_id, case_key = _case_context(state)
                    duration_ms = int((time.perf_counter() - (self._scan_started_at or time.perf_counter())) * 1000)
                    ev: dict[str, Any] = {}
                    if case_id:
                        ev["caseId"] = case_id
                    if case_key:
                        ev["caseKey"] = case_key
                    event = AgentAuditEvent.scan_completed(
                        tenant_id=tenant_id,
                        processed_count=0,
                        duration_ms=duration_ms,
                        trace_id=trace_id,
                        **ev,
                    )
                    if case_id:
                        event.resource_type = "CASE"
                        event.resource_id = case_id
                    self._emit_audit(event)
                    self._scan_completed_emitted = True
                except Exception:
                    pass
            try:
                from core.audit import AgentAuditEvent
                from core.context import get_request_context
                tenant_id = state.get("tenant_id") or "default"
                trace_id = get_request_context().get("trace_id") or state.get("trace_id")
                context = state.get("context") or {}
                case_id = context.get("caseId") or context.get("case_id") or ""
                if case_id:
                    event = AgentAuditEvent.reasoning_composed(
                        tenant_id=tenant_id,
                        case_id=case_id,
                        trace_id=trace_id,
                    )
                    self._emit_audit(event)
            except Exception:
                pass


def create_finance_sse_hook(event_queue: list[dict[str, Any]]) -> FinanceSSEHook:
    """Finance SSE Hook 생성"""
    return FinanceSSEHook(event_queue)
