"""
Audit Event Schemas

audit_event_log에 기록할 표준 이벤트 스키마.
최소 필드: tenant_id, actor_type, actor_agent_id, event_category, event_type,
resource_type, resource_id, outcome, severity, evidence_json
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AuditEventCategory(str, Enum):
    """이벤트 카테고리 (C-1: INTEGRATION, ACTION, CASE 확장)"""
    AGENT = "AGENT"
    ACTION = "ACTION"
    INTEGRATION = "INTEGRATION"
    CASE = "CASE"


class AuditEventType(str, Enum):
    """의무 이벤트 타입 (C-1 명세)"""
    # SCAN
    SCAN_STARTED = "AGENT/SCAN_STARTED"
    SCAN_COMPLETED = "AGENT/SCAN_COMPLETED"
    # DETECT
    DETECTION_FOUND = "AGENT/DETECTION_FOUND"
    # ANALYZE (RAG)
    RAG_QUERIED = "AGENT/RAG_QUERIED"
    REASONING_COMPOSED = "AGENT/REASONING_COMPOSED"
    # SIMULATE (C-1: ACTION 카테고리로 분류)
    SIMULATION_RUN = "ACTION/SIMULATION_RUN"
    # EXECUTE
    ACTION_PROPOSED = "ACTION/ACTION_PROPOSED"
    ACTION_APPROVED = "ACTION/ACTION_APPROVED"  # HITL 승인 시
    ACTION_EXECUTED = "ACTION/ACTION_EXECUTED"
    ACTION_ROLLED_BACK = "ACTION/ACTION_ROLLED_BACK"
    # INTEGRATION
    INGEST_RECEIVED = "INTEGRATION/INGEST_RECEIVED"
    INGEST_PARSED = "INTEGRATION/INGEST_PARSED"
    INGEST_FAILED = "INTEGRATION/INGEST_FAILED"
    SAP_WRITE_SUCCESS = "INTEGRATION/SAP_WRITE_SUCCESS"
    SAP_WRITE_FAILED = "INTEGRATION/SAP_WRITE_FAILED"
    # CASE (대시보드 연동)
    CASE_CREATED = "CASE/CASE_CREATED"
    CASE_STATUS_CHANGED = "CASE/CASE_STATUS_CHANGED"
    CASE_ASSIGNED = "CASE/CASE_ASSIGNED"
    # ACTION 확장
    ACTION_FAILED = "ACTION/ACTION_FAILED"


class AuditEvent(BaseModel):
    """Audit 이벤트 기본 스키마"""

    tenant_id: str = Field(..., description="X-Tenant-ID")
    actor_type: str = Field(default="AGENT", description="액터 타입")
    actor_agent_id: str = Field(..., description="에이전트 ID (예: finance_agent)")
    event_category: str = Field(..., description="event_category")
    event_type: str = Field(..., description="event_type (예: AGENT/SCAN_STARTED)")
    resource_type: str | None = Field(default=None, description="resource_type: CASE, AGENT_ACTION, INTEGRATION (통합관제센터 규격)")
    resource_id: str | None = Field(default=None, description="resource_id (caseId, actionId)")
    outcome: str = Field(default="SUCCESS", description="outcome (SUCCESS, FAILED, PENDING, DENIED, NOOP) - audit_event_log 규격")
    severity: str = Field(default="INFO", description="severity (INFO, WARN, ERROR) - 통합관제센터 표시 레벨")
    evidence_json: dict[str, Any] = Field(
        default_factory=dict,
        description="단계별 payload. message: 운영자 이해 가능 문장, detail은 evidence_json에. correlation: traceId, gatewayRequestId, caseId, caseKey, actionId",
    )
    tags: dict[str, Any] = Field(
        default_factory=dict,
        description="대시보드 집계용. driverType, severity 등 (Top Risk Driver)",
    )
    trace_id: str | None = Field(default=None, description="X-Trace-ID")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AgentAuditEvent:
    """에이전트 의무 이벤트 생성 헬퍼"""

    @staticmethod
    def scan_started(
        tenant_id: str,
        actor_agent_id: str = "finance_agent",
        trace_id: str | None = None,
        **evidence: Any,
    ) -> AuditEvent:
        message = evidence.pop("message", None) or "Scan started"
        return AuditEvent(
            tenant_id=tenant_id,
            actor_type="AGENT",
            actor_agent_id=actor_agent_id,
            event_category="AGENT",
            event_type=AuditEventType.SCAN_STARTED.value,
            outcome="PENDING",
            severity="INFO",
            evidence_json={"message": message, **evidence},
            trace_id=trace_id,
        )

    @staticmethod
    def scan_completed(
        tenant_id: str,
        processed_count: int,
        duration_ms: int,
        actor_agent_id: str = "finance_agent",
        trace_id: str | None = None,
        **evidence: Any,
    ) -> AuditEvent:
        return AuditEvent(
            tenant_id=tenant_id,
            actor_type="AGENT",
            actor_agent_id=actor_agent_id,
            event_category="AGENT",
            event_type=AuditEventType.SCAN_COMPLETED.value,
            outcome="SUCCESS",
            severity="INFO",
            evidence_json={"processedCount": processed_count, "durationMs": duration_ms, **evidence},
            trace_id=trace_id,
        )

    @staticmethod
    def detection_found(
        tenant_id: str,
        case_id: str,
        risk_type_key: str,
        score: float,
        actor_agent_id: str = "finance_agent",
        trace_id: str | None = None,
        caseKey: str | None = None,
        **evidence: Any,
    ) -> AuditEvent:
        message = evidence.pop("message", None) or f"Detection found: {risk_type_key} (score: {score})"
        ev = {"caseId": case_id, "riskTypeKey": risk_type_key, "score": score, "message": message, **evidence}
        if caseKey:
            ev["caseKey"] = caseKey
        return AuditEvent(
            tenant_id=tenant_id,
            actor_type="AGENT",
            actor_agent_id=actor_agent_id,
            event_category="AGENT",
            event_type=AuditEventType.DETECTION_FOUND.value,
            resource_type="CASE",
            resource_id=case_id,
            outcome="SUCCESS",
            severity="INFO",
            evidence_json={"caseId": case_id, "riskTypeKey": risk_type_key, "score": score, "message": message, **evidence},
            tags={"driverType": risk_type_key, "severity": "HIGH" if score >= 0.7 else "MEDIUM" if score >= 0.4 else "LOW"},
            trace_id=trace_id,
        )

    @staticmethod
    def rag_queried(
        tenant_id: str,
        doc_ids: list[str],
        top_k: int,
        latency_ms: int,
        actor_agent_id: str = "finance_agent",
        trace_id: str | None = None,
        caseId: str | None = None,
        caseKey: str | None = None,
        **evidence: Any,
    ) -> AuditEvent:
        message = evidence.pop("message", None) or f"RAG queried: {len(doc_ids)} docs, topK={top_k}, {latency_ms}ms"
        ev: dict[str, Any] = {"docIds": doc_ids, "topK": top_k, "latencyMs": latency_ms, "message": message, **evidence}
        if caseId:
            ev["caseId"] = caseId
        if caseKey:
            ev["caseKey"] = caseKey
        return AuditEvent(
            tenant_id=tenant_id,
            actor_type="AGENT",
            actor_agent_id=actor_agent_id,
            event_category="AGENT",
            event_type=AuditEventType.RAG_QUERIED.value,
            outcome="SUCCESS",
            severity="INFO",
            evidence_json=ev,
            trace_id=trace_id,
            resource_type="CASE" if caseId else None,
            resource_id=caseId,
        )

    @staticmethod
    def reasoning_composed(
        tenant_id: str,
        case_id: str,
        actor_agent_id: str = "finance_agent",
        trace_id: str | None = None,
        **evidence: Any,
    ) -> AuditEvent:
        message = evidence.pop("message", None) or f"Reasoning composed for case: {case_id}"
        return AuditEvent(
            tenant_id=tenant_id,
            actor_type="AGENT",
            actor_agent_id=actor_agent_id,
            event_category="AGENT",
            event_type=AuditEventType.REASONING_COMPOSED.value,
            resource_type="CASE",
            resource_id=case_id,
            outcome="SUCCESS",
            severity="INFO",
            evidence_json={"caseId": case_id, "message": message, **evidence},
            trace_id=trace_id,
        )

    @staticmethod
    def simulation_run(
        tenant_id: str,
        action_id: str,
        result: str,  # PASS | FAIL
        diff_json: dict[str, Any] | None = None,
        actor_agent_id: str = "finance_agent",
        trace_id: str | None = None,
        caseId: str | None = None,
        caseKey: str | None = None,
        **evidence: Any,
    ) -> AuditEvent:
        outcome = "SUCCESS" if result.upper() == "PASS" else "FAIL"
        message = evidence.pop("message", None) or f"Simulation {result}: {action_id}"
        ev = {"actionId": action_id, "result": result, "diffJson": diff_json or {}, "message": message, **evidence}
        if caseId:
            ev["caseId"] = caseId
        if caseKey:
            ev["caseKey"] = caseKey
        return AuditEvent(
            tenant_id=tenant_id,
            actor_type="AGENT",
            actor_agent_id=actor_agent_id,
            event_category="ACTION",
            event_type=AuditEventType.SIMULATION_RUN.value,
            resource_type="AGENT_ACTION",
            resource_id=action_id,
            outcome=outcome,
            severity="INFO",
            evidence_json=ev,
            trace_id=trace_id,
        )

    @staticmethod
    def action_proposed(
        tenant_id: str,
        action_id: str,
        requires_approval: bool = True,
        actor_agent_id: str = "finance_agent",
        trace_id: str | None = None,
        caseId: str | None = None,
        caseKey: str | None = None,
        **evidence: Any,
    ) -> AuditEvent:
        message = evidence.pop("message", None) or f"Action proposed: {action_id} (requiresApproval={requires_approval})"
        ev: dict[str, Any] = {"actionId": action_id, "requiresApproval": requires_approval, "message": message, **evidence}
        if caseId:
            ev["caseId"] = caseId
        if caseKey:
            ev["caseKey"] = caseKey
        return AuditEvent(
            tenant_id=tenant_id,
            actor_type="AGENT",
            actor_agent_id=actor_agent_id,
            event_category="ACTION",
            event_type=AuditEventType.ACTION_PROPOSED.value,
            resource_type="AGENT_ACTION",
            resource_id=action_id,
            outcome="PENDING",
            severity="INFO",
            evidence_json=ev,
            trace_id=trace_id,
        )

    @staticmethod
    def action_approved(
        tenant_id: str,
        action_id: str,
        actor_agent_id: str = "finance_agent",
        trace_id: str | None = None,
        caseId: str | None = None,
        caseKey: str | None = None,
        **evidence: Any,
    ) -> AuditEvent:
        """HITL 승인 시 (case_id 연동: 통합 워크벤치 타임라인용)"""
        message = evidence.pop("message", None) or f"Action approved: {action_id}"
        ev: dict[str, Any] = {"actionId": action_id, "message": message, **evidence}
        if caseId:
            ev["caseId"] = caseId
        if caseKey:
            ev["caseKey"] = caseKey
        return AuditEvent(
            tenant_id=tenant_id,
            actor_type="AGENT",
            actor_agent_id=actor_agent_id,
            event_category="ACTION",
            event_type=AuditEventType.ACTION_APPROVED.value,
            resource_type="AGENT_ACTION",
            resource_id=action_id,
            outcome="SUCCESS",
            severity="INFO",
            evidence_json=ev,
            trace_id=trace_id,
        )

    @staticmethod
    def action_executed(
        tenant_id: str,
        action_id: str,
        outcome: str,  # SUCCESS | FAIL
        sap_ref: str | None = None,
        actor_agent_id: str = "finance_agent",
        trace_id: str | None = None,
        caseId: str | None = None,
        caseKey: str | None = None,
        **evidence: Any,
    ) -> AuditEvent:
        severity = "ERROR" if outcome == "FAIL" else "INFO"
        message = evidence.pop("message", None) or f"Action executed: {action_id} ({outcome})"
        ev = {"actionId": action_id, "sapRef": sap_ref, "message": message, **evidence}
        if caseId:
            ev["caseId"] = caseId
        if caseKey:
            ev["caseKey"] = caseKey
        return AuditEvent(
            tenant_id=tenant_id,
            actor_type="AGENT",
            actor_agent_id=actor_agent_id,
            event_category="ACTION",
            event_type=AuditEventType.ACTION_EXECUTED.value,
            resource_type="AGENT_ACTION",
            resource_id=action_id,
            outcome=outcome,
            severity=severity,
            evidence_json=ev,
            trace_id=trace_id,
        )

    @staticmethod
    def action_failed(
        tenant_id: str,
        action_id: str,
        error: str,
        actor_agent_id: str = "finance_agent",
        trace_id: str | None = None,
        **evidence: Any,
    ) -> AuditEvent:
        """액션 실행 실패 시 (C-1 확장)"""
        message = evidence.pop("message", None) or f"Action failed: {action_id} - {error}"
        return AuditEvent(
            tenant_id=tenant_id,
            actor_type="AGENT",
            actor_agent_id=actor_agent_id,
            event_category="ACTION",
            event_type=AuditEventType.ACTION_FAILED.value,
            resource_type="AGENT_ACTION",
            resource_id=action_id,
            outcome="FAILED",
            severity="ERROR",
            evidence_json={"actionId": action_id, "error": error, "message": message, **evidence},
            trace_id=trace_id,
        )

    @staticmethod
    def action_rolled_back(
        tenant_id: str,
        action_id: str,
        reason: str,
        actor_agent_id: str = "finance_agent",
        trace_id: str | None = None,
        **evidence: Any,
    ) -> AuditEvent:
        """액션 롤백 시"""
        message = evidence.pop("message", None) or f"Action rolled back: {action_id} - {reason}"
        return AuditEvent(
            tenant_id=tenant_id,
            actor_type="AGENT",
            actor_agent_id=actor_agent_id,
            event_category="ACTION",
            event_type=AuditEventType.ACTION_ROLLED_BACK.value,
            resource_type="AGENT_ACTION",
            resource_id=action_id,
            outcome="FAIL",
            severity="WARN",
            evidence_json={"actionId": action_id, "reason": reason, "message": message, **evidence},
            trace_id=trace_id,
        )

    @staticmethod
    def sap_write_success(
        tenant_id: str,
        sap_ref: str,
        resource_id: str | None = None,
        actor_agent_id: str = "finance_agent",
        trace_id: str | None = None,
        caseId: str | None = None,
        caseKey: str | None = None,
        **evidence: Any,
    ) -> AuditEvent:
        message = evidence.pop("message", None) or f"SAP write success: {sap_ref}"
        ev: dict[str, Any] = {"sapRef": sap_ref, "message": message, **evidence}
        if caseId:
            ev["caseId"] = caseId
        if caseKey:
            ev["caseKey"] = caseKey
        return AuditEvent(
            tenant_id=tenant_id,
            actor_type="AGENT",
            actor_agent_id=actor_agent_id,
            event_category="INTEGRATION",
            event_type=AuditEventType.SAP_WRITE_SUCCESS.value,
            resource_type="INTEGRATION",
            resource_id=resource_id or sap_ref,
            outcome="SUCCESS",
            severity="INFO",
            evidence_json=ev,
            trace_id=trace_id,
        )

    @staticmethod
    def sap_write_failed(
        tenant_id: str,
        sap_ref: str | None,
        error: str,
        resource_id: str | None = None,
        actor_agent_id: str = "finance_agent",
        trace_id: str | None = None,
        caseId: str | None = None,
        caseKey: str | None = None,
        **evidence: Any,
    ) -> AuditEvent:
        message = evidence.pop("message", None) or f"SAP write failed: {error}"
        ev: dict[str, Any] = {"sapRef": sap_ref, "error": error, "message": message, **evidence}
        if caseId:
            ev["caseId"] = caseId
        if caseKey:
            ev["caseKey"] = caseKey
        return AuditEvent(
            tenant_id=tenant_id,
            actor_type="AGENT",
            actor_agent_id=actor_agent_id,
            event_category="INTEGRATION",
            event_type=AuditEventType.SAP_WRITE_FAILED.value,
            resource_type="INTEGRATION",
            resource_id=resource_id or sap_ref,
            outcome="FAIL",
            severity="ERROR",
            evidence_json=ev,
            trace_id=trace_id,
        )

    # --- CASE 카테고리 (C-1, C-3: 대시보드 집계) ---

    @staticmethod
    def case_created(
        tenant_id: str,
        case_id: str,
        case_key: str | None = None,
        actor_agent_id: str = "finance_agent",
        trace_id: str | None = None,
        **evidence: Any,
    ) -> AuditEvent:
        """케이스 생성 시 (Synapse/Ingest 파이프라인 등)"""
        message = evidence.pop("message", None) or f"Case created: {case_id}"
        ev = {"caseId": case_id, "message": message, **evidence}
        if case_key:
            ev["caseKey"] = case_key
        return AuditEvent(
            tenant_id=tenant_id,
            actor_type="AGENT",
            actor_agent_id=actor_agent_id,
            event_category="CASE",
            event_type=AuditEventType.CASE_CREATED.value,
            resource_type="CASE",
            resource_id=case_id,
            outcome="SUCCESS",
            severity="INFO",
            evidence_json=ev,
            trace_id=trace_id,
        )

    @staticmethod
    def case_status_changed(
        tenant_id: str,
        case_id: str,
        from_status: str,
        to_status: str,
        case_key: str | None = None,
        actor_agent_id: str = "finance_agent",
        trace_id: str | None = None,
        **evidence: Any,
    ) -> AuditEvent:
        """케이스 상태 변경 시 (C-3: Action Required/승인대기 등)"""
        message = evidence.pop("message", None) or f"Case status: {from_status} → {to_status}"
        ev = {"caseId": case_id, "fromStatus": from_status, "toStatus": to_status, "message": message, **evidence}
        if case_key:
            ev["caseKey"] = case_key
        return AuditEvent(
            tenant_id=tenant_id,
            actor_type="AGENT",
            actor_agent_id=actor_agent_id,
            event_category="CASE",
            event_type=AuditEventType.CASE_STATUS_CHANGED.value,
            resource_type="CASE",
            resource_id=case_id,
            outcome="SUCCESS",
            severity="INFO",
            evidence_json=ev,
            trace_id=trace_id,
        )

    @staticmethod
    def case_assigned(
        tenant_id: str,
        case_id: str,
        assignee_id: str,
        case_key: str | None = None,
        actor_agent_id: str = "finance_agent",
        trace_id: str | None = None,
        **evidence: Any,
    ) -> AuditEvent:
        """케이스 담당자 배정 시"""
        message = evidence.pop("message", None) or f"Case assigned to {assignee_id}"
        ev = {"caseId": case_id, "assigneeId": assignee_id, "message": message, **evidence}
        if case_key:
            ev["caseKey"] = case_key
        return AuditEvent(
            tenant_id=tenant_id,
            actor_type="AGENT",
            actor_agent_id=actor_agent_id,
            event_category="CASE",
            event_type=AuditEventType.CASE_ASSIGNED.value,
            resource_type="CASE",
            resource_id=case_id,
            outcome="SUCCESS",
            severity="INFO",
            evidence_json=ev,
            trace_id=trace_id,
        )
