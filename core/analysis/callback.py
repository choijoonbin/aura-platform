"""
Phase2 BE Callback

분석 완료 시 BE로 POST. 재시도 3회 (지수 backoff).
멱등성: 동일 (runId, proposal) 재전송 시 BE dedup 처리.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

CALLBACK_MAX_RETRIES = 3


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

    last_error: Exception | None = None
    for attempt in range(CALLBACK_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    logger.info(f"Callback ok runId={run_id} status={status}")
                    return True
                logger.warning(f"Callback {run_id} attempt {attempt + 1} got {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            last_error = e
            delay = 2 ** attempt
            logger.warning(f"Callback {run_id} attempt {attempt + 1} failed: {e}, retry in {delay}s")
            await asyncio.sleep(delay)

    logger.error(f"Callback failed runId={run_id} after {CALLBACK_MAX_RETRIES} retries: {last_error}")
    return False
