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
    """state에서 caseId, caseKey 추출 (audit traceability용). agent_activity_log case 매핑 필수."""
    ctx = state.get("context") or {}
    case_id = ctx.get("caseId") or ctx.get("case_id")
    case_key = ctx.get("caseKey") or ctx.get("case_key")
    return case_id, case_key


def _apply_case_resource(event: Any, state: dict[str, Any]) -> None:
    """
    context에 case_id가 있으면 모든 agent_activity_log 생성 시 resource_type='CASE', resource_id=case_id 자동 설정.
    AuditEvent 인스턴스를 받아 in-place로 수정함.
    """
    case_id, _ = _case_context(state)
    if case_id:
        event.resource_type = "CASE"
        event.resource_id = case_id


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
                _apply_case_resource(event, state)
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
                    step="ANALYSIS",
                    evidence=None,
                ).model_dump()
            )
        elif node_name == "evidence_gather":
            evidence_refs = [{"type": e.get("type"), "source": e.get("source"), "ref": e.get("ref")} for e in state.get("evidence", [])]
            ref_summary = ", ".join(e.get("source", "") for e in state.get("evidence", [])) or "없음"
            self.event_queue.append(
                ThoughtEvent(
                    thoughtType=ThoughtType.ANALYSIS,
                    content=f"사내 규정집 및 케이스 데이터에서 관련 조항·증거를 탐색 중입니다.",
                    sources=[e.get("source", "") for e in state.get("evidence", [])],
                    metadata={"evidence_refs": evidence_refs} if evidence_refs else {},
                    step="INTERNAL_POLICY_LOOKUP",
                    evidence=f"수집 소스: {ref_summary}" if ref_summary != "없음" else None,
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
                    step="PLANNING",
                    evidence=None,
                ).model_dump()
            )
        elif node_name == "execute":
            self.event_queue.append(
                ThoughtEvent(
                    thoughtType=ThoughtType.REASONING,
                    content="규정과 대조하여 판단 근거를 작성합니다. (도구 선택 및 실행 준비)",
                    sources=[],
                    step="FINAL_SYNTHESIS",
                    evidence=None,
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
            evidence_refs = [e.get("source", "") for e in state.get("evidence", [])]
            self.event_queue.append(
                ThoughtEvent(
                    thoughtType=ThoughtType.REFLECTION,
                    content="조사 결과를 검토하고 최종 판단 근거를 정리합니다.",
                    sources=evidence_refs,
                    step="REFLECTION",
                    evidence=", ".join(evidence_refs) if evidence_refs else None,
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
                _apply_case_resource(event, state)
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
                    _apply_case_resource(event, state)
                    self._emit_audit(event)
                    self._scan_completed_emitted = True
                except Exception:
                    pass
            try:
                from core.audit import AgentAuditEvent
                from core.context import get_request_context
                tenant_id = state.get("tenant_id") or "default"
                ctx = get_request_context()
                trace_id = ctx.get("trace_id") or state.get("trace_id")
                context = state.get("context") or {}
                case_id = context.get("caseId") or context.get("case_id") or ""
                if case_id:
                    # Phase 4: 정책 참조를 reasoning 및 evidence에 명시
                    policy_config = ctx.get("policy_config_source") or "dwp_aura.sys_monitoring_configs"
                    policy_profile = ctx.get("policy_profile") or "policy_profile"
                    reason_suffix = f" {policy_config} 임계치 및 {policy_profile} 가이드 참조."
                    message = f"Reasoning composed for case: {case_id}.{reason_suffix}"
                    policy_ref: dict[str, Any] = {
                        "configSource": policy_config,
                        "profileName": policy_profile,
                    }
                    event = AgentAuditEvent.reasoning_composed(
                        tenant_id=tenant_id,
                        case_id=case_id,
                        trace_id=trace_id,
                        message=message,
                        policy_reference=policy_ref,
                    )
                    _apply_case_resource(event, state)
                    self._emit_audit(event)
            except Exception:
                pass


def create_finance_sse_hook(event_queue: list[dict[str, Any]]) -> FinanceSSEHook:
    """Finance SSE Hook 생성"""
    return FinanceSSEHook(event_queue)
