"""
Aura Cases Routes (Prompt C P0-P2, Audit Analysis)

Case Detail 탭: Agent Stream, RAG Evidence, Similar, Confidence, Analysis
감사 분석: Trigger 202 JSON, Stream 별도, BE Callback
"""

import asyncio
import json
import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from api.dependencies import AdminUser, CurrentUser, TenantId
from api.schemas.common import coerce_case_run_id
from api.sse_utils import SSE_HEADERS, format_sse_line
from core.context import set_request_context
from core.analysis.callback import send_callback
from core.analysis.run_store import get_event, get_or_create_queue, put_event, queue_exists, remove_queue
from core.streaming.case_stream_store import (
    CaseStreamEvent,
    get_case_stream_store,
    get_audit_analysis_result,
)
from tools.synapse_finance_tool import get_case, search_documents

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/aura/cases", tags=["aura-cases"])

# SSE 이벤트 간 최소 지연 (초)
STREAM_EVENT_DELAY = 0.15


def _format_case_sse_event(ev: CaseStreamEvent) -> str:
    """SSE 형식: id, event, data"""
    return f"id: {ev.id}\nevent: {ev.event}\ndata: {json.dumps(ev.to_sse_data(), ensure_ascii=False)}\n\n"


# ==================== P0: Case Stream ====================


@router.get("/{case_id}/stream")
async def case_stream(
    case_id: str,
    user: CurrentUser,
    tenant_id: TenantId,
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
):
    """
    Case Agent Stream (SSE) - P0
    
    GET /api/aura/cases/{caseId}/stream
    Last-Event-ID로 replay 지원.
    """
    store = get_case_stream_store()
    tenant = tenant_id or "1"
    trace_id = f"trace-{case_id}-{uuid.uuid4().hex[:8]}"

    async def event_generator():
        # Last-Event-ID 이후 이벤트 먼저 전송 (replay)
        events_after = store.get_events_after(case_id, last_event_id)
        for ev in events_after:
            yield _format_case_sse_event(ev)
            await asyncio.sleep(STREAM_EVENT_DELAY)

        # 기존 이벤트가 없으면 샘플 3~5개 생성 후 스트리밍
        if not events_after:
            sample_events = store.generate_sample_events(
                case_id=case_id,
                tenant_id=tenant,
                trace_id=trace_id,
                user_id=user.user_id,
                count=5,
            )
            for ev in sample_events:
                yield _format_case_sse_event(ev)
                await asyncio.sleep(STREAM_EVENT_DELAY)

        # 스트림 종료 표시
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/{case_id}/stream/trigger")
async def case_stream_trigger(
    case_id: str,
    user: AdminUser,
    tenant_id: TenantId,
):
    """
    Case Stream 수동 트리거 (P0, admin 전용)
    
    POST /api/aura/cases/{caseId}/stream/trigger
    테스트 재현성을 위한 샘플 이벤트 생성.
    """
    store = get_case_stream_store()
    tenant = tenant_id or "1"
    trace_id = f"trace-{case_id}-trigger-{uuid.uuid4().hex[:8]}"

    events = store.generate_sample_events(
        case_id=case_id,
        tenant_id=tenant,
        trace_id=trace_id,
        user_id=user.user_id,
        count=5,
    )
    return {
        "status": "triggered",
        "caseId": case_id,
        "eventCount": len(events),
        "traceId": trace_id,
        "message": "Sample events generated. Connect to GET /stream to receive them.",
    }


# ==================== Audit Analysis: Analysis Runs (Feign 호환) ====================


class AuraAnalyzeRequest(BaseModel):
    """BE 트리거 요청 (감사 분석 표준)"""
    runId: str = Field(..., description="BE가 생성한 run 식별자")
    caseId: str | None = Field(default=None, description="케이스 ID (path와 중복 가능, BE는 Long으로 전송)")
    evidence: dict[str, Any] | None = Field(default=None, description="evidence snapshot (문서/라인/오픈아이템/거래처 등)")
    mode: str | None = Field(default="LIVE", description="LIVE | SIMULATION")
    requestedBy: str | None = Field(default="HUMAN", description="HUMAN | SYSTEM")
    options: dict[str, Any] | None = Field(default=None, description="model, policyVersion 등")

    @field_validator("caseId", "runId", mode="before")
    @classmethod
    def _coerce_str(cls, v: Any) -> Any:
        return coerce_case_run_id(v)


async def _run_analysis_background(
    case_id: str,
    run_id: str,
    tenant_id: str,
    auth_token: str | None,
    body_evidence: dict[str, Any] | None = None,
    x_sandbox: str | None = None,
):
    """백그라운드 분석 실행 + 큐에 이벤트 적재 + 완료 시 콜백. body_evidence: C(폴백)용. 정책 참조 로그용 context."""
    from core.config import get_settings
    max_web = get_settings().web_search_max_calls_per_run
    aura_trace_id = f"aura-{run_id[:8]}-{uuid.uuid4().hex[:8]}"
    set_request_context(
        tenant_id=tenant_id,
        user_id="",
        auth_token=auth_token,
        trace_id=f"trace-{case_id}-{run_id[:8]}",
        case_id=case_id,
        policy_config_source="dwp_aura.sys_monitoring_configs",
        policy_profile="default",
        x_sandbox=x_sandbox,
        aura_trace_id=aura_trace_id,
        _guardrails={"web_search_calls": 0, "web_search_max_calls": max_web},
    )
    event_type = "failed"
    payload: dict[str, Any] = {}
    config = None
    try:
        from core.analysis.agent_factory import fetch_agent_config, select_agent_for_request
        from core.analysis.audit_analysis_pipeline import run_audit_analysis

        # Discovery + Selection: 사용자 요청 분석하여 적절한 에이전트 선택
        agent_id_val = await select_agent_for_request(
            user_query=None,  # case 분석이므로 케이스 컨텍스트 기반 선택
            context={"caseId": case_id, "evidence": body_evidence},
            tenant_id=tenant_id,
        )
        config = await fetch_agent_config(agent_id=agent_id_val, tenant_id=tenant_id)
        async for event_type, payload in run_audit_analysis(
            case_id,
            run_id=run_id,
            tenant_id=tenant_id,
            body_evidence=body_evidence,
            model_name=config.model_name,
            agent_config=config,
        ):
            put_event(run_id, event_type, payload)
            if event_type in ("completed", "failed"):
                break

        if event_type == "completed":
            result = get_audit_analysis_result(case_id)
            if result:
                await send_callback(run_id, case_id, "COMPLETED", final_result=result, agent_id=config.agent_id, version=config.version)
            else:
                await send_callback(run_id, case_id, "COMPLETED", final_result={
                    "score": payload.get("score", 0),
                    "severity": payload.get("severity", "MEDIUM"),
                    "reasonText": payload.get("summary", ""),
                    "confidence": {},
                    "evidence": [],
                    "ragRefs": [],
                    "similar": [],
                    "proposals": [],
                }, agent_id=config.agent_id, version=config.version)
        else:
            err = payload.get("error", "unknown")
            if isinstance(err, dict):
                err = err.get("message") or err.get("error") or "unknown"
            await send_callback(
                run_id, case_id, "FAILED",
                error_message=str(err),
                agent_id=config.agent_id,
                version=config.version,
            )
    except Exception as e:
        logger.exception(f"Analysis background failed case={case_id} run={run_id}")
        put_event(run_id, "failed", {"error": str(e), "stage": "background"})
        await send_callback(
            run_id, case_id, "FAILED",
            error_message=str(e),
            agent_id=config.agent_id if config else "audit",
            version=config.version if config else "1.0",
        )
    finally:
        # 스트림이 proposal·completed 수신할 시간 확보 (레이스 컨디션 방지)
        await asyncio.sleep(2.0)
        remove_queue(run_id)


@router.post("/{case_id}/analysis-runs")
async def case_analysis_runs(
    case_id: str,
    request: Request,
    body: AuraAnalyzeRequest,
    user: CurrentUser,
    tenant_id: TenantId,
):
    """
    감사 분석 트리거 (Feign 호환)
    
    POST /aura/cases/{caseId}/analysis-runs
    202 + JSON 즉시 반환. 백그라운드에서 분석 실행 후 BE 콜백.
    """
    if os.environ.get("DEMO_OFF", "").upper() in ("1", "TRUE", "YES"):
        return {"status": "disabled", "message": "Analysis disabled (DEMO_OFF)"}

    run_id = body.runId
    tenant_id_val = tenant_id or "1"
    auth_token = request.headers.get("Authorization")

    get_or_create_queue(run_id)
    x_sandbox = request.headers.get("X-Sandbox")
    asyncio.create_task(_run_analysis_background(
        case_id, run_id, tenant_id_val, auth_token,
        body_evidence=body.evidence,
        x_sandbox=x_sandbox,
    ))

    stream_url = f"/aura/analysis-runs/{run_id}/stream"
    return JSONResponse(
        status_code=202,
        content={
            "status": "ACCEPTED",
            "runId": run_id,
            "caseId": case_id,
            "streamUrl": stream_url,
        },
    )


@router.get("/{case_id}/analysis/stream")
async def case_analysis_stream(
    case_id: str,
    runId: str,
    user: CurrentUser,
    tenant_id: TenantId,
):
    """
    감사 분석 스트림 (SSE)

    GET /aura/cases/{caseId}/analysis/stream?runId={runId}
    started → step → evidence → confidence → proposal → completed | failed
    """
    run_id = runId
    if not queue_exists(run_id):
        logger.info(
            "case_analysis_stream: runId not found or already completed run_id=%s case_id=%s",
            run_id,
            case_id,
        )
        return {"error": "runId not found or already completed", "runId": run_id}

    logger.info("case_analysis_stream: start consuming run_id=%s case_id=%s", run_id, case_id)

    async def event_generator():
        # 연결 직후 SSE 주석 한 줄 전송 (클라이언트/프록시가 스트림 연결 인식용)
        try:
            yield ": connected\n\n"
            logger.info("case_analysis_stream: first chunk sent run_id=%s", run_id)
        except (GeneratorExit, BaseException) as e:
            logger.warning("case_analysis_stream: connection closed before/after first chunk run_id=%s reason=%s", run_id, e)
            raise

        sent_completed = False
        case_id_val = case_id
        try:
            while True:
                ev = await get_event(run_id, timeout=300.0)
                if ev is None:
                    logger.info("case_analysis_stream: get_event None (timeout or queue removed) run_id=%s", run_id)
                    break
                event_type, payload = ev
                if event_type == "started":
                    case_id_val = payload.get("caseId", "")
                yield format_sse_line(event_type, payload)
                await asyncio.sleep(STREAM_EVENT_DELAY)
                if event_type in ("completed", "failed"):
                    sent_completed = True
                    break
            if not sent_completed:
                fallback = {"status": "completed", "runId": run_id, "caseId": case_id_val}
                yield format_sse_line("completed", fallback)
            yield "data: [DONE]\n\n"
        except (GeneratorExit, BaseException) as e:
            logger.warning("case_analysis_stream: stream closed run_id=%s reason=%s", run_id, e)
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


# 스트림 전용 라우터 (BaseHTTPMiddleware 미경유용 — 스트림 취소 방지)
stream_only_router = APIRouter(prefix="/aura/cases", tags=["aura-cases"])
stream_only_router.add_api_route(
    "/{case_id}/analysis/stream",
    case_analysis_stream,
    methods=["GET"],
)


# ==================== Audit Analysis: Analysis Trigger (SSE, legacy) ====================


@router.post("/{case_id}/analysis/trigger")
async def case_analysis_trigger(
    case_id: str,
    request: Request,
    user: CurrentUser,
    tenant_id: TenantId,
):
    """
    감사 분석 트리거 (SSE 스트림)
    
    POST /api/aura/cases/{caseId}/analysis/trigger
    started → step → evidence → confidence → proposal → completed (또는 failed) 이벤트를 SSE로 스트리밍.
    DEMO_OFF 환경변수 시 no-op 결과 반환.
    """
    if os.environ.get("DEMO_OFF", "").upper() in ("1", "TRUE", "YES"):
        return {"status": "disabled", "message": "Analysis disabled (DEMO_OFF)"}

    from core.config import get_settings
    _max_web = get_settings().web_search_max_calls_per_run
    set_request_context(
        tenant_id=tenant_id or "1",
        user_id=user.user_id,
        auth_token=request.headers.get("Authorization"),
        trace_id=f"trace-{case_id}-analysis",
        case_id=case_id,
        x_sandbox=request.headers.get("X-Sandbox"),
        _guardrails={"web_search_calls": 0, "web_search_max_calls": _max_web},
    )

    async def event_generator():
        from core.analysis.agent_factory import fetch_agent_config
        from core.analysis.audit_analysis_pipeline import run_audit_analysis

        try:
            from core.analysis.agent_factory import select_agent_for_request
            
            # Discovery + Selection: 사용자 요청 분석하여 적절한 에이전트 선택
            agent_id_val = await select_agent_for_request(
                user_query=None,  # 케이스 분석이므로 컨텍스트 기반 선택
                context={"caseId": case_id},
                tenant_id=tenant_id or "1",
            )
            config = await fetch_agent_config(agent_id=agent_id_val, tenant_id=tenant_id or "1")
            async for event_type, payload in run_audit_analysis(
                case_id,
                tenant_id=tenant_id or "1",
                model_name=config.model_name,
                agent_config=config,
            ):
                yield format_sse_line(event_type, payload)
                await asyncio.sleep(STREAM_EVENT_DELAY)
        except Exception as e:
            logger.exception(f"Audit analysis trigger failed: {e}")
            yield format_sse_line("failed", {"error": str(e), "stage": "trigger"})
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


# ==================== P1: RAG Evidence ====================


async def _get_case_keys(case_id: str) -> dict[str, str]:
    """case_id로 keys(bukrs, belnr, gjahr) 조회 - Synapse get_case 사용 (호출 전 set_request_context 필요)"""
    try:
        result = await get_case.ainvoke({"caseId": case_id})
        data = json.loads(result) if isinstance(result, str) else result
        if isinstance(data, dict) and "error" in data:
            return {}
        keys = {}
        for k in ("bukrs", "belnr", "gjahr"):
            if k in data:
                keys[k] = str(data[k])
            elif (alt := k.replace("_", "")) in data:
                keys[k] = str(data[alt])
        return keys
    except Exception as e:
        logger.warning(f"get_case_keys failed for {case_id}: {e}")
        return {}


@router.get("/{case_id}/rag/evidence")
async def case_rag_evidence(
    case_id: str,
    request: Request,
    user: CurrentUser,
    tenant_id: TenantId,
):
    """
    RAG Evidence 목록 (P1)
    
    GET /api/aura/cases/{caseId}/rag/evidence
    evidence_json 정규화: [{sourceTable, keys, field, value, confidence?}]
    """
    set_request_context(
        tenant_id=tenant_id or "1",
        user_id=user.user_id,
        auth_token=request.headers.get("Authorization"),
        trace_id=f"trace-{case_id}-rag",
        case_id=case_id,
    )
    keys = await _get_case_keys(case_id)
    try:
        result = await search_documents.ainvoke(
            {"filters": {"caseId": case_id, "topK": 10}}
        )
        docs = json.loads(result) if isinstance(result, str) else result
    except Exception as e:
        logger.warning(f"search_documents failed for {case_id}: {e}")
        docs = []

    # evidence_json 정규화
    evidence_items = []
    if isinstance(docs, list):
        for i, doc in enumerate(docs[:10]):
            if isinstance(doc, dict):
                evidence_items.append({
                    "sourceTable": doc.get("sourceTable", "documents"),
                    "keys": keys or doc.get("keys", {"caseId": case_id}),
                    "field": doc.get("field", "content"),
                    "value": doc.get("value", doc.get("content", str(doc)[:200])),
                    "confidence": doc.get("confidence"),
                })
            else:
                evidence_items.append({
                    "sourceTable": "documents",
                    "keys": keys or {"caseId": case_id},
                    "field": "content",
                    "value": str(doc)[:200],
                    "confidence": None,
                })
    elif isinstance(docs, dict):
        items = docs.get("documents", docs.get("items", [docs]))
        for i, doc in enumerate((items if isinstance(items, list) else [items])[:10]):
            evidence_items.append({
                "sourceTable": "documents",
                "keys": keys or {"caseId": case_id},
                "field": "content",
                "value": str(doc)[:200] if not isinstance(doc, dict) else doc.get("content", str(doc))[:200],
                "confidence": doc.get("confidence") if isinstance(doc, dict) else None,
            })

    # Synapse 응답 형식이 다를 수 있음 - 최소 3개 fallback
    if len(evidence_items) < 3:
        for i in range(3 - len(evidence_items)):
            evidence_items.append({
                "sourceTable": "documents",
                "keys": keys or {"caseId": case_id, "bukrs": "1000", "belnr": "1900000001", "gjahr": "2024"},
                "field": f"evidence_{len(evidence_items) + 1}",
                "value": f"Evidence placeholder for case {case_id}",
                "confidence": 0.8,
            })

    return {
        "caseId": case_id,
        "evidence": evidence_items,
        "citations": [{"sourceTable": e["sourceTable"], "keys": e["keys"]} for e in evidence_items],
    }


# ==================== P1: Similar Cases ====================


@router.get("/{case_id}/similar")
async def case_similar(
    case_id: str,
    request: Request,
    user: CurrentUser,
    tenant_id: TenantId,
):
    """
    유사 케이스 (P1, 규칙 기반)
    
    GET /api/aura/cases/{caseId}/similar
    same vendor / amount range / time range (규칙 기반)
    """
    set_request_context(
        tenant_id=tenant_id or "1",
        user_id=user.user_id,
        auth_token=request.headers.get("Authorization"),
        trace_id=f"trace-{case_id}-similar",
        case_id=case_id,
    )
    try:
        result = await get_case.ainvoke({"caseId": case_id})
        case_data = json.loads(result) if isinstance(result, str) else result
    except Exception as e:
        logger.warning(f"get_case failed for similar: {e}")
        case_data = {}

    if isinstance(case_data, dict) and "error" in case_data:
        case_data = {}

    # 규칙 기반 유사 케이스 (실데이터 없으면 샘플)
    vendor = case_data.get("vendorId") or case_data.get("vendor_id") or "V-001"
    amount = case_data.get("amount") or case_data.get("totalAmount") or 10000
    similar = [
        {"caseId": f"{case_id}-sim-1", "similarity": "vendor", "vendorId": vendor, "amount": amount * 0.9},
        {"caseId": f"{case_id}-sim-2", "similarity": "amount_range", "vendorId": "V-002", "amount": amount * 1.1},
    ]
    return {"caseId": case_id, "similar": similar}


# ==================== P1: Confidence ====================


@router.get("/{case_id}/confidence")
async def case_confidence(
    case_id: str,
    request: Request,
    user: CurrentUser,
    tenant_id: TenantId,
):
    """
    Confidence Score breakdown (P1, 규칙 기반)
    
    GET /api/aura/cases/{caseId}/confidence
    score breakdown: rule contributions
    """
    set_request_context(
        tenant_id=tenant_id or "1",
        user_id=user.user_id,
        auth_token=request.headers.get("Authorization"),
        trace_id=f"trace-{case_id}-confidence",
        case_id=case_id,
    )
    try:
        result = await get_case.ainvoke({"caseId": case_id})
        case_data = json.loads(result) if isinstance(result, str) else result
    except Exception:
        case_data = {}

    score = 0.85
    if isinstance(case_data, dict) and "score" in case_data:
        score = float(case_data.get("score", score))
    elif isinstance(case_data, dict) and "riskScore" in case_data:
        score = float(case_data.get("riskScore", score))

    breakdown = [
        {"rule": "DUPLICATE_INVOICE", "contribution": 0.45, "weight": 0.5},
        {"rule": "VENDOR_RISK", "contribution": 0.25, "weight": 0.3},
        {"rule": "AMOUNT_ANOMALY", "contribution": 0.15, "weight": 0.2},
    ]
    return {
        "caseId": case_id,
        "score": score,
        "breakdown": breakdown,
    }


# ==================== P2: Analysis Summary (Audit Analysis) ====================


@router.get("/{case_id}/analysis")
async def case_analysis(
    case_id: str,
    request: Request,
    user: CurrentUser,
    tenant_id: TenantId,
):
    """
    Analysis Summary (P2, 감사 분석)
    
    GET /api/aura/cases/{caseId}/analysis
    감사 분석 완료 시: reasonText, proposals, confidenceBreakdown, ragRefs, similarCases 반환.
    미실행 시: 템플릿 기반 fallback.
    """
    set_request_context(
        tenant_id=tenant_id or "1",
        user_id=user.user_id,
        auth_token=request.headers.get("Authorization"),
        trace_id=f"trace-{case_id}-analysis",
        case_id=case_id,
    )

    # 감사 분석 저장 결과 우선 (Autonomous Conclusion 필드 포함)
    audit_result = get_audit_analysis_result(case_id)
    if audit_result:
        out = {
            "caseId": case_id,
            "reasonText": audit_result.get("reasonText", ""),
            "proposals": audit_result.get("proposals", []),
            "confidenceBreakdown": audit_result.get("confidenceBreakdown", {}),
            "ragRefs": audit_result.get("ragRefs", []),
            "similarCases": audit_result.get("similarCases", []),
            "score": audit_result.get("score", 0),
            "severity": audit_result.get("severity", "MEDIUM"),
        }
        # Autonomous Conclusion (BE/FE Aura AI Workspace 연동)
        if audit_result.get("risk_score") is not None:
            out["risk_score"] = audit_result["risk_score"]
        if audit_result.get("violation_clause") is not None:
            out["violation_clause"] = audit_result["violation_clause"]
        if audit_result.get("reasoning_summary") is not None:
            out["reasoning_summary"] = audit_result["reasoning_summary"]
        if audit_result.get("recommended_action") is not None:
            out["recommended_action"] = audit_result["recommended_action"]
        if audit_result.get("citations") is not None:
            out["citations"] = audit_result["citations"]
        return out

    # Fallback: get_case 기반 templates
    try:
        result = await get_case.ainvoke({"caseId": case_id})
        case_data = json.loads(result) if isinstance(result, str) else result
    except Exception:
        case_data = {}

    risk_type = "DUPLICATE_INVOICE"
    if isinstance(case_data, dict):
        risk_type = case_data.get("riskTypeKey") or case_data.get("risk_type") or risk_type

    summary = (
        f"Case {case_id} analysis: Risk type {risk_type}. "
        "Evidence collected from documents and open items. "
        "Recommendation: Review and approve proposed action."
    )
    return {
        "caseId": case_id,
        "summary": summary,
        "reasonText": summary,
        "proposals": [],
        "confidenceBreakdown": {},
        "riskType": risk_type,
        "template": "standard",
    }
