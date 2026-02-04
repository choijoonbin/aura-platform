"""
Request-scoped context for async operations.

Synapse Tool API 호출 시 tenant/user/trace 헤더를 전달하기 위해
요청 스코프 컨텍스트를 제공합니다.
"""

from contextvars import ContextVar
from typing import Any

# 요청 스코프: tenant_id, user_id, auth_token, trace_id
_request_context: ContextVar[dict[str, Any]] = ContextVar(
    "request_context",
    default={},
)


def set_request_context(
    tenant_id: str,
    user_id: str,
    auth_token: str | None,
    trace_id: str | None = None,
    gateway_request_id: str | None = None,
    case_id: str | None = None,
    case_key: str | None = None,
) -> None:
    """요청 컨텍스트 설정 (스트림 핸들러 시작 시 호출)
    
    C-2: correlation 키(traceId, gatewayRequestId, caseId, caseKey, actionId)를
    Audit evidence_json에 보강하기 위해 case_id, case_key를 저장합니다.
    """
    _request_context.set({
        "tenant_id": tenant_id,
        "user_id": user_id,
        "auth_token": auth_token,
        "trace_id": trace_id,
        "gateway_request_id": gateway_request_id,
        "case_id": case_id,
        "case_key": case_key,
    })


def get_request_context() -> dict[str, Any]:
    """요청 컨텍스트 조회 (Synapse Tool 호출 시 사용)"""
    return _request_context.get().copy()


def get_synapse_headers(idempotency_key: str | None = None) -> dict[str, str]:
    """
    Synapse Tool API 호출용 헤더 반환.
    
    X-Tenant-ID, X-User-ID, X-Trace-ID, Authorization(JWT) 포함.
    멱등성 필요 시 X-Idempotency-Key 추가.
    """
    ctx = _request_context.get()
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if ctx.get("tenant_id"):
        headers["X-Tenant-ID"] = ctx["tenant_id"]
    if ctx.get("user_id"):
        headers["X-User-ID"] = ctx["user_id"]
    if ctx.get("trace_id"):
        headers["X-Trace-ID"] = ctx["trace_id"]
    if ctx.get("auth_token"):
        token = ctx["auth_token"]
        if not token.startswith("Bearer "):
            token = f"Bearer {token}"
        headers["Authorization"] = token
    if idempotency_key:
        headers["X-Idempotency-Key"] = idempotency_key
    return headers
