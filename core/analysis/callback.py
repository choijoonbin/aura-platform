"""
Case Audit Analysis — BE Callback

분석 완료 시 BE로 POST. 재시도 3회 (지수 backoff).
멱등성: 동일 (runId, proposal) 재전송 시 BE dedup 처리.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from core.config import settings
from core.analysis.callback_client import post_with_retry

logger = logging.getLogger(__name__)


def _build_final_result(audit_result: dict[str, Any]) -> dict[str, Any]:
    """
    audit_result → BE finalResult.
    백엔드 case_analysis_result 테이블 저장 규격에 맞춤.
    필수 필드: violation_clause, risk_score, reasoning_summary, recommended_action, citations[].
    """
    score = audit_result.get("score", 0)
    return {
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

    return await post_with_retry(url, payload, success_status_codes=(200,))
