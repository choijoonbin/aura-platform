"""
Phase3 BE Callback (PHASE3_SPEC §D)

resultCallbackUrl + auth(BEARER) 로 POST. payload: runId, caseId, status, analysis, proposals, meta.
"""

import logging
from typing import Any

from core.analysis.callback_client import post_with_retry

logger = logging.getLogger(__name__)


def _build_auth_headers(auth: dict[str, Any] | None) -> dict[str, str]:
    """auth dict → Authorization 헤더."""
    headers: dict[str, str] = {}
    if auth and isinstance(auth, dict):
        auth_type = (auth.get("type") or "").upper()
        token = auth.get("token") or ""
        if auth_type == "BEARER" and token:
            headers["Authorization"] = f"Bearer {token}"
    return headers


async def send_phase3_callback(
    result_callback_url: str,
    auth: dict[str, Any] | None,
    payload: dict[str, Any],
) -> bool:
    """
    Phase3 콜백 전송. callbacks.resultCallbackUrl 로 POST, auth 적용.

    Args:
        result_callback_url: BE가 제공한 콜백 URL
        auth: {"type": "BEARER", "token": "..."} (또는 None)
        payload: runId, caseId, status, analysis, proposals, meta

    Returns:
        성공 시 True, 실패 시 False
    """
    headers = {"Content-Type": "application/json", **_build_auth_headers(auth)}
    return await post_with_retry(result_callback_url, payload, headers=headers)
