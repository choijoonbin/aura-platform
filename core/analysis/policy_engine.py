"""
Deterministic policy gate for finance analysis.

LLM 출력과 분리된 최종 안전장치로 사용한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

_HR_WORK_SET = {"WORK", "WORKING", "BUSINESS_TRIP"}
_HR_LEAVE_SET = {"LEAVE", "VACATION", "OFF"}
_HR_RAW_OFF = "OFF"
_HR_RAW_VACATION = "VACATION"


def normalize_hr_status(value: Any) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    raw = str(value).strip()
    if not raw:
        return None, None
    up = raw.upper()
    if up in _HR_WORK_SET:
        return "WORK", raw
    if up in _HR_LEAVE_SET:
        return "LEAVE", raw
    return up, raw


def normalize_mcc_code(value: Any) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    raw = str(value).strip()
    if not raw:
        return None, None
    return (raw, raw) if raw.isdigit() and len(raw) == 4 else ("unknown", raw)


def normalize_occurred_at(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # +09 -> +09:00 정규화
    if len(s) >= 3 and (s.endswith("+09") or s.endswith("-09")):
        s = f"{s}:00"
    return s


def is_weekend(occurred_at: str | None) -> bool:
    if not occurred_at:
        return False
    try:
        dt = datetime.fromisoformat(occurred_at)
    except ValueError:
        return False
    return dt.weekday() >= 5


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


def derive_is_holiday(
    *,
    occurred_at: str | None,
    hr_status: str | None,
    hr_status_raw: str | None,
    is_holiday_input: bool | None,
) -> tuple[bool, str]:
    """
    BE 확정 우선순위:
    1) hrStatusRaw == OFF      -> true
    2) hrStatusRaw == VACATION -> false
    3) hrStatus(normalized)==WORK -> false
    4) 날짜(주말) fallback
    """
    raw = (hr_status_raw or "").strip().upper()
    if raw == _HR_RAW_OFF:
        return True, "hr_status_raw_off"
    if raw == _HR_RAW_VACATION:
        return False, "hr_status_raw_vacation"
    if hr_status == "WORK":
        return False, "hr_status_work"
    if is_holiday_input is not None:
        return bool(is_holiday_input), "input_is_holiday"
    return is_weekend(occurred_at), "weekend_fallback"


def evaluate_policy_gate(
    case_data: dict[str, Any] | None,
    *,
    has_rag_evidence: bool,
) -> dict[str, Any]:
    case_data = case_data or {}
    signals: list[str] = []

    hr_status_raw_input = case_data.get("hrStatusRaw") or case_data.get("hr_status_raw")
    hr_status, hr_raw_norm = normalize_hr_status(case_data.get("hrStatus") or case_data.get("hr_status"))
    hr_raw = str(hr_status_raw_input).strip() if hr_status_raw_input is not None else hr_raw_norm
    mcc_code, mcc_raw = normalize_mcc_code(case_data.get("mccCode") or case_data.get("mcc_code"))
    occurred_at = normalize_occurred_at(case_data.get("occurredAt") or case_data.get("occurred_at"))
    budget_exceeded = case_data.get("budgetExceeded") or case_data.get("budget_exceeded")
    is_holiday_input = _to_bool(case_data.get("isHoliday") or case_data.get("is_holiday"))
    case_type = str(case_data.get("case_type") or case_data.get("caseType") or "").strip().upper() or None

    is_holiday, is_holiday_source = derive_is_holiday(
        occurred_at=occurred_at,
        hr_status=hr_status,
        hr_status_raw=hr_raw,
        is_holiday_input=is_holiday_input,
    )
    if is_holiday:
        signals.append("holiday_usage")
    if hr_status == "LEAVE":
        signals.append("leave_status")
        if (hr_raw or "").upper() == _HR_RAW_VACATION:
            signals.append("vacation_status")
        elif (hr_raw or "").upper() == _HR_RAW_OFF:
            signals.append("off_status")
        else:
            signals.append("leave_general")
    elif hr_status == "WORK":
        signals.append("work_status")
    if str(budget_exceeded).strip().upper() in {"Y", "TRUE", "1"}:
        signals.append("budget_exceeded")

    recommended_case_type = case_type
    if not recommended_case_type:
        if "budget_exceeded" in signals:
            recommended_case_type = "LIMIT_EXCEED"
        elif "holiday_usage" in signals and "leave_status" in signals:
            recommended_case_type = "HOLIDAY_USAGE"
        else:
            recommended_case_type = "UNUSUAL_PATTERN"

    return {
        "signals": signals,
        "recommended_case_type": recommended_case_type,
        "allow_strong_conclusion": bool(has_rag_evidence),
        "needs_manual_review": not bool(has_rag_evidence),
        "normalized": {
            "hrStatus": hr_status,
            "hrStatusRaw": hr_raw,
            "mccCode": mcc_code,
            "mccCodeRaw": mcc_raw,
            "occurredAt": occurred_at,
            "isHoliday": is_holiday,
            "isHolidaySource": is_holiday_source,
        },
    }
