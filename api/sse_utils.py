"""
SSE(Server-Sent Events) 공통 유틸

라우트 간 중복을 줄이기 위한 헤더·포맷 헬퍼.
"""

import json
from typing import Any

# 스트리밍 응답에 공통으로 사용하는 헤더 (BE 중계·nginx 버퍼링 비활성화)
# 스펙: docs/aura/docs/streaming/AURA_SSE_SPEC.md
SSE_HEADERS = {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache, no-store",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def format_sse_line(event_type: str, payload: dict[str, Any]) -> str:
    """
    SSE 한 줄 형식: event + data (ensure_ascii=False).
    analysis-runs, cases run stream 등 공통 포맷용.
    """
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
