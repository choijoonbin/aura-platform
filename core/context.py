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
    bukrs: str | None = None,
    belnr: str | None = None,
    gjahr: str | None = None,
    policy_config_source: str | None = None,
    policy_profile: str | None = None,
    **extra: Any,
) -> None:
    """요청 컨텍스트 설정 (스트림 핸들러 시작 시 호출)

    C-2: correlation 키(traceId, gatewayRequestId, caseId, caseKey, actionId)를
    Audit evidence_json에 보강하기 위해 case_id, case_key를 저장합니다.
    Phase 3: SAP 원천 전표 계보 연결을 위해 bukrs, belnr, gjahr를 저장합니다.
    Phase 4: 정책 참조 로그를 위해 policy_config_source, policy_profile를 저장합니다.
    """
    ctx: dict[str, Any] = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "auth_token": auth_token,
        "trace_id": trace_id,
        "gateway_request_id": gateway_request_id,
        "case_id": case_id,
        "case_key": case_key,
    }
    if bukrs is not None:
        ctx["bukrs"] = bukrs
    if belnr is not None:
        ctx["belnr"] = belnr
    if gjahr is not None:
        ctx["gjahr"] = gjahr
    if policy_config_source is not None:
        ctx["policy_config_source"] = policy_config_source
    if policy_profile is not None:
        ctx["policy_profile"] = policy_profile
    ctx.update(extra)
    _request_context.set(ctx)


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
