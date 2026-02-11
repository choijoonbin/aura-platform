"""
Phase2 BE Callback

분석 완료 시 BE로 POST. 재시도 3회 (지수 backoff).
멱등성: 동일 (runId, proposal) 재전송 시 BE dedup 처리.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from core.config import settings
from core.analysis.callback_client import post_with_retry

logger = logging.getLogger(__name__)


def _build_final_result(phase2_result: dict[str, Any]) -> dict[str, Any]:
    """phase2_result → BE finalResult (confidence, similar 필드명)"""
    return {
        "score": phase2_result.get("score", 0),
        "severity": phase2_result.get("severity", "MEDIUM"),
        "reasonText": phase2_result.get("reasonText", ""),
        "confidence": phase2_result.get("confidenceBreakdown", phase2_result.get("confidence", {})),
        "evidence": phase2_result.get("evidence", phase2_result.get("ragRefs", []))[:10],
        "ragRefs": phase2_result.get("ragRefs", []),
        "similar": phase2_result.get("similarCases", phase2_result.get("similar", [])),
        "proposals": [
            {
                "type": p.get("type"),
                "riskLevel": p.get("riskLevel"),
                "rationale": p.get("rationale"),
                "payload": p.get("payload", {}),
                "createdAt": p.get("createdAt", datetime.now(timezone.utc).isoformat()),
                "requiresApproval": p.get("requiresApproval", True),
            }
            for p in phase2_result.get("proposals", [])
        ],
    }


async def send_callback(
    run_id: str,
    case_id: str,
    status: str,
    final_result: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> bool:
    """
    BE 콜백 전송. status=COMPLETED 시 finalResult 포함, FAILED 시 partialEvents에 에러.
    
    Returns:
        성공 시 True, 실패 시 False (재시도 후)
    """
    base = settings.dwp_gateway_url.rstrip("/")
    path = settings.callback_path.lstrip("/")
    url = f"{base}/{path}" if not path.startswith("http") else path

    payload: dict[str, Any] = {
        "runId": run_id,
        "caseId": case_id,
        "status": status,
    }
    if final_result:
        payload["finalResult"] = _build_final_result(final_result)
    if error_message:
        payload["partialEvents"] = [{"stage": "callback", "errorMessage": error_message}]

    return await post_with_retry(url, payload, success_status_codes=(200,))
