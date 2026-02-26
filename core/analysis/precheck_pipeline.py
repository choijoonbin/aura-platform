"""
Pre-Analysis Screening — 전표 첫인상 분류

정밀 분석(Analysis Run) 전, 전표를 찰나에 스캔하여 caseType·severity·reasonText·score를 산출합니다.
v1.1: DRIVER_TYPE 6종, score 0-100, 배치(screen-batch) 지원. reasonText 마크다운·SPLIT_PAYMENT 구체 문구.
"""

import json
import logging
import re
from datetime import datetime
from typing import Any

from core.llm import get_llm_client
from core.llm.prompts import get_screening_prompt
from core.analysis.policy_engine import normalize_occurred_at

logger = logging.getLogger(__name__)

# DRIVER_TYPE 6종 (BE 코드 테이블 동기화). 그 외 값은 UNUSUAL_PATTERN으로 정규화.
# DEFAULT는 사용하지 않음. 미판별/실패 시 UNUSUAL_PATTERN.
# 판단 기준: 프롬프트에서 [금액+시각+가맹점 업종] 결합 분석, LLM이 6종 중 하나 반환.
ALLOWED_CASE_TYPES = frozenset({
    "HOLIDAY_USAGE",
    "DUPLICATE_SUSPECT",
    "SPLIT_PAYMENT",
    "PRIVATE_USE_RISK",
    "LIMIT_EXCEED",
    "UNUSUAL_PATTERN",
})

CASE_TYPE_DISPLAY_NAME: dict[str, str] = {
    "HOLIDAY_USAGE": "휴일 사용 의심",
    "DUPLICATE_SUSPECT": "중복 결제 의심",
    "SPLIT_PAYMENT": "분할 결제 의심",
    "PRIVATE_USE_RISK": "사적 사용 위험",
    "LIMIT_EXCEED": "한도 초과 의심",
    "UNUSUAL_PATTERN": "이상 패턴",
}

_ALLOWED_SEVERITIES = {"LOW", "MEDIUM", "HIGH"}
_MCC_RISK_POINTS = {"LOW": 5, "MEDIUM": 15, "HIGH": 25, "UNKNOWN": 8}
_FALLBACK_REASONS = {
    "NO_EVIDENCE": "핵심 입력값이 일부 누락되어 보수적으로 분류했습니다.",
    "INPUT_PARTIAL": "핵심 입력값 일부 누락(INPUT_PARTIAL)으로 점수를 보수적으로 조정했습니다.",
}


def _replace_case_type_codes(text: str) -> str:
    if not text:
        return text
    out = text
    for code, name in CASE_TYPE_DISPLAY_NAME.items():
        out = out.replace(code, name)
    return out


def _case_type_name(code: str | None) -> str:
    key = (code or "").strip().upper()
    return CASE_TYPE_DISPLAY_NAME.get(key, key or "미분류")


def _extract(voucher: dict[str, Any], *keys: str) -> Any:
    ev = voucher.get("evidence") if isinstance(voucher.get("evidence"), dict) else {}
    for k in keys:
        if voucher.get(k) is not None:
            return voucher.get(k)
        if ev.get(k) is not None:
            return ev.get(k)
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


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _derive_runtime_enrichment(voucher: dict[str, Any]) -> dict[str, Any]:
    occurred = normalize_occurred_at(_extract(voucher, "occurredAt", "occurred_at"))
    dt = _parse_dt(occurred)
    amount_raw = _extract(voucher, "amount", "totalAmount")
    try:
        amount = float(amount_raw) if amount_raw is not None else None
    except (TypeError, ValueError):
        amount = None
    hour = dt.hour if dt else None
    if amount is None:
        amount_band = "UNKNOWN"
    elif amount >= 1_000_000:
        amount_band = "XL"
    elif amount >= 300_000:
        amount_band = "L"
    elif amount >= 100_000:
        amount_band = "M"
    else:
        amount_band = "S"
    missing_fields = []
    for k in ("occurredAt", "amount", "hrStatus", "mccCode"):
        val = _extract(voucher, k, k.lower())
        if val in (None, ""):
            missing_fields.append(k)
    return {
        "weekday": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"][dt.weekday()] if dt else None,
        "hour": hour,
        "is_night_time": bool(hour is not None and (hour >= 22 or hour < 6)),
        "is_weekend": bool(dt.weekday() >= 5) if dt else False,
        "amount_band": amount_band,
        "input_partial": bool(missing_fields),
        "missing_fields": missing_fields,
    }


def _derive_deterministic_signals(voucher: dict[str, Any], case_type: str) -> dict[str, Any]:
    occurred = normalize_occurred_at(_extract(voucher, "occurredAt", "occurred_at"))
    dt = _parse_dt(occurred)
    hr_status = str(_extract(voucher, "hrStatus", "hr_status") or "").strip().upper()
    hr_status_raw = str(_extract(voucher, "hrStatusRaw", "hr_status_raw") or "").strip().upper()
    mcc_code = str(_extract(voucher, "mccCode", "mcc_code") or "").strip()
    mcc_name = str(_extract(voucher, "mccName", "mcc_name") or "").strip()
    mcc_risk = str(_extract(voucher, "mccRiskCategory", "mcc_risk_category") or "UNKNOWN").strip().upper() or "UNKNOWN"
    budget_exceeded = _to_bool(_extract(voucher, "budgetExceeded", "budget_exceeded"))
    budget_flag = str(_extract(voucher, "budgetExceededFlag", "budget_exceeded_flag") or "").strip().upper()
    is_weekend_allowed = str(_extract(voucher, "isWeekendAllowed", "is_weekend_allowed") or "").strip().upper()
    holiday_type = str(_extract(voucher, "holidayType", "holiday_type") or "").strip().upper()
    is_holiday = _to_bool(_extract(voucher, "isHoliday", "is_holiday"))
    if is_holiday is None:
        is_holiday = holiday_type in {"WEEKEND", "PUBLIC_HOLIDAY"} if holiday_type else False
        if dt and dt.weekday() >= 5 and holiday_type in {"", "NONE"}:
            is_holiday = True
    amount_raw = _extract(voucher, "amount", "totalAmount")
    try:
        amount = float(amount_raw) if amount_raw is not None else None
    except (TypeError, ValueError):
        amount = None
    points = 0
    breakdown: list[dict[str, Any]] = []
    decision_codes: list[str] = []
    evidence_map: dict[str, Any] = {
        "occurredAt": occurred,
        "weekday": None,
        "holidayType": holiday_type or None,
        "isHoliday": bool(is_holiday),
        "hrStatus": hr_status or None,
        "hrStatusRaw": hr_status_raw or None,
        "mccCode": mcc_code or None,
        "mccName": mcc_name or None,
        "mccRiskCategory": mcc_risk,
        "budgetExceeded": budget_exceeded if budget_exceeded is not None else (budget_flag == "Y"),
        "budgetExceededFlag": budget_flag or None,
        "isWeekendAllowed": is_weekend_allowed or None,
        "amount": amount,
    }
    if dt:
        weekday_ko = ["월", "화", "수", "목", "금", "토", "일"][dt.weekday()]
        evidence_map["weekday"] = weekday_ko
    missing_required = []
    for k, val in (
        ("occurredAt", occurred),
        ("amount", amount),
        ("hrStatus", hr_status),
        ("mccCode", mcc_code),
    ):
        if val in (None, ""):
            missing_required.append(k)
    if missing_required:
        decision_codes.append("INPUT_PARTIAL")
        breakdown.append({"code": "INPUT_PARTIAL", "points": 0, "evidence": ",".join(missing_required)})
    mcc_points = _MCC_RISK_POINTS.get(mcc_risk, _MCC_RISK_POINTS["UNKNOWN"])
    points += mcc_points
    breakdown.append({"code": "MCC_RISK", "points": mcc_points, "evidence": mcc_risk})
    if is_holiday and hr_status == "LEAVE":
        points += 30
        decision_codes.append("HOLIDAY_LEAVE")
        breakdown.append({"code": "HOLIDAY_LEAVE", "points": 30, "evidence": f"isHoliday={is_holiday},hrStatus={hr_status}"})
    if is_holiday and is_weekend_allowed == "N":
        points += 15
        decision_codes.append("WEEKEND_NOT_ALLOWED")
        breakdown.append({"code": "WEEKEND_NOT_ALLOWED", "points": 15, "evidence": f"isHoliday={is_holiday},isWeekendAllowed={is_weekend_allowed}"})
    if budget_exceeded is True or budget_flag == "Y":
        points += 15
        decision_codes.append("BUDGET_EXCEEDED")
        breakdown.append({"code": "BUDGET_EXCEEDED", "points": 15, "evidence": f"budgetExceeded={budget_exceeded},flag={budget_flag}"})
    if dt and (dt.hour >= 22 or dt.hour < 6):
        points += 10
        decision_codes.append("NIGHT_TIME")
        breakdown.append({"code": "NIGHT_TIME", "points": 10, "evidence": f"hour={dt.hour}"})
    if amount is not None:
        if amount >= 1_000_000:
            points += 20
            decision_codes.append("HIGH_AMOUNT")
            breakdown.append({"code": "HIGH_AMOUNT", "points": 20, "evidence": f"amount={amount}"})
        elif amount >= 300_000:
            points += 12
            decision_codes.append("MID_HIGH_AMOUNT")
            breakdown.append({"code": "MID_HIGH_AMOUNT", "points": 12, "evidence": f"amount={amount}"})
        elif amount >= 100_000:
            points += 6
            decision_codes.append("MID_AMOUNT")
            breakdown.append({"code": "MID_AMOUNT", "points": 6, "evidence": f"amount={amount}"})
    if case_type == "HOLIDAY_USAGE":
        points += 8
        breakdown.append({"code": "CASE_TYPE_HOLIDAY_USAGE", "points": 8, "evidence": "llm_case_type"})
    elif case_type == "LIMIT_EXCEED":
        points += 8
        breakdown.append({"code": "CASE_TYPE_LIMIT_EXCEED", "points": 8, "evidence": "llm_case_type"})
    score = max(0, min(100, int(round(points))))
    if score >= 70:
        severity = "HIGH"
    elif score >= 40:
        severity = "MEDIUM"
    else:
        severity = "LOW"
    return {
        "score": score,
        "severity": severity,
        "score_breakdown": breakdown,
        "decision_codes": decision_codes or ["BASELINE"],
        "evidence_map": evidence_map,
    }


def _deterministic_reason(case_type: str, voucher: dict[str, Any], scoring: dict[str, Any]) -> str:
    em = scoring.get("evidence_map") if isinstance(scoring.get("evidence_map"), dict) else {}
    occurred = em.get("occurredAt") or normalize_occurred_at(_extract(voucher, "occurredAt", "occurred_at"))
    weekday = em.get("weekday")
    amount = em.get("amount")
    hr_status = em.get("hrStatus") or _extract(voucher, "hrStatus", "hr_status")
    mcc_name = em.get("mccName") or _extract(voucher, "mccName", "mcc_name")
    mcc_code = em.get("mccCode") or _extract(voucher, "mccCode", "mcc_code")
    budget_exceeded = em.get("budgetExceeded")
    pieces: list[str] = []
    if occurred:
        day_text = f"{occurred[:10]}" + (f"({weekday})" if weekday else "")
        pieces.append(f"발생일 **{day_text}**")
    if amount is not None:
        pieces.append(f"금액 **{int(amount):,}**")
    if hr_status:
        pieces.append(f"근태 **{hr_status}**")
    if mcc_code or mcc_name:
        pieces.append(f"업종 **{mcc_code or '-'} {mcc_name or ''}**".strip())
    if budget_exceeded is True:
        pieces.append("예산초과 **Y**")
    base = ", ".join(pieces) if pieces else "핵심 입력"
    case_name = _case_type_name(case_type)
    if case_type == "HOLIDAY_USAGE":
        return f"{base} 기준으로 **{case_name}** 신호가 확인되었습니다."
    if case_type == "LIMIT_EXCEED":
        return f"{base} 기준으로 **{case_name}** 가능성이 높습니다."
    if case_type == "PRIVATE_USE_RISK":
        return f"{base} 기준으로 **{case_name}** 징후가 관찰되었습니다."
    if case_type in {"DUPLICATE_SUSPECT", "SPLIT_PAYMENT"}:
        return f"{base} 기준으로 **{case_name}** 추가 확인이 필요합니다."
    return f"{base} 기준으로 **{case_name}** 패턴으로 분류했습니다."


def _align_case_type_with_signals(case_type: str, scoring: dict[str, Any]) -> tuple[str, str | None]:
    evidence_map = scoring.get("evidence_map") if isinstance(scoring.get("evidence_map"), dict) else {}
    decision_codes = set(scoring.get("decision_codes") or [])
    is_holiday = bool(evidence_map.get("isHoliday"))
    budget_exceeded = evidence_map.get("budgetExceeded") is True
    aligned = case_type
    reason = None
    if case_type == "HOLIDAY_USAGE" and not is_holiday:
        if budget_exceeded:
            aligned = "LIMIT_EXCEED"
            reason = "holiday_without_holiday_signal_to_limit_exceed"
        else:
            aligned = "UNUSUAL_PATTERN"
            reason = "holiday_without_holiday_signal_to_unusual"
    if case_type == "LIMIT_EXCEED" and not budget_exceeded and "HIGH_AMOUNT" not in decision_codes and "MID_HIGH_AMOUNT" not in decision_codes:
        aligned = "UNUSUAL_PATTERN"
        reason = "limit_without_budget_or_amount_signal_to_unusual"
    return aligned, reason


def _deterministic_holiday_reason(voucher: dict[str, Any]) -> str | None:
    occurred = (
        voucher.get("occurredAt")
        or voucher.get("occurred_at")
        or ((voucher.get("evidence") or {}).get("occurredAt") if isinstance(voucher.get("evidence"), dict) else None)
    )
    occurred = normalize_occurred_at(occurred)
    if not occurred:
        return None
    holiday_flag = _to_bool(_extract(voucher, "isHoliday", "is_holiday"))
    holiday_type = str(_extract(voucher, "holidayType", "holiday_type") or "").strip().upper()
    try:
        dt = datetime.fromisoformat(str(occurred))
    except ValueError:
        return None
    inferred_holiday = bool(holiday_flag) or holiday_type in {"WEEKEND", "PUBLIC_HOLIDAY"} or dt.weekday() >= 5
    if not inferred_holiday:
        return None
    weekday_ko = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"][dt.weekday()]
    hr_status = (
        voucher.get("hrStatus")
        or voucher.get("hr_status")
        or ((voucher.get("evidence") or {}).get("hrStatus") if isinstance(voucher.get("evidence"), dict) else None)
        or "UNKNOWN"
    )
    return f"{dt.date().isoformat()}는 {weekday_ko}이며, 근태 상태({hr_status})와 결합해 휴일 사용 위험으로 분류함."


def _apply_reasontext_policy(result: dict[str, Any], voucher: dict[str, Any]) -> dict[str, Any]:
    out = dict(result)
    scoring = out.get("score_breakdown") if isinstance(out.get("score_breakdown"), list) else []
    em = out.get("evidence_map") if isinstance(out.get("evidence_map"), dict) else {}
    case_type = str(out.get("caseType") or "").strip().upper()
    deterministic = _deterministic_reason(
        case_type,
        voucher,
        {"evidence_map": em, "score_breakdown": scoring},
    )
    original_reason = str(out.get("reasonText") or "").strip()
    if case_type == "HOLIDAY_USAGE":
        fixed = _deterministic_holiday_reason(voucher)
        if fixed:
            deterministic = fixed
    if original_reason and original_reason != deterministic:
        logger.info(
            "Screening reasonText normalized(caseType=%s): before=%s after=%s",
            case_type,
            (original_reason[:120] + "…") if len(original_reason) > 120 else original_reason,
            (deterministic[:120] + "…") if len(deterministic) > 120 else deterministic,
        )
    out["reasonText"] = _replace_case_type_codes(deterministic)
    return out

SCREENING_SYSTEM_DEFAULT = """[Role]
당신은 대량의 전표에서 부정 징후를 초고속으로 잡아내는 수석 감사 스캐너입니다.

[Output — JSON만 출력. score는 정수 0~100]
{
  "caseType": "아래 6종 중 하나",
  "severity": "LOW|MEDIUM|HIGH",
  "score": 0~100,
  "reasonText": "한국어 한 문장",
  "reasoningProcess": "판단 근거",
  "score_breakdown": [{"code":"...", "points": 0, "evidence":"..."}],
  "evidence_map": {"occurredAt":"...", "hrStatus":"...", "mccCode":"..."},
  "decision_codes": ["..."]
}

[caseType — 반드시 6종만]
HOLIDAY_USAGE, DUPLICATE_SUSPECT, SPLIT_PAYMENT, PRIVATE_USE_RISK, LIMIT_EXCEED, UNUSUAL_PATTERN

[판단] [금액+시각+업종] 결합. 제공된 증거 강도에 따라 가장 적합한 유형 1개만 선택.

[reasonText] 전문 감사관 톤. 핵심 수치·키워드는 **굵게**. 입력에 없는 패턴(예: 10분 내 N회)은 생성 금지."""


def _get_screening_system() -> str:
    """YAML 프롬프트 우선, 없으면 코드 기본값."""
    s = get_screening_prompt()
    return s if s else SCREENING_SYSTEM_DEFAULT


def _voucher_to_context(voucher: dict[str, Any]) -> str:
    """전표 데이터를 LLM에 넘길 문맥 문자열로 변환. evidence 내부 필드도 사용. v3.0: hrStatus, mccCode, mccName, budgetExceeded 포함."""
    ev = voucher.get("evidence") if isinstance(voucher.get("evidence"), dict) else {}
    parts: list[str] = []
    if voucher.get("amount") is not None or voucher.get("totalAmount") is not None:
        amt = voucher.get("amount") or voucher.get("totalAmount")
        parts.append(f"금액: {amt}")
    occurred = voucher.get("occurredAt") or voucher.get("occurred_at") or ev.get("occurredAt") or ev.get("occurred_at")
    occurred = normalize_occurred_at(occurred)
    if occurred:
        parts.append(f"발생 시각: {occurred}")
    expense = voucher.get("expenseType") or voucher.get("expense_type") or ev.get("expenseType") or ev.get("expense_type")
    if expense:
        parts.append(f"경비 유형: {expense}")
    expense_name = voucher.get("expenseTypeName") or voucher.get("expense_type_name") or ev.get("expenseTypeName") or ev.get("expense_type_name")
    if expense_name:
        parts.append(f"경비 유형명: {expense_name}")
    merchant = voucher.get("merchantName") or voucher.get("merchant_name") or ev.get("merchantName") or ev.get("merchant_name")
    if merchant:
        parts.append(f"가맹점: {merchant}")
    # v3.0: 근태·업종·예산 초과 (제9조·제34조·제5조 대조용)
    hr_status = voucher.get("hrStatus") or voucher.get("hr_status") or ev.get("hrStatus") or ev.get("hr_status")
    if hr_status:
        parts.append(f"hrStatus(근태): {hr_status}")
    mcc_code = voucher.get("mccCode") or voucher.get("mcc_code") or ev.get("mccCode") or ev.get("mcc_code")
    mcc_name = voucher.get("mccName") or voucher.get("mcc_name") or ev.get("mccName") or ev.get("merchant_name")
    if mcc_code or mcc_name:
        parts.append(f"mccCode/mccName(업종): {mcc_code or ''} {mcc_name or ''}".strip())
    mcc_risk = voucher.get("mccRiskCategory") or voucher.get("mcc_risk_category") or ev.get("mccRiskCategory") or ev.get("mcc_risk_category")
    if mcc_risk:
        parts.append(f"mccRiskCategory: {mcc_risk}")
    mcc_raw = voucher.get("mccCodeRaw") or voucher.get("mcc_code_raw") or ev.get("mccCodeRaw") or ev.get("mcc_code_raw")
    if mcc_raw:
        parts.append(f"mccCodeRaw: {mcc_raw}")
    budget_exceeded = voucher.get("budgetExceeded") or voucher.get("budget_exceeded") or ev.get("budgetExceeded") or ev.get("budget_exceeded")
    if budget_exceeded is not None and str(budget_exceeded).strip().upper() in ("Y", "N", "TRUE", "FALSE"):
        parts.append(f"budgetExceeded: {str(budget_exceeded).strip().upper()}")
    budget_flag = voucher.get("budgetExceededFlag") or voucher.get("budget_exceeded_flag") or ev.get("budgetExceededFlag") or ev.get("budget_exceeded_flag")
    if budget_flag:
        parts.append(f"budgetExceededFlag: {budget_flag}")
    holiday = voucher.get("isHoliday") or voucher.get("is_holiday") or ev.get("isHoliday") or ev.get("is_holiday")
    if holiday is not None:
        parts.append(f"isHoliday: {holiday}")
    holiday_type = voucher.get("holidayType") or voucher.get("holiday_type") or ev.get("holidayType") or ev.get("holiday_type")
    if holiday_type:
        parts.append(f"holidayType: {holiday_type}")
    weekend_allowed = voucher.get("isWeekendAllowed") or voucher.get("is_weekend_allowed") or ev.get("isWeekendAllowed") or ev.get("is_weekend_allowed")
    if weekend_allowed:
        parts.append(f"isWeekendAllowed: {weekend_allowed}")
    hr_raw = voucher.get("hrStatusRaw") or voucher.get("hr_status_raw") or ev.get("hrStatusRaw") or ev.get("hr_status_raw")
    if hr_raw:
        parts.append(f"hrStatusRaw: {hr_raw}")
    rel_hint = voucher.get("relatedArticleHint") or voucher.get("related_article_hint") or ev.get("relatedArticleHint") or ev.get("related_article_hint")
    if rel_hint:
        parts.append(f"relatedArticleHint(힌트): {rel_hint}")
    rel_hint_usage = voucher.get("relatedArticleHintUsage") or voucher.get("related_article_hint_usage") or ev.get("relatedArticleHintUsage") or ev.get("related_article_hint_usage")
    if rel_hint_usage:
        parts.append(f"relatedArticleHintUsage: {rel_hint_usage}")
    source_ts = voucher.get("sourceTimestamp") or voucher.get("source_timestamp")
    if source_ts:
        parts.append(f"sourceTimestamp(UTC): {source_ts}")
    schema_ver = voucher.get("schemaVersion") or voucher.get("schema_version")
    if schema_ver:
        parts.append(f"schemaVersion: {schema_ver}")
    normalization_flags = voucher.get("normalizationFlags") or voucher.get("normalization_flags")
    if isinstance(normalization_flags, dict) and normalization_flags:
        parts.append(f"normalizationFlags: {json.dumps(normalization_flags, ensure_ascii=False)}")
    data_quality = voucher.get("dataQuality") or voucher.get("data_quality")
    if isinstance(data_quality, dict):
        missing = data_quality.get("missingFields")
        if isinstance(missing, list):
            parts.append(f"dataQuality.missingFields: {missing}")
    runtime_enrichment = _derive_runtime_enrichment(voucher)
    parts.append(
        "runtime_enrichment: "
        + json.dumps(runtime_enrichment, ensure_ascii=False)
    )
    risk = voucher.get("case_type") or voucher.get("caseType") or ev.get("case_type") or ev.get("caseType")
    if risk:
        parts.append(f"백엔드 분류 유형(case_type): {risk}")
    keys = voucher.get("keys")
    if isinstance(keys, dict):
        if keys.get("belnr"):
            parts.append(f"전표번호: {keys.get('belnr')}")
        if keys.get("buzei"):
            parts.append(f"행: {keys.get('buzei')}")
    if not parts:
        parts.append("(제공된 전표 필드 없음)")
    return "\n".join(parts)


def _parse_screening_response(text: str) -> dict[str, Any]:
    """LLM 응답에서 JSON 블록 추출 후 파싱."""
    text = (text or "").strip()
    # ```json ... ``` 블록
    code_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if code_match:
        try:
            return json.loads(code_match.group(1))
        except json.JSONDecodeError:
            pass
    # 첫 번째 { 부터 짝 맞는 } 까지
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{") and "\"caseType\"" in line:
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {}


def _parse_screening_response_array(text: str, expected_len: int) -> list[dict[str, Any]]:
    """LLM 응답에서 JSON 배열 추출. 길이 불일치 시 빈 리스트."""
    text = (text or "").strip()
    # ```json [...] ``` 또는 [ ... ]
    code_match = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", text)
    if code_match:
        try:
            arr = json.loads(code_match.group(1))
            return arr if isinstance(arr, list) else []
        except json.JSONDecodeError:
            pass
    start = text.find("[")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    try:
                        arr = json.loads(text[start : i + 1])
                        return arr if isinstance(arr, list) else []
                    except json.JSONDecodeError:
                        break
    return []


def _default_screening_result(case_id: str = "", reason: str = "", *, emit_log: bool = True) -> dict[str, Any]:
    """배치 응답 길이 불일치 또는 개별 파싱 실패 시 사용. 인덱스 1:1 유지용."""
    if emit_log:
        logger.info(
            "Screening fallback to UNUSUAL_PATTERN: case_id=%s reason=%s (Aura는 DEFAULT를 반환하지 않음, BE에 UNUSUAL_PATTERN 전달됨)",
            case_id or "(n/a)",
            reason or "no_llm_result",
        )
    result: dict[str, Any] = {
        "caseType": "UNUSUAL_PATTERN",
        "severity": "MEDIUM",
        "score": 50,
        "reasonText": "스크리닝 결과를 생성하지 못했습니다. 정밀 분석을 권장합니다.",
    }
    if case_id:
        result["caseId"] = case_id
    return result


def _normalize_single_result(out: dict[str, Any], case_id: str = "") -> dict[str, Any]:
    """단일 LLM 출력을 BE 인서트 규격으로 정규화 (caseType 6종, score 0-100). LLM이 caseType/severity/reasonText를 숫자 등으로 줄 수 있으므로 str 강제."""
    def _str(v: Any, default: str = "") -> str:
        if v is None:
            return default
        return str(v).strip() if isinstance(v, str) else str(v).strip()

    raw_case_type = _str(out.get("caseType"), "UNUSUAL_PATTERN").upper().replace(" ", "_")
    case_type = raw_case_type if raw_case_type in ALLOWED_CASE_TYPES else "UNUSUAL_PATTERN"
    if raw_case_type != case_type:
        _rt = _str(out.get("reasonText"), "")
        reason_preview = _rt[:60] + ("..." if len(_rt) > 60 else "")
        logger.info(
            "Screening caseType normalized: llm_returned=%s -> caseType=%s (not in allowed 6) case_id=%s reasonText_preview=%s",
            raw_case_type,
            case_type,
            case_id or "(batch)",
            reason_preview,
        )
    # 엔터프라이즈 안정화: 점수/심각도는 결정론 계산을 우선 적용하여 재현성 보장
    llm_severity_raw = _str(out.get("severity"), "MEDIUM").upper()
    llm_severity = llm_severity_raw if llm_severity_raw in _ALLOWED_SEVERITIES else "MEDIUM"
    try:
        s = out.get("score", 50)
        llm_score = int(s) if isinstance(s, (int, float)) and 0 <= float(s) <= 100 else float(s) * 100 if isinstance(s, (int, float)) and 0 <= float(s) <= 1 else 50
    except (TypeError, ValueError):
        llm_score = 50
    llm_score = max(0, min(100, int(round(llm_score))))
    reasoning_process = _str(out.get("reasoningProcess"), "")
    result: dict[str, Any] = {
        "caseType": case_type,
        "severity": llm_severity,
        "reasonText": _replace_case_type_codes(_str(out.get("reasonText")) or "전표 스캔 완료. 정밀 분석을 권장합니다."),
        "score": llm_score,
    }
    score_breakdown = out.get("score_breakdown")
    if isinstance(score_breakdown, list):
        result["score_breakdown"] = score_breakdown
    evidence_map = out.get("evidence_map")
    if isinstance(evidence_map, dict):
        result["evidence_map"] = evidence_map
    decision_codes = out.get("decision_codes")
    if isinstance(decision_codes, list):
        result["decision_codes"] = [str(c) for c in decision_codes if str(c).strip()]
    if reasoning_process:
        result["reasoningProcess"] = reasoning_process
    if case_id:
        result["caseId"] = case_id
    logger.info(
        "Screening result(raw): caseId=%s caseType=%s severity=%s score=%s reasonText=%s",
        case_id or "(n/a)",
        case_type,
        llm_severity,
        llm_score,
        (str(result.get("reasonText") or "")[:80] + "..." if len(str(result.get('reasonText') or '')) > 80 else str(result.get("reasonText") or "")),
    )
    return result


async def run_screen(voucher: dict[str, Any], case_id: str = "") -> dict[str, Any]:
    """
    전표 스크리닝 실행. caseType, severity, reasonText, score 반환.

    Args:
        voucher: 전표 데이터 (amount, occurredAt, expenseType, keys 등). get_case 정규화 결과 또는 동일 구조.
        case_id: 케이스 ID (로깅/메타용).

    Returns:
        { "caseType", "severity", "reasonText", "score", "caseId"? }
    """
    context = _voucher_to_context(voucher)
    has_occurred = bool(voucher.get("occurredAt") or voucher.get("occurred_at") or (voucher.get("evidence") or {}).get("occurredAt"))
    has_hr_status = bool(voucher.get("hrStatus") or voucher.get("hr_status") or (voucher.get("evidence") or {}).get("hrStatus"))
    has_mcc = bool(voucher.get("mccCode") or voucher.get("mcc_code") or (voucher.get("evidence") or {}).get("mccCode"))
    logger.info(
        "Screening input (단건): case_id=%s has_occurredAt=%s has_hrStatus=%s has_mcc=%s mccCode=%s mccName=%s voucher_keys=%s context_preview=%s",
        case_id or "(n/a)",
        has_occurred,
        has_hr_status,
        has_mcc,
        voucher.get("mccCode") or voucher.get("mcc_code") or (voucher.get("evidence") or {}).get("mccCode"),
        voucher.get("mccName") or voucher.get("mcc_name") or (voucher.get("evidence") or {}).get("mccName"),
        list(voucher.keys()),
        context.replace("\n", " | ")[:250] + ("..." if len(context) > 250 else ""),
    )
    user_prompt = f"[전표 데이터]\n{context}\n\n위 전표를 스캔하여 caseType, severity, reasonText, score를 JSON으로만 출력하십시오."

    try:
        llm = get_llm_client()
        system = _get_screening_system()
        response = await llm.ainvoke(
            f"{system}\n\n---\n\n{user_prompt}"
        )
        raw = (response or "").strip()
        out = _parse_screening_response(raw)
        if not out:
            logger.warning(
                "Screening parse empty: case_id=%s raw_len=%d raw_preview=%s (fallback UNUSUAL_PATTERN)",
                case_id,
                len(raw),
                (raw[:200] + "..." if len(raw) > 200 else raw),
            )
        else:
            logger.info(
                "Screening LLM raw: case_id=%s raw_caseType=%s severity=%s score=%s",
                case_id or "(n/a)",
                out.get("caseType"),
                out.get("severity"),
                out.get("score"),
            )
    except Exception as e:
        logger.warning("Screening LLM failed case_id=%s: %s", case_id, e)
        out = {}

    normalized = _normalize_single_result(out, case_id)
    scoring = _derive_deterministic_signals(voucher, str(normalized.get("caseType") or "UNUSUAL_PATTERN"))
    aligned_case_type, align_reason = _align_case_type_with_signals(str(normalized.get("caseType") or "UNUSUAL_PATTERN"), scoring)
    if aligned_case_type != normalized.get("caseType"):
        logger.info(
            "Screening caseType aligned by deterministic signals: case_id=%s before=%s after=%s reason=%s",
            case_id or "(n/a)",
            normalized.get("caseType"),
            aligned_case_type,
            align_reason,
        )
        normalized["caseType"] = aligned_case_type
        scoring = _derive_deterministic_signals(voucher, aligned_case_type)
    normalized["score"] = int(scoring["score"])
    normalized["severity"] = str(scoring["severity"])
    normalized["score_breakdown"] = scoring["score_breakdown"]
    normalized["evidence_map"] = scoring["evidence_map"]
    normalized["decision_codes"] = scoring["decision_codes"]
    if "INPUT_PARTIAL" in scoring["decision_codes"]:
        normalized["reasoningProcess"] = (
            (str(normalized.get("reasoningProcess") or "").strip() + " " if normalized.get("reasoningProcess") else "")
            + _FALLBACK_REASONS["INPUT_PARTIAL"]
        ).strip()
    logger.info(
        "Screening deterministic score: case_id=%s score=%s severity=%s decision_codes=%s breakdown_count=%s",
        case_id or "(n/a)",
        normalized.get("score"),
        normalized.get("severity"),
        normalized.get("decision_codes"),
        len(normalized.get("score_breakdown") or []),
    )
    return _apply_reasontext_policy(normalized, voucher)


async def run_screen_batch(
    vouchers: list[dict[str, Any]],
    case_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    대량 전표 배치 스크리닝. 단일 LLM 호출로 N건 처리 후 BE 즉시 인서트 가능한 JSON 배열 반환.

    - vouchers: 전표 리스트 (각 항목은 _voucher_to_context 가능한 dict).
    - case_ids: 선택. 순서 대응 caseId 리스트 (길이 불일치 시 인덱스만 사용).
    - 반환: [ { caseType, severity, score, reasonText, caseId? }, ... ] **요청 vouchers와 동일 순서(1:1)**.
    """
    if not vouchers:
        return []
    case_ids = case_ids or []
    # 단일 LLM 호출: N건을 한 번에 넘기고 JSON 배열 요청
    contexts = [_voucher_to_context(v) for v in vouchers]
    numbered = "\n\n".join(f"[전표 {i+1}]\n{ctx}" for i, ctx in enumerate(contexts))

    logger.info(
        "Screening batch input: n=%d case_ids=%s (판단 기준: 금액+시각+업종, 6종 caseType)",
        len(vouchers),
        case_ids[:10] if len(case_ids) > 10 else case_ids,
    )
    # 로깅: 휴일/제9조 판단용 필드가 몇 건에 있는지 (case_type 추적용)
    ctx_has_occurred = sum(1 for v in vouchers if v.get("occurredAt") or v.get("occurred_at"))
    ctx_has_hr = sum(1 for v in vouchers if v.get("hrStatus") or v.get("hr_status"))
    ctx_has_mcc = sum(1 for v in vouchers if v.get("mccCode") or v.get("mcc_code"))
    ctx_has_budget = sum(1 for v in vouchers if v.get("budgetExceeded") is not None or v.get("budget_exceeded") is not None)
    logger.info(
        "Screening batch context summary: vouchers_with_occurredAt=%d vouchers_with_hrStatus=%d vouchers_with_mcc=%d vouchers_with_budgetExceeded=%d (of n=%d)",
        ctx_has_occurred,
        ctx_has_hr,
        ctx_has_mcc,
        ctx_has_budget,
        len(vouchers),
    )
    user_prompt = f"""[전표 {len(vouchers)}건 — 순서 유지 필수]
{numbered}

위 전표들을 순서대로 스캔하십시오. 각 전표마다 입력 증거를 벗어나지 않는 caseType 1개를 선택하십시오.
입력에 없는 패턴(예: 반복 결제 횟수, 과거 비교 수치, 10분 내 N회 등)을 임의 생성하지 마십시오.
핵심 수치·키워드는 **굵게** 처리하십시오.
출력: **반드시 위 순서와 동일한 JSON 배열 하나**만 출력. [ {{ "caseType", "severity", "score", "reasonText" }}, ... ] (score 정수 0~100)"""

    try:
        llm = get_llm_client()
        system = _get_screening_system()
        response = await llm.ainvoke(f"{system}\n\n---\n\n{user_prompt}")
        raw = (response or "").strip()
        arr = _parse_screening_response_array(raw, len(vouchers))
        if not arr and raw:
            logger.warning(
                "Screening batch parse failed or empty array: raw_len=%d raw_preview=%s (all items fallback UNUSUAL_PATTERN)",
                len(raw),
                (raw[:300] + "..." if len(raw) > 300 else raw),
            )
    except Exception as e:
        logger.warning("Screening batch LLM failed: %s", e)
        arr = []

    # 항상 요청 길이와 동일한 배열 반환(인덱스 1:1). 실패/누락 건만 기본값 유지.
    n = len(vouchers)
    result: list[dict[str, Any]] = [
        _default_screening_result(
            case_ids[i] if i < len(case_ids) else "",
            reason="array_length_mismatch_or_no_llm",
            emit_log=False,
        )
        for i in range(n)
    ]
    if arr:
        for i in range(min(len(arr), n)):
            try:
                raw_out = arr[i]
                out = raw_out if isinstance(raw_out, dict) else {}
                normalized = _normalize_single_result(out, case_ids[i] if i < len(case_ids) else "")
                scoring = _derive_deterministic_signals(vouchers[i] if i < len(vouchers) else {}, str(normalized.get("caseType") or "UNUSUAL_PATTERN"))
                aligned_case_type, align_reason = _align_case_type_with_signals(str(normalized.get("caseType") or "UNUSUAL_PATTERN"), scoring)
                if aligned_case_type != normalized.get("caseType"):
                    logger.info(
                        "Screening caseType aligned by deterministic signals(batch): case_id=%s before=%s after=%s reason=%s",
                        case_ids[i] if i < len(case_ids) else "(n/a)",
                        normalized.get("caseType"),
                        aligned_case_type,
                        align_reason,
                    )
                    normalized["caseType"] = aligned_case_type
                    scoring = _derive_deterministic_signals(vouchers[i] if i < len(vouchers) else {}, aligned_case_type)
                normalized["score"] = int(scoring["score"])
                normalized["severity"] = str(scoring["severity"])
                normalized["score_breakdown"] = scoring["score_breakdown"]
                normalized["evidence_map"] = scoring["evidence_map"]
                normalized["decision_codes"] = scoring["decision_codes"]
                result[i] = _apply_reasontext_policy(normalized, vouchers[i] if i < len(vouchers) else {})
            except Exception as e:
                logger.debug("Batch item %d normalize failed: %s", i, e)
                result[i] = _default_screening_result(
                    case_ids[i] if i < len(case_ids) else "",
                    reason=f"normalize_exception_{e!r}",
                    emit_log=True,
                )

    if len(arr) != n:
        for i in range(len(arr) if arr else 0, n):
            logger.info(
                "Screening fallback to UNUSUAL_PATTERN: case_id=%s reason=array_length_mismatch_or_no_llm",
                case_ids[i] if i < len(case_ids) else "(n/a)",
            )
        logger.info(
            "Batch response length mismatch (got %d, expected %d). Missing indices use UNUSUAL_PATTERN. reason=array_length_mismatch",
            len(arr) if arr else 0,
            n,
        )
    # BE index 기반 매핑: 반환 순서는 vouchers 순서와 1:1 동일 보장
    return result


def pick_briefing_priority(
    results: list[dict[str, Any]],
    case_ids: list[str],
) -> tuple[int | None, str | None]:
    """
    배치 결과에서 '가장 주목해야 할' 케이스 1건을 선정.
    - 규칙: score 최대 → 동점이면 severity HIGH > MEDIUM > LOW → 동점이면 첫 번째 인덱스.
    - Returns: (priority_index, priority_case_id) 또는 (None, None).
    """
    if not results:
        return (None, None)
    severity_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}

    def key(i: int) -> tuple[int, int]:
        r = results[i]
        score = int(r.get("score", 0) or 0)
        sev = (r.get("severity") or "MEDIUM").strip().upper()
        return (-score, -(severity_order.get(sev, 2)))

    best_i = min(range(len(results)), key=key)
    case_id = (case_ids[best_i] or "").strip() if best_i < len(case_ids) else (results[best_i].get("caseId") or "")
    return (best_i, case_id or None)


async def generate_briefing_insight(
    priority_result: dict[str, Any],
    voucher: dict[str, Any],
    case_id: str,
) -> str:
    """
    자동 포커싱된 케이스용 브리핑 인사이트 문장 1개 생성.
    '분석 완료' 같은 단답이 아닌, 전체 문맥을 관통하는 한 문장으로 반환.
    """
    reason = (priority_result.get("reasonText") or "").strip()
    if reason and reason not in (
        "전표 스캔 완료. 정밀 분석을 권장합니다.",
        "스크리닝 결과를 생성하지 못했습니다. 정밀 분석을 권장합니다.",
    ):
        return reason
    # reasonText가 기본 문구일 때만 LLM으로 한 문장 브리핑 생성
    case_type = (priority_result.get("caseType") or "UNUSUAL_PATTERN").strip()
    case_type_name = _case_type_name(case_type)
    severity = (priority_result.get("severity") or "MEDIUM").strip()
    score = int(priority_result.get("score", 50) or 50)
    ctx = _voucher_to_context(voucher)
    try:
        llm = get_llm_client()
        prompt = f"""[스크리닝 결과 1건 — 브리핑용 한 문장 요약]
caseType: {case_type_name}
severity: {severity}
score: {score}
전표: {ctx}

위 케이스를 감사 담당자가 즉시 이해할 수 있도록, **한 문장**으로만 브리핑 인사이트를 작성하십시오. 금액·시각·가맹점 등 핵심 수치는 유지하고, "분석 완료" 같은 단답은 금지합니다."""
        resp = await llm.ainvoke(prompt)
        out = (resp or "").strip()
        if out and len(out) > 10:
            return _replace_case_type_codes(out[:500])
    except Exception as e:
        logger.debug("Briefing insight LLM failed: %s", e)
    return f"[{case_type_name}] score {score}. 정밀 분석을 권장합니다."
