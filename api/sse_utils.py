"""
SSE(Server-Sent Events) 공통 유틸

라우트 간 중복을 줄이기 위한 헤더·포맷 헬퍼.
FE 요구: event: failed 시 반드시 한 줄 이상의 data (error 또는 message 문자열, 필요 시 stage) 포함.
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


def _normalize_failed_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    failed 이벤트용 payload 정규화.
    FE는 data의 error(문자열) 또는 message(문자열), 필요 시 stage를 파싱해 표시.
    event: failed 만 보내고 data를 비우면 FE가 "서버에서 상세 사유 미전달"로 처리하므로,
    반드시 error 또는 message(문자열)를 포함한다.
    """
    if not payload:
        return {"message": "분석 실패", "stage": "pipeline"}
    out = dict(payload)
    # error가 dict인 경우(Phase3 등): message, stage를 최상위로 풀어서 FE가 파싱하기 쉽게
    err = out.get("error")
    if isinstance(err, dict):
        if "message" in err and "message" not in out:
            out["message"] = err["message"]
        if "stage" in err and "stage" not in out:
            out["stage"] = err["stage"]
        out["error"] = err.get("message", str(err))
    elif isinstance(err, str) and err:
        out.setdefault("message", err)
    if not out.get("error") and not out.get("message"):
        out.setdefault("message", "분석 실패")
    if "stage" not in out:
        out.setdefault("stage", "pipeline")
    return out


def format_sse_line(event_type: str, payload: dict[str, Any]) -> str:
    """
    SSE 한 줄 형식: event + data (ensure_ascii=False).
    event_type은 그대로 "event:" 라인에 사용 (예: thought_pending, AGENT_STREAM, step).
    event: failed 인 경우 payload를 정규화하여 항상 error 또는 message(문자열)를 포함한다.
    """
    if event_type == "failed":
        payload = _normalize_failed_payload(payload)
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
