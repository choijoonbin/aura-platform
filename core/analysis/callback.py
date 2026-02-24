"""
Case Audit Analysis — BE Callback

분석 완료 시 BE로 POST. 재시도 3회 (지수 backoff).
멱등성: 동일 (runId, proposal) 재전송 시 BE dedup 처리.
콜백 200 OK 후: POST …/cases/{caseId}/status 로 케이스 상태를 RESOLVED 로 갱신 (정상 종료 시만).
"""

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from core.config import settings
from core.analysis.callback_client import post_with_retry

logger = logging.getLogger(__name__)

# 케이스 상태 API: 정상 완료 시 호출. 실패(FAILED) 시에는 호출하지 않음.
CASE_STATUS_PATH = "/api/synapse/cases/{case_id}/status"
CASE_STATUS_ON_COMPLETE = "RESOLVED"
CASE_STATUS_TIMEOUT = 10.0


def _build_final_result(audit_result: dict[str, Any]) -> dict[str, Any]:
    """
    audit_result → BE finalResult.
    백엔드 case_analysis_result 테이블 저장 규격에 맞춤.
    필수 필드: violation_clause, risk_score, reasoning_summary, recommended_action, citations[].
    V65: doc_id, item_id, chunk_id, target_buzei 반드시 snake_case로 고정.
    decision_reason: Universal Compliance Auditor 규격(Reason + Evidence JSON) 강제.
    """
    score = audit_result.get("score", 0)
    # decision_reason: 구조화된 인사이트(Reason + Evidence JSON) — 단순 텍스트 대신 사용
    decision_reason = audit_result.get("decision_reason")
    if not decision_reason or not isinstance(decision_reason, dict):
        decision_reason = {
            "reason": audit_result.get("reasoning_summary", audit_result.get("reasonText", "")),
            "evidence": {},
            "citations": audit_result.get("citations", []),
        }
    return {
        "status": "COMPLETED",
        "score": score,
        "severity": audit_result.get("severity", "MEDIUM"),
        "reasonText": audit_result.get("reasonText", ""),
        "confidence": audit_result.get("confidenceBreakdown", audit_result.get("confidence", {})),
        "evidence": audit_result.get("evidence", audit_result.get("ragRefs", []))[:10],
        "ragRefs": audit_result.get("ragRefs", []),
        "similar": audit_result.get("similarCases", audit_result.get("similar", [])),
        "proposals": [
            {
                "type": p.get("type"),
                "riskLevel": p.get("riskLevel"),
                "rationale": p.get("rationale"),
                "payload": p.get("payload", {}),
                "createdAt": p.get("createdAt", datetime.now(timezone.utc).isoformat()),
                "requiresApproval": p.get("requiresApproval", True),
            }
            for p in audit_result.get("proposals", [])
        ],
        # case_analysis_result 필수 필드 (Autonomous Conclusion + citations)
        "risk_score": audit_result.get("risk_score", round(score * 100)),
        "violation_clause": audit_result.get("violation_clause", ""),
        "reasoning_summary": audit_result.get("reasoning_summary", audit_result.get("reasonText", "")),
        "recommended_action": audit_result.get("recommended_action", ""),
        "citations": audit_result.get("citations", []),
        # 최종 결과 고도화: 구조화된 인사이트 (Reason + Evidence JSON)
        "decision_reason": decision_reason,
        # V65 스키마: 문서·행·청크 식별 — snake_case 고정 (BE 저장 일치)
        "doc_id": audit_result.get("doc_id"),
        "item_id": audit_result.get("item_id"),
        "chunk_id": audit_result.get("chunk_id"),
        "target_buzei": audit_result.get("target_buzei"),
        "item_no": audit_result.get("item_no"),
    }


async def send_callback(
    run_id: str,
    case_id: str,
    status: str,
    final_result: dict[str, Any] | None = None,
    error_message: str | None = None,
    *,
    agent_id: str = "audit",
    version: str = "1.0",
    error_stage: str | None = None,
) -> bool:
    """
    BE 콜백 전송. status=COMPLETED 시 finalResult 포함, FAILED 시 partialEvents에 에러.
    agent_id, version을 반드시 포함하여 이력 관리 가능하게 함 (계약 협의 포인트).
    X-Sandbox: true일 때 is_sandbox 플래그 포함 (BE가 DB 저장 생략용).

    Returns:
        성공 시 True, 실패 시 False (재시도 후)
    """
    base = settings.dwp_gateway_url.rstrip("/")
    path = settings.callback_path.lstrip("/")
    url = f"{base}/{path}" if not path.startswith("http") else path

    try:
        from core.context import get_request_context
        ctx = get_request_context()
        is_sandbox = (ctx.get("x_sandbox") or "").strip().upper() in ("TRUE", "1", "YES")
        aura_trace_id = ctx.get("aura_trace_id")
    except Exception:
        is_sandbox = False
        aura_trace_id = None

    payload: dict[str, Any] = {
        "runId": run_id,
        "caseId": case_id,
        "status": status,
        "agent_id": agent_id,
        "version": version,
        "is_sandbox": is_sandbox,
    }
    if aura_trace_id:
        payload["trace"] = {"auraTraceId": aura_trace_id}
    if final_result:
        payload["finalResult"] = _build_final_result(final_result)
    if status.upper() == "FAILED":
        msg = error_message or "unknown"
        payload["error"] = {"message": msg, "stage": error_stage or "pipeline"}
        payload["partialEvents"] = [{"stage": "callback", "errorMessage": msg}]
    elif error_message:
        payload["partialEvents"] = [{"stage": "callback", "errorMessage": error_message}]

    ok = await post_with_retry(url, payload, success_status_codes=(200,))
    # 콜백 200 OK 후, 정상 완료 시에만 케이스 상태 API 호출 (진행중 → RESOLVED). 실패 건은 호출 안 함.
    if ok and status.upper() == "COMPLETED":
        await _notify_case_status(case_id)
    return ok


async def _notify_case_status(case_id: str, new_status: str = CASE_STATUS_ON_COMPLETE) -> bool:
    """
    POST …/api/synapse/cases/{caseId}/status — 케이스를 완료 처리.
    Body: { "status": "RESOLVED" }. 실패 시 로그만 남기고 True 반환(콜백 성공은 이미 완료).
    """
    base = settings.dwp_gateway_url.rstrip("/")
    path = CASE_STATUS_PATH.format(case_id=case_id).lstrip("/")
    url = f"{base}/{path}" if not path.startswith("http") else path
    body = {"status": new_status}
    try:
        from core.context import get_synapse_headers
        headers = get_synapse_headers()
    except Exception as e:
        logger.debug("case status headers skipped: %s", e)
        headers = {"Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=CASE_STATUS_TIMEOUT) as client:
            resp = await client.post(url, json=body, headers=headers)
            if resp.status_code in (200, 201, 202):
                logger.info("case status updated case_id=%s status=%s", case_id, new_status)
                return True
            logger.warning("case status API case_id=%s status_code=%s %s", case_id, resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("case status API failed case_id=%s: %s", case_id, e)
    return False
