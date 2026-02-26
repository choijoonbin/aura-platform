"""
MCP adapter (Aura-side).

실제 MCP 서버가 준비되기 전까지는 payload-first 기반으로 사실(Fact) 컨텍스트를
표준 형태로 생성한다. 이후 MCP 연동 시 본 모듈의 조회 구현만 교체하면 된다.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx
from core.analysis.policy_engine import (
    derive_is_holiday,
    normalize_hr_status,
    normalize_mcc_code,
    normalize_occurred_at,
)
from core.config import get_settings
from core.context import get_request_context, get_synapse_headers

logger = logging.getLogger(__name__)


def _extract(payload: dict[str, Any], *keys: str) -> Any:
    nested = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    for k in keys:
        if payload.get(k) is not None:
            return payload.get(k)
        if nested.get(k) is not None:
            return nested.get(k)
    return None


def _to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().upper()
    if s in {"TRUE", "Y", "1"}:
        return True
    if s in {"FALSE", "N", "0"}:
        return False
    return None


def _weekday_name_ko(occurred_at: str | None) -> str | None:
    if not occurred_at:
        return None
    try:
        dt = datetime.fromisoformat(occurred_at)
    except ValueError:
        return None
    return ["월", "화", "수", "목", "금", "토", "일"][dt.weekday()]


def build_fact_context(
    payload: dict[str, Any] | None,
    *,
    case_id: str | None = None,
    stage: str = "analysis",
) -> dict[str, Any]:
    """
    payload 기반 MCP 호환 fact context 생성.

    Returns:
      {
        "enabled": bool,
        "mode": "payload_only" | ...,
        "stage": str,
        "facts": {...},
        "quality": {...},
      }
    """
    settings = get_settings()
    enabled = bool(getattr(settings, "mcp_enabled", False))
    mode = str(getattr(settings, "mcp_mode", "payload_only") or "payload_only").strip().lower()
    data = payload if isinstance(payload, dict) else {}

    occurred_at = normalize_occurred_at(_extract(data, "occurredAt", "occurred_at"))
    hr_status, hr_status_raw_norm = normalize_hr_status(_extract(data, "hrStatus", "hr_status"))
    hr_status_raw_input = _extract(data, "hrStatusRaw", "hr_status_raw")
    hr_status_raw = str(hr_status_raw_input).strip() if hr_status_raw_input is not None else hr_status_raw_norm
    mcc_code, mcc_code_raw = normalize_mcc_code(_extract(data, "mccCode", "mcc_code"))
    holiday_input = _to_bool(_extract(data, "isHoliday", "is_holiday"))
    is_holiday, holiday_source = derive_is_holiday(
        occurred_at=occurred_at,
        hr_status=hr_status,
        hr_status_raw=hr_status_raw,
        is_holiday_input=holiday_input,
    )
    holiday_type = str(_extract(data, "holidayType", "holiday_type") or "").strip().upper()
    if not holiday_type:
        holiday_type = "WEEKEND" if is_holiday else "NONE"

    missing_fields: list[str] = []
    for field_name, val in (
        ("occurredAt", occurred_at),
        ("amount", _extract(data, "amount", "totalAmount")),
        ("hrStatus", hr_status),
        ("mccCode", mcc_code),
        ("case_type", _extract(data, "case_type", "caseType")),
    ):
        if val in (None, ""):
            missing_fields.append(field_name)

    facts = {
        "caseId": case_id,
        "stage": stage,
        "occurredAt": occurred_at,
        "weekdayKo": _weekday_name_ko(occurred_at),
        "isHoliday": bool(is_holiday),
        "holidayType": holiday_type,
        "holidayDecisionSource": holiday_source,
        "hrStatus": hr_status,
        "hrStatusRaw": hr_status_raw,
        "mccCode": mcc_code,
        "mccCodeRaw": mcc_code_raw,
        "expenseType": _extract(data, "expenseType", "expense_type"),
        "expenseTypeName": _extract(data, "expenseTypeName", "expense_type_name"),
        "mccRiskCategory": _extract(data, "mccRiskCategory", "mcc_risk_category"),
        "isWeekendAllowed": _extract(data, "isWeekendAllowed", "is_weekend_allowed"),
        "budgetExceeded": _to_bool(_extract(data, "budgetExceeded", "budget_exceeded")),
        "relatedArticleHint": _extract(data, "relatedArticleHint", "related_article_hint"),
        "sourceSystem": _extract(data, "sourceSystem", "source_system"),
        "sourceTimestamp": _extract(data, "sourceTimestamp", "source_timestamp"),
    }

    return {
        "enabled": enabled,
        "mode": mode,
        "stage": stage,
        "facts": facts,
        "quality": {
            "input_partial": bool(missing_fields),
            "missing_fields": missing_fields,
        },
    }


def _tool_base_url() -> str | None:
    settings = get_settings()
    base = str(getattr(settings, "mcp_base_url", "") or "").strip()
    if not base:
        return None
    return base.rstrip("/")


def _tool_path(base: str, path: str) -> str:
    if base.endswith("/mcp/tools"):
        return f"{base}{path}"
    if base.endswith("/api/mcp/tools"):
        return f"{base}{path}"
    if base.endswith("/api/synapse/mcp/tools"):
        return f"{base}{path}"
    if "/api/mcp" in base:
        return f"{base}/tools{path}"
    if "/api/synapse" in base:
        return f"{base}/mcp/tools{path}"
    return f"{base}/api/synapse/mcp/tools{path}"


async def _post_tool(
    path: str,
    payload: dict[str, Any],
    *,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    base = _tool_base_url()
    if not base:
        return None
    settings = get_settings()
    timeout = float(getattr(settings, "mcp_timeout_seconds", 5.0))
    url = _tool_path(base, path)
    headers = get_synapse_headers()
    if extra_headers:
        headers.update({k: v for k, v in extra_headers.items() if v not in (None, "")})
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json() if resp.content else {}
    except Exception as e:
        logger.warning("mcp_adapter tool call failed path=%s url=%s err=%s", path, url, e)
        return None
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return None
    if not bool(data.get("success", False)):
        logger.info(
            "mcp_adapter tool result error path=%s trace=%s code=%s msg=%s",
            path,
            data.get("traceId"),
            data.get("errorCode"),
            data.get("errorMessage"),
        )
        return None
    return data.get("data") if isinstance(data.get("data"), dict) else None


async def resolve_fact_context(
    payload: dict[str, Any] | None,
    *,
    case_id: str | None = None,
    stage: str = "analysis",
) -> dict[str, Any]:
    """
    MCP fact context 최종 생성.
    - payload_only: 로컬 규칙만 사용
    - hybrid/remote: MCP tool 호출로 fact 보강 (실패 시 로컬 fallback)
    """
    base_ctx = build_fact_context(payload, case_id=case_id, stage=stage)
    settings = get_settings()
    mode = str(getattr(settings, "mcp_mode", "payload_only") or "payload_only").strip().lower()
    if not bool(getattr(settings, "mcp_enabled", False)):
        return base_ctx
    if mode not in {"hybrid", "remote"}:
        logger.info("mcp_adapter running in payload_only mode stage=%s case_id=%s", stage, case_id)
        return base_ctx
    if not _tool_base_url():
        logger.warning(
            "mcp_adapter mode=%s but mcp_base_url is empty (stage=%s case_id=%s). fallback=payload_only",
            mode,
            stage,
            case_id,
        )
        return base_ctx
    data = payload if isinstance(payload, dict) else {}
    request_ctx = get_request_context() or {}
    default_headers = get_synapse_headers()
    tenant_id = str(default_headers.get("X-Tenant-ID") or request_ctx.get("tenant_id") or "").strip() or None
    user_id = (
        _extract(data, "userId", "user_id", "requestedByUserId", "requested_by_user_id")
        or default_headers.get("X-User-ID")
        or request_ctx.get("user_id")
    )
    user_id_str = str(user_id).strip() if user_id is not None else None
    trace_id = str(default_headers.get("X-Trace-ID") or request_ctx.get("trace_id") or "").strip() or None
    effective_headers = {}
    if tenant_id:
        effective_headers["X-Tenant-ID"] = tenant_id
    if user_id_str:
        effective_headers["X-User-ID"] = user_id_str
    if trace_id:
        effective_headers["X-Trace-ID"] = trace_id
    missing_header_fields: list[str] = []
    if not tenant_id:
        missing_header_fields.append("X-Tenant-ID")
    if not user_id_str:
        missing_header_fields.append("X-User-ID")
    if missing_header_fields:
        quality = dict(base_ctx.get("quality") or {})
        existing = [str(v) for v in quality.get("missing_fields", []) if str(v).strip()]
        merged = list(dict.fromkeys(existing + missing_header_fields))
        quality.update({
            "input_partial": True,
            "missing_fields": merged,
            "mcp_enriched": False,
            "mcp_calls_ok": 0,
            "mcp_skipped": True,
            "mcp_skip_reason": "MCP_HEADERS_MISSING",
            "mcp_missing_headers": missing_header_fields,
        })
        out = dict(base_ctx)
        out["mode"] = mode
        out["quality"] = quality
        logger.warning(
            "mcp_adapter skip remote calls stage=%s case_id=%s reason=MCP_HEADERS_MISSING missing_headers=%s",
            stage,
            case_id,
            missing_header_fields,
        )
        return out
    facts = dict(base_ctx.get("facts") or {})
    enriched_calls = 0

    # 1) business-calendar
    occurred_at = facts.get("occurredAt")
    if occurred_at and user_id_str:
        cal = await _post_tool(
            "/business-calendar",
            {"occurredAt": occurred_at, "userId": user_id_str},
            extra_headers=effective_headers,
        )
        if isinstance(cal, dict):
            enriched_calls += 1
            facts["isHoliday"] = cal.get("isHoliday", facts.get("isHoliday"))
            facts["holidayType"] = cal.get("holidayType", facts.get("holidayType"))
            facts["holidayDecisionSource"] = cal.get("decisionSource", facts.get("holidayDecisionSource"))
            facts["hrStatus"] = cal.get("hrStatus", facts.get("hrStatus"))
            facts["hrStatusRaw"] = cal.get("hrStatusRaw", facts.get("hrStatusRaw"))

    # 2) master-data
    md_req = {
        "mccCode": facts.get("mccCodeRaw") or facts.get("mccCode"),
        "expenseType": facts.get("expenseType"),
        "hrStatus": facts.get("hrStatusRaw") or facts.get("hrStatus"),
    }
    if any(v not in (None, "") for v in md_req.values()):
        md = await _post_tool("/master-data", md_req, extra_headers=effective_headers)
        if isinstance(md, dict):
            enriched_calls += 1
            mcc = md.get("mcc") if isinstance(md.get("mcc"), dict) else {}
            exp = md.get("expenseType") if isinstance(md.get("expenseType"), dict) else {}
            hr = md.get("hrStatus") if isinstance(md.get("hrStatus"), dict) else {}
            if mcc.get("normalized"):
                facts["mccCode"] = mcc.get("normalized")
            if mcc.get("raw"):
                facts["mccCodeRaw"] = mcc.get("raw")
            if exp.get("normalizedName"):
                facts["expenseTypeName"] = exp.get("normalizedName")
            if hr.get("normalized"):
                facts["hrStatus"] = hr.get("normalized")
            if hr.get("raw"):
                facts["hrStatusRaw"] = hr.get("raw")

    # 3) policy-regulation (힌트 조항이 있을 때만)
    rel = facts.get("relatedArticleHint")
    article_hint = None
    if isinstance(rel, list) and rel:
        article_hint = str(rel[0]).strip()
    elif isinstance(rel, str) and rel.strip():
        article_hint = rel.strip()
    if article_hint:
        pol = await _post_tool(
            "/policy-regulation",
            {"article": article_hint, "effectiveAt": occurred_at},
            extra_headers=effective_headers,
        )
        if isinstance(pol, dict):
            enriched_calls += 1
            facts["policyItemCount"] = pol.get("count")

    out = dict(base_ctx)
    out["mode"] = mode
    out["facts"] = facts
    out["quality"] = {
        **(base_ctx.get("quality") or {}),
        "mcp_enriched": enriched_calls > 0,
        "mcp_calls_ok": enriched_calls,
    }
    logger.info(
        "mcp_adapter resolved stage=%s case_id=%s mode=%s occurredAt=%s user_id=%s calls_ok=%s",
        stage,
        case_id,
        mode,
        occurred_at,
        user_id_str,
        enriched_calls,
    )
    return out
