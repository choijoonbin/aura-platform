"""
Synapse Finance Tool Module

Synapse 백엔드 Tool API를 호출하는 HTTP 기반 도구입니다.
Aura는 Postgres를 직접 읽지 않고 Synapse를 통해 데이터를 조회합니다.

표준화 사항:
- 모든 호출: X-Tenant-ID, X-User-ID, X-Trace-ID, Authorization(JWT)
- 5xx/timeout 시 exponential backoff + max retry
- simulate/execute: X-Idempotency-Key로 중복 방지
- Audit: 주요 단계에서 audit_event_log용 이벤트 발행 (C-1 명세)
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any

import httpx
from langchain_core.tools import tool
from pydantic import Field

from core.config import settings
from core.context import get_request_context, get_synapse_headers

logger = logging.getLogger(__name__)

# Synapse Agent Tool API
# 신규(Gateway 8080): http://localhost:8080/api/synapse/agent-tools → /cases, /documents 등
# 구(8081): http://localhost:8081 → /tools/finance/cases 등
BASE_URL = settings.synapse_base_url.rstrip("/")
_USE_AGENT_TOOLS = "agent-tools" in BASE_URL


def _emit_audit_event(event: Any) -> None:
    """Audit 이벤트 발행 (fire-and-forget)"""
    try:
        from core.audit.writer import get_audit_writer
        get_audit_writer().ingest_fire_and_forget(event)
    except Exception as e:
        logger.debug(f"Audit emit skipped: {e}")
TIMEOUT = settings.synapse_timeout
MAX_RETRIES = settings.synapse_max_retries


def _get_headers(idempotency_key: str | None = None) -> dict[str, str]:
    """Synapse 호출용 헤더 (tenant/user/trace 포함)"""
    try:
        return get_synapse_headers(idempotency_key=idempotency_key)
    except LookupError:
        base = {"Content-Type": "application/json", "Accept": "application/json"}
        if idempotency_key:
            base["X-Idempotency-Key"] = idempotency_key
        return base


def _path(p: str) -> str:
    """경로 (agent-tools 미사용 시 /tools/finance prefix)"""
    return p if _USE_AGENT_TOOLS else f"/tools/finance{p}"


async def _synapse_request_with_retry(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_data: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> str:
    """
    Synapse HTTP 요청 (재시도 정책 적용)
    
    5xx, timeout 시 exponential backoff로 최대 MAX_RETRIES 재시도.
    """
    url = f"{BASE_URL}{path}"
    headers = _get_headers(idempotency_key)
    
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                if method == "GET":
                    resp = await client.get(url, headers=headers, params=params or {})
                else:
                    resp = await client.post(url, headers=headers, json=json_data or {})
                
                # 5xx 재시도
                if resp.status_code >= 500 and attempt < MAX_RETRIES:
                    delay = 2 ** attempt  # 1, 2, 4 초
                    logger.warning(
                        f"Synapse {method} {path} returned {resp.status_code}, "
                        f"retry {attempt + 1}/{MAX_RETRIES} in {delay}s"
                    )
                    await asyncio.sleep(delay)
                    continue
                
                resp.raise_for_status()
                return resp.text
                
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_error = e
            if attempt < MAX_RETRIES:
                delay = 2 ** attempt
                logger.warning(
                    f"Synapse {method} {path} timeout/connect error, "
                    f"retry {attempt + 1}/{MAX_RETRIES} in {delay}s: {e}"
                )
                await asyncio.sleep(delay)
            else:
                raise
        except httpx.HTTPStatusError as e:
            if e.response.status_code >= 500 and attempt < MAX_RETRIES:
                delay = 2 ** attempt
                logger.warning(
                    f"Synapse {method} {path} 5xx, retry {attempt + 1}/{MAX_RETRIES} in {delay}s"
                )
                await asyncio.sleep(delay)
                continue
            raise
    
    if last_error:
        raise last_error
    return ""


async def _synapse_get(path: str, params: dict[str, Any] | None = None) -> str:
    """Synapse GET 요청"""
    return await _synapse_request_with_retry("GET", path, params=params)


async def _synapse_post(
    path: str,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
) -> str:
    """Synapse POST 요청 (멱등성 키 선택)"""
    return await _synapse_request_with_retry(
        "POST", path, json_data=payload, idempotency_key=idempotency_key
    )


@tool
async def get_case(caseId: str = Field(..., description="케이스 ID")) -> str:
    """
    케이스 상세 정보를 조회합니다.
    
    Synapse 백엔드 Tool API를 통해 중복송장 의심 케이스 등의 상세를 가져옵니다.
    """
    try:
        result = await _synapse_get(_path(f"/cases/{caseId}"))
        try:
            parsed = json.loads(result)
            if parsed.get("riskTypeKey") or parsed.get("risk_type") or parsed.get("score") is not None:
                from core.audit import AgentAuditEvent
                ctx = get_request_context()
                risk_key = parsed.get("riskTypeKey") or parsed.get("risk_type") or "unknown"
                score = float(parsed.get("score", 0)) if parsed.get("score") is not None else 0.0
                case_key = parsed.get("caseKey") or parsed.get("case_key") or ctx.get("case_key")
                event = AgentAuditEvent.detection_found(
                    tenant_id=ctx.get("tenant_id") or "default",
                    case_id=caseId,
                    risk_type_key=str(risk_key),
                    score=score,
                    trace_id=ctx.get("trace_id"),
                    caseKey=case_key,
                )
                _emit_audit_event(event)
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
        return result
    except httpx.HTTPStatusError as e:
        logger.error(f"get_case failed: {e}")
        return json.dumps({"error": str(e), "status_code": e.response.status_code})
    except Exception as e:
        logger.error(f"get_case failed: {e}")
        return json.dumps({"error": str(e)})


def _is_invalid_param_value(v: str | None) -> bool:
    """LLM이 Field 메타데이터를 값으로 넘긴 경우 감지"""
    if not v or not isinstance(v, str):
        return True
    s = v.strip().lower()
    return "annotation" in s or "nonetype" in s or "required=" in s or "default=" in s


@tool
async def search_documents(
    filters: dict[str, Any] = Field(
        default_factory=dict,
        description="검색 필터 (caseId, bukrs, gjahr, page, size 등)",
    )
) -> str:
    """
    문서를 검색합니다.
    
    Synapse: GET /documents (query: bukrs, gjahr, page, size 등).
    caseId만 있으면 get_case로 case 조회 후 bukrs/gjahr 추출하여 documents 호출.
    """
    start = time.perf_counter()
    try:
        case_id = filters.get("caseId") or filters.get("case_id")
        top_k = filters.get("topK") or filters.get("top_k") or filters.get("size") or 10
        page = filters.get("page", 0)
        size = int(top_k) if isinstance(top_k, (int, float)) else 10

        if case_id and not (filters.get("bukrs") or filters.get("gjahr")):
            case_resp = await _synapse_get(_path(f"/cases/{case_id}"))
            case_data = json.loads(case_resp) if isinstance(case_resp, str) else case_resp
            if isinstance(case_data, dict) and "error" not in case_data:
                bukrs = case_data.get("bukrs") or case_data.get("companyCode")
                gjahr = case_data.get("gjahr") or case_data.get("fiscalYear")
                if bukrs or gjahr:
                    filters = {**filters, "bukrs": bukrs, "gjahr": gjahr, "page": page, "size": size}
            else:
                filters = {"page": page, "size": size}

        params = {k: v for k, v in filters.items() if v is not None and k not in ("caseId", "case_id", "topK", "top_k", "documentIds")}
        params.setdefault("page", page)
        params.setdefault("size", size)
        result = await _synapse_get(_path("/documents"), params)
        latency_ms = int((time.perf_counter() - start) * 1000)
        doc_ids = filters.get("documentIds") or []
        if isinstance(doc_ids, str):
            doc_ids = [doc_ids]
        top_k = filters.get("topK") or filters.get("top_k") or filters.get("size") or 10
        try:
            from core.audit import AgentAuditEvent
            ctx = get_request_context()
            event = AgentAuditEvent.rag_queried(
                tenant_id=ctx.get("tenant_id") or "default",
                doc_ids=doc_ids[:20] if isinstance(doc_ids, list) else [],
                top_k=int(top_k) if isinstance(top_k, (int, float)) else 10,
                latency_ms=latency_ms,
                trace_id=ctx.get("trace_id"),
            )
            _emit_audit_event(event)
        except Exception:
            pass
        return result
    except httpx.HTTPStatusError as e:
        logger.error(f"search_documents failed: {e}")
        return json.dumps({"error": str(e), "status_code": e.response.status_code})
    except Exception as e:
        logger.error(f"search_documents failed: {e}")
        return json.dumps({"error": str(e)})


@tool
async def get_document(
    bukrs: str = Field(..., description="회사 코드"),
    belnr: str = Field(..., description="전표 번호"),
    gjahr: str = Field(..., description="회계 연도"),
) -> str:
    """
    단일 문서를 조회합니다.
    """
    try:
        return await _synapse_get(_path(f"/documents/{bukrs}/{belnr}/{gjahr}"))
    except httpx.HTTPStatusError as e:
        logger.error(f"get_document failed: {e}")
        return json.dumps({"error": str(e), "status_code": e.response.status_code})
    except Exception as e:
        logger.error(f"get_document failed: {e}")
        return json.dumps({"error": str(e)})


@tool
async def get_lineage(
    caseId: str | None = Field(default=None, description="케이스 ID (문서 조회용)"),
    belnr: str | None = Field(default=None, description="전표 번호"),
    gjahr: str | None = Field(default=None, description="회계 연도"),
    bukrs: str | None = Field(default=None, description="회사 코드"),
) -> str:
    """
    전표/문서의 라인리지(Lineage)를 조회합니다.
    caseId 우선, 없으면 belnr+gjahr(+bukrs) 사용. Field 메타데이터 문자열은 거부.
    """
    try:
        if belnr and gjahr and not _is_invalid_param_value(belnr) and not _is_invalid_param_value(gjahr):
            params: dict[str, Any] = {"belnr": belnr, "gjahr": gjahr}
            if bukrs and not _is_invalid_param_value(bukrs):
                params["bukrs"] = bukrs
            result = await _synapse_get(_path("/lineage"), params)
        elif caseId:
            result = await _synapse_get(_path("/lineage"), {"caseId": caseId})
        else:
            return json.dumps({"error": "caseId or (belnr, gjahr) required. Field 메타데이터 문자열을 전달하지 마세요."})
        return result
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return json.dumps({"lineage": [], "message": "Lineage endpoint not yet implemented"})
        logger.error(f"get_lineage failed: {e}")
        return json.dumps({"error": str(e), "status_code": e.response.status_code})
    except Exception as e:
        logger.error(f"get_lineage failed: {e}")
        return json.dumps({"error": str(e)})


@tool
async def get_entity(entityId: str = Field(..., description="엔티티 ID")) -> str:
    """
    엔티티 정보를 조회합니다.
    """
    try:
        return await _synapse_get(_path(f"/entities/{entityId}"))
    except httpx.HTTPStatusError as e:
        logger.error(f"get_entity failed: {e}")
        return json.dumps({"error": str(e), "status_code": e.response.status_code})
    except Exception as e:
        logger.error(f"get_entity failed: {e}")
        return json.dumps({"error": str(e)})


@tool
async def get_open_items(
    filters: dict[str, Any] = Field(
        default_factory=dict,
        description="필터 (type: AR|AP, overdueBucket, page, size 등)",
    )
) -> str:
    """
    미결 항목(Open Items)을 조회합니다.
    Synapse: GET /open-items (query: type, overdueBucket, page, size).
    caseId 필터는 Synapse 미지원.
    """
    try:
        params = {k: v for k, v in (filters or {}).items() if v is not None}
        params.setdefault("page", 0)
        params.setdefault("size", 20)
        return await _synapse_get(_path("/open-items"), params)
    except httpx.HTTPStatusError as e:
        logger.error(f"get_open_items failed: {e}")
        return json.dumps({"error": str(e), "status_code": e.response.status_code})
    except Exception as e:
        logger.error(f"get_open_items failed: {e}")
        return json.dumps({"error": str(e)})


@tool
async def simulate_action(
    caseId: str = Field(..., description="케이스 ID"),
    actionType: str = Field(..., description="액션 타입 (예: write_off, clear)"),
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="액션 파라미터",
    ),
    idempotency_key: str | None = Field(
        default=None,
        description="멱등성 키 (중복 호출 방지, 미지정 시 자동 생성)",
    ),
) -> str:
    """
    액션을 시뮬레이션합니다. 실제 실행 없이 결과를 미리 확인합니다.
    X-Idempotency-Key로 중복 호출 방지.
    """
    key = idempotency_key if isinstance(idempotency_key, str) else f"sim_{uuid.uuid4().hex[:16]}"
    action_id = f"sim_{caseId}_{actionType}_{key[:8]}"
    try:
        result = await _synapse_post(
            _path("/actions/simulate"),
            {"caseId": caseId, "actionType": actionType, "payload": payload},
            idempotency_key=key,
        )
        try:
            parsed = json.loads(result)
            sim_result = parsed.get("result") or parsed.get("status") or "PASS"
            diff_json = parsed.get("diffJson") or parsed.get("diff") or {}
            result_id = parsed.get("actionId") or action_id
        except (json.JSONDecodeError, TypeError):
            sim_result, diff_json, result_id = "PASS", {}, action_id
        try:
            from core.audit import AgentAuditEvent
            ctx = get_request_context()
            event = AgentAuditEvent.simulation_run(
                tenant_id=ctx.get("tenant_id") or "default",
                action_id=result_id,
                result=sim_result,
                diff_json=diff_json,
                trace_id=ctx.get("trace_id"),
                caseId=caseId,
                caseKey=ctx.get("case_key"),
            )
            _emit_audit_event(event)
        except Exception:
            pass
        return result
    except httpx.HTTPStatusError as e:
        logger.error(f"simulate_action failed: {e}")
        return json.dumps({"error": str(e), "status_code": e.response.status_code})
    except Exception as e:
        logger.error(f"simulate_action failed: {e}")
        return json.dumps({"error": str(e)})


@tool
async def propose_action(
    caseId: str = Field(..., description="케이스 ID"),
    actionType: str = Field(..., description="액션 타입"),
    payload: dict[str, Any] = Field(default_factory=dict, description="액션 파라미터"),
) -> str:
    """
    액션을 제안합니다. 위험도가 높거나 Guardrail에 걸리면 HITL 승인이 필요합니다.
    
    승인 필요 시 에이전트가 interrupt되고, 사용자 승인 후 execute_action으로 실행됩니다.
    """
    action_id = f"prop_{caseId}_{actionType}_{uuid.uuid4().hex[:8]}"
    try:
        result = await _synapse_post(
            _path("/actions/propose"),
            {"caseId": caseId, "actionType": actionType, "payload": payload},
        )
        try:
            parsed = json.loads(result)
            result_id = parsed.get("actionId") or parsed.get("id") or action_id
        except (json.JSONDecodeError, TypeError):
            result_id = action_id
        try:
            from core.audit import AgentAuditEvent
            ctx = get_request_context()
            case_key = ctx.get("case_key")
            event = AgentAuditEvent.action_proposed(
                tenant_id=ctx.get("tenant_id") or "default",
                action_id=result_id,
                requires_approval=True,
                trace_id=ctx.get("trace_id"),
                caseId=caseId,
                caseKey=case_key,
                actionType=actionType,
            )
            _emit_audit_event(event)
        except Exception:
            pass
        return result
    except httpx.HTTPStatusError as e:
        logger.error(f"propose_action failed: {e}")
        return json.dumps({"error": str(e), "status_code": e.response.status_code})
    except Exception as e:
        logger.error(f"propose_action failed: {e}")
        return json.dumps({"error": str(e)})


@tool
async def execute_action(
    actionId: str = Field(..., description="승인 완료된 액션 ID"),
    idempotency_key: str | None = Field(
        default=None,
        description="멱등성 키 (중복 실행 방지, 미지정 시 actionId 사용)",
    ),
) -> str:
    """
    승인 완료된 액션을 실행합니다.
    
    HITL 승인 후 Synapse 백엔드에서 전달한 actionId로 호출합니다.
    X-Idempotency-Key로 중복 실행 방지.
    """
    key = idempotency_key or actionId
    try:
        result = await _synapse_post(
            _path("/actions/execute"),
            {"actionId": actionId},
            idempotency_key=key,
        )
        try:
            parsed = json.loads(result)
            outcome = "SUCCESS" if not parsed.get("error") else "FAIL"
            sap_ref = parsed.get("sapRef") or parsed.get("sap_ref") or parsed.get("reference")
        except (json.JSONDecodeError, TypeError):
            outcome, sap_ref, parsed = "SUCCESS", None, {}
        try:
            from core.audit import AgentAuditEvent
            ctx = get_request_context()
            event = AgentAuditEvent.action_executed(
                tenant_id=ctx.get("tenant_id") or "default",
                action_id=actionId,
                outcome=outcome,
                sap_ref=sap_ref,
                trace_id=ctx.get("trace_id"),
                caseId=ctx.get("case_id"),
                caseKey=ctx.get("case_key"),
            )
            _emit_audit_event(event)
            if outcome == "SUCCESS" and sap_ref:
                sap_event = AgentAuditEvent.sap_write_success(
                    tenant_id=ctx.get("tenant_id") or "default",
                    sap_ref=sap_ref,
                    resource_id=actionId,
                    trace_id=ctx.get("trace_id"),
                )
                _emit_audit_event(sap_event)
            elif outcome == "FAIL":
                err_msg = parsed.get("error", "Unknown error") if parsed else "Unknown error"
                sap_event = AgentAuditEvent.sap_write_failed(
                    tenant_id=ctx.get("tenant_id") or "default",
                    sap_ref=sap_ref,
                    error=str(err_msg),
                    resource_id=actionId,
                    trace_id=ctx.get("trace_id"),
                )
                _emit_audit_event(sap_event)
        except Exception:
            pass
        return result
    except httpx.HTTPStatusError as e:
        logger.error(f"execute_action failed: {e}")
        err_result = json.dumps({"error": str(e), "status_code": e.response.status_code})
        try:
            from core.audit import AgentAuditEvent
            ctx = get_request_context()
            event = AgentAuditEvent.action_executed(
                tenant_id=ctx.get("tenant_id") or "default",
                action_id=actionId,
                outcome="FAIL",
                sap_ref=None,
                trace_id=ctx.get("trace_id"),
                caseId=ctx.get("case_id"),
                caseKey=ctx.get("case_key"),
            )
            _emit_audit_event(event)
        except Exception:
            pass
        return err_result
    except Exception as e:
        logger.error(f"execute_action failed: {e}")
        return json.dumps({"error": str(e)})


# HITL 승인이 필요한 도구 (Finance Agent에서 사용)
FINANCE_HITL_TOOLS = {"propose_action"}

# 전체 Finance 도구 목록
FINANCE_TOOLS = [
    get_case,
    search_documents,
    get_document,
    get_entity,
    get_open_items,
    get_lineage,
    simulate_action,
    propose_action,
    execute_action,
]
