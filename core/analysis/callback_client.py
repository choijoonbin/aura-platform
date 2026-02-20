"""
공통 콜백 HTTP 전송

재시도(지수 backoff) 및 공통 헤더. 감사 분석 / Phase3 콜백 모듈에서 사용.
"""

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CALLBACK_MAX_RETRIES = 3
CALLBACK_TIMEOUT = 30.0
SUCCESS_STATUS_CODES = (200, 201, 202)


async def post_with_retry(
    url: str,
    json_payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    success_status_codes: tuple[int, ...] = SUCCESS_STATUS_CODES,
) -> bool:
    """
    JSON POST 전송, 실패 시 재시도 (지수 backoff).

    Args:
        url: 전송 대상 URL
        json_payload: JSON body
        headers: 요청 헤더 (None이면 Content-Type: application/json 만 사용)
        success_status_codes: 성공으로 볼 상태 코드

    Returns:
        성공 시 True, 재시도 후에도 실패 시 False
    """
    request_headers: dict[str, str] = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)

    # 디버그: 콜백 페이로드 로깅 (민감 데이터 제외)
    payload_summary = {
        k: (v if k not in ("finalResult", "evidence", "ragRefs") else f"<{type(v).__name__}>")
        for k, v in json_payload.items()
    }
    logger.info("Callback sending: url=%s payload_keys=%s summary=%s", url[:80], list(json_payload.keys()), payload_summary)
    
    last_error: Exception | None = None
    for attempt in range(CALLBACK_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=CALLBACK_TIMEOUT) as client:
                resp = await client.post(url, json=json_payload, headers=request_headers)
                if resp.status_code in success_status_codes:
                    logger.info("Callback ok url=%s status_code=%s", url[:80], resp.status_code)
                    return True
                logger.warning(
                    "Callback attempt %s got %s: %s",
                    attempt + 1, resp.status_code, resp.text[:200],
                )
        except Exception as e:
            last_error = e
            delay = 2 ** attempt
            logger.warning("Callback attempt %s failed: %s, retry in %ss", attempt + 1, e, delay)
            await asyncio.sleep(delay)

    logger.error("Callback failed after %s retries: %s", CALLBACK_MAX_RETRIES, last_error)
    return False
