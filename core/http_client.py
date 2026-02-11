"""
공통 HTTP 클라이언트

Synapse·외부 API 호출 시 중복을 줄이기 위한 비동기 POST 헬퍼.
(재시도·백오프는 callback_client 등 호출처에서 처리)
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def post_json(
    url: str,
    json_body: Any,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> tuple[bool, int, str]:
    """
    JSON POST 요청 수행.

    Returns:
        (성공 여부, status_code, response.text)
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url,
                json=json_body,
                headers=headers or {},
            )
            return (200 <= resp.status_code < 400, resp.status_code, resp.text)
    except Exception as e:
        logger.warning("HTTP POST error: %s", e)
        return (False, 0, str(e))
