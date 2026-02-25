"""
Pre-Analysis Screening — 전표 첫인상 분류

정밀 분석(Analysis Run) 전, 전표를 찰나에 스캔하여 caseType·severity·reasonText·score를 산출합니다.
v1.1: DRIVER_TYPE 6종, score 0-100, 배치(screen-batch) 지원. reasonText 마크다운·SPLIT_PAYMENT 구체 문구.
"""

import json
import logging
import re
from typing import Any

from core.llm import get_llm_client
from core.llm.prompts import get_screening_prompt

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

SCREENING_SYSTEM_DEFAULT = """[Role]
당신은 대량의 전표에서 부정 징후를 초고속으로 잡아내는 수석 감사 스캐너입니다.

[Output — JSON만 출력. score는 정수 0~100]
{ "caseType": "아래 6종 중 하나", "severity": "LOW|MEDIUM|HIGH", "score": 0~100, "reasonText": "한국어 한 문장" }

[caseType — 반드시 6종만]
HOLIDAY_USAGE, DUPLICATE_SUSPECT, SPLIT_PAYMENT, PRIVATE_USE_RISK, LIMIT_EXCEED, UNUSUAL_PATTERN

[판단] [금액+시각+업종] 결합. 동일 가맹점·짧은 시간·유사 금액 반복 시 SPLIT_PAYMENT·고득점.

[reasonText] 전문 감사관 톤. 핵심 수치·키워드는 **굵게**. SPLIT_PAYMENT일 때는 "동일 가맹점에서 10분 내 N회 결제된 내역이 포착되어 한도 우회로 의심됩니다" 형태로 구체적 근거 포함."""


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
    if occurred:
        parts.append(f"발생 시각: {occurred}")
    expense = voucher.get("expenseType") or voucher.get("expense_type") or ev.get("expenseType") or ev.get("expense_type")
    if expense:
        parts.append(f"경비 유형: {expense}")
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
    budget_exceeded = voucher.get("budgetExceeded") or voucher.get("budget_exceeded") or ev.get("budgetExceeded") or ev.get("budget_exceeded")
    if budget_exceeded is not None and str(budget_exceeded).strip().upper() in ("Y", "N", "TRUE", "FALSE"):
        parts.append(f"budgetExceeded: {str(budget_exceeded).strip().upper()}")
    risk = voucher.get("riskTypeKey") or voucher.get("risk_type") or ev.get("riskTypeKey") or ev.get("risk_type")
    if risk:
        parts.append(f"백엔드 위험 유형: {risk}")
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


def _default_screening_result(case_id: str = "", reason: str = "") -> dict[str, Any]:
    """배치 응답 길이 불일치 또는 개별 파싱 실패 시 사용. 인덱스 1:1 유지용."""
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
    severity_raw = _str(out.get("severity"), "MEDIUM").upper()
    severity = severity_raw if severity_raw in ("LOW", "MEDIUM", "HIGH") else "MEDIUM"
    reason_text = _str(out.get("reasonText")) or "전표 스캔 완료. 정밀 분석을 권장합니다."
    try:
        s = out.get("score", 50)
        score = int(s) if isinstance(s, (int, float)) and 0 <= float(s) <= 100 else float(s) * 100 if isinstance(s, (int, float)) and 0 <= float(s) <= 1 else 50
    except (TypeError, ValueError):
        score = 50
    score = max(0, min(100, int(round(score))))
    reasoning_process = _str(out.get("reasoningProcess"), "")
    result: dict[str, Any] = {"caseType": case_type, "severity": severity, "reasonText": reason_text, "score": score}
    if reasoning_process:
        result["reasoningProcess"] = reasoning_process
    if case_id:
        result["caseId"] = case_id
    logger.info(
        "Screening result: caseId=%s caseType=%s severity=%s score=%s reasonText=%s",
        case_id or "(n/a)",
        case_type,
        severity,
        score,
        (reason_text[:80] + "..." if len(reason_text) > 80 else reason_text),
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
    logger.info(
        "Screening input (단건): case_id=%s has_occurredAt=%s has_hrStatus=%s voucher_keys=%s context_preview=%s",
        case_id or "(n/a)",
        has_occurred,
        has_hr_status,
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

    return _normalize_single_result(out, case_id)


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
    logger.info(
        "Screening batch context summary: vouchers_with_occurredAt=%d vouchers_with_hrStatus=%d (of n=%d)",
        ctx_has_occurred,
        ctx_has_hr,
        len(vouchers),
    )
    user_prompt = f"""[전표 {len(vouchers)}건 — 순서 유지 필수]
{numbered}

위 전표들을 순서대로 스캔하십시오. 동일 가맹점·짧은 시간(10분 내)·유사 금액 반복이 있으면 해당 건은 SPLIT_PAYMENT로 분류하고 score를 높게 부여하십시오. SPLIT_PAYMENT의 reasonText에는 "동일 가맹점에서 10분 내 N회 결제된 내역이 포착되어 한도 우회로 의심됩니다"처럼 구체적 근거를 넣으십시오. 핵심 수치·키워드는 **굵게** 처리하십시오.
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
        _default_screening_result(case_ids[i] if i < len(case_ids) else "", reason="array_length_mismatch_or_no_llm")
        for i in range(n)
    ]
    if arr:
        for i in range(min(len(arr), n)):
            try:
                raw_out = arr[i]
                out = raw_out if isinstance(raw_out, dict) else {}
                result[i] = _normalize_single_result(out, case_ids[i] if i < len(case_ids) else "")
            except Exception as e:
                logger.debug("Batch item %d normalize failed: %s", i, e)
                result[i] = _default_screening_result(case_ids[i] if i < len(case_ids) else "", reason=f"normalize_exception_{e!r}")

    if len(arr) != n:
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
    severity = (priority_result.get("severity") or "MEDIUM").strip()
    score = int(priority_result.get("score", 50) or 50)
    ctx = _voucher_to_context(voucher)
    try:
        llm = get_llm_client()
        prompt = f"""[스크리닝 결과 1건 — 브리핑용 한 문장 요약]
caseType: {case_type}
severity: {severity}
score: {score}
전표: {ctx}

위 케이스를 감사 담당자가 즉시 이해할 수 있도록, **한 문장**으로만 브리핑 인사이트를 작성하십시오. 금액·시각·가맹점 등 핵심 수치는 유지하고, "분석 완료" 같은 단답은 금지합니다."""
        resp = await llm.ainvoke(prompt)
        out = (resp or "").strip()
        if out and len(out) > 10:
            return out[:500]
    except Exception as e:
        logger.debug("Briefing insight LLM failed: %s", e)
    return f"[{case_type}] score {score}. 정밀 분석을 권장합니다."
