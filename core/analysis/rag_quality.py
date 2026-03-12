"""
RAG 품질 보강 유틸

- 룰 기반 제약(요청 payload 기반 조항 힌트) + 벡터 검색 하이브리드
- 조항 중심 리랭킹
- 외부 검색 텍스트 오염/인젝션 필터
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_PROMPT_INJECTION_PATTERNS = (
    "ignore previous",
    "ignore all previous",
    "system prompt",
    "developer message",
    "act as",
    "jailbreak",
    "do not follow",
    "prompt injection",
)

_ARTICLE_PATTERN = re.compile(r"(제\s*\d+\s*조(?:\s*제\s*\d+\s*항)?)")
_NOISE_TERM_PATTERN = re.compile(r"^[A-Za-z0-9\s/\-_.()]{1,40}$")
_NOISE_TERMS = {
    "sa",
    "g/l account document",
    "gl account document",
    "document",
    "account document",
    "expense",
}

_EXPENSE_TYPE_CODE_MAP = {
    "SA": "식대",
    "KR": "업무경비",
    "TR": "교통비",
    "EN": "접대비",
    "OT": "기타비용",
}


def _is_meaningful_query_term(term: str) -> bool:
    t = (term or "").strip()
    if not t:
        return False
    low = t.lower()
    if low in _NOISE_TERMS:
        return False
    # 영문/코드성 일반 용어만으로 구성된 짧은 토큰은 제외
    if _NOISE_TERM_PATTERN.fullmatch(t) and len(t) <= 20 and " " not in t and "/" not in t:
        return False
    return True


def _extract_expense_terms(case_data: dict[str, Any] | None) -> list[str]:
    if not isinstance(case_data, dict):
        return []
    code = str(case_data.get("expenseType") or case_data.get("expense_type") or "").strip().upper()
    name = str(case_data.get("expenseTypeName") or case_data.get("expense_type_name") or "").strip()
    terms: list[str] = []
    if not name and code:
        mapped = _EXPENSE_TYPE_CODE_MAP.get(code)
        if mapped:
            name = mapped
            logger.info("rag_quality: expense_type mapped code=%s name=%s", code, mapped)
        else:
            logger.info("rag_quality: expense_type map miss code=%s", code)
    if name and _is_meaningful_query_term(name):
        terms.append(name)
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        key = t.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _extract_semantic_terms(
    case_data: dict[str, Any] | None,
    *,
    intended_risk_type: str | None = None,
) -> list[str]:
    if not isinstance(case_data, dict):
        return []
    terms: list[str] = []
    is_holiday = case_data.get("isHoliday") or case_data.get("is_holiday")
    hr_status = str(case_data.get("hrStatus") or case_data.get("hr_status") or "").strip().upper()
    mcc_name = str(case_data.get("mccName") or case_data.get("mcc_name") or "").strip()
    budget_exceeded = case_data.get("budgetExceeded") or case_data.get("budget_exceeded")
    if is_holiday is True:
        terms.extend(["휴일", "주말", "공휴일"])
    if hr_status == "LEAVE":
        terms.extend(["휴무", "휴가", "업무연관성"])
    if budget_exceeded is True or str(budget_exceeded).strip().upper() in {"Y", "TRUE", "1"}:
        terms.extend(["한도", "예산초과"])
    if mcc_name and _is_meaningful_query_term(mcc_name):
        terms.append(mcc_name)
    # 의도 위험유형 코드는 직접 넣지 않고 의미어로만 보강
    risk = str(intended_risk_type or "").strip().upper()
    if "HOLIDAY" in risk:
        terms.extend(["휴일", "주말", "심야"])
    elif "LIMIT" in risk:
        terms.extend(["한도", "초과"])
    elif "PRIVATE" in risk:
        terms.extend(["사적사용", "업무무관"])
    elif "SPLIT" in risk:
        terms.extend(["분할결제", "반복결제"])
    elif "DUPLICATE" in risk:
        terms.extend(["중복", "결제"])
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        k = t.strip()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def _extract_related_articles(case_data: dict[str, Any] | None) -> list[str]:
    if not isinstance(case_data, dict):
        return []
    raw = (
        case_data.get("mcc_related_article")
        or case_data.get("mccRelatedArticle")
        or (
            case_data.get("evidence", {}).get("mcc_related_article")
            if isinstance(case_data.get("evidence"), dict)
            else None
        )
    )
    if raw is None:
        return []
    text = str(raw).strip()
    if not text:
        return []
    found = _ARTICLE_PATTERN.findall(text)
    if not found:
        return []
    normalized = [re.sub(r"\s+", "", f) for f in found]
    seen: set[str] = set()
    out: list[str] = []
    for a in normalized:
        if a and a not in seen:
            seen.add(a)
            out.append(a)
    return out


def build_dynamic_rag_query(
    case_data: dict[str, Any] | None,
    *,
    intended_risk_type: str | None = None,
) -> str:
    tokens: list[str] = ["법인카드", "전표", "규정", "감사", "준수"]
    if not isinstance(case_data, dict):
        return " ".join(tokens)
    expense_type = case_data.get("expenseType") or case_data.get("expense_type")
    merchant = case_data.get("merchantName") or case_data.get("merchant_name")
    occurred = case_data.get("occurredAt") or case_data.get("occurred_at")
    amount = case_data.get("amount") or case_data.get("totalAmount")
    hr_status = case_data.get("hrStatus") or case_data.get("hr_status")
    mcc_code = case_data.get("mccCode") or case_data.get("mcc_code")
    budget_exceeded = case_data.get("budgetExceeded") or case_data.get("budget_exceeded")
    if expense_type and _is_meaningful_query_term(str(expense_type)):
        tokens.append(str(expense_type))
    tokens.extend(_extract_expense_terms(case_data))
    if merchant:
        merchant_norm = str(merchant).strip()
        # 노이즈 토큰(슬래시/제어문자/특수기호 다수)을 포함하면 쿼리에서 제외
        if re.fullmatch(r"[0-9A-Za-z가-힣\s\-\(\)&\.]{2,30}", merchant_norm):
            tokens.append(merchant_norm)
    if occurred:
        tokens.extend(["발생일", str(occurred)[:10]])
    tokens.extend(_extract_semantic_terms(case_data, intended_risk_type=intended_risk_type))
    if amount is not None:
        tokens.extend(["금액", str(amount)])
    if hr_status:
        tokens.extend(["근태", str(hr_status)])
    if mcc_code:
        tokens.extend(["MCC", str(mcc_code)])
    if budget_exceeded is not None:
        tokens.extend(["예산초과", str(budget_exceeded)])
    seen: set[str] = set()
    deduped: list[str] = []
    for t in tokens:
        key = t.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return " ".join(deduped)


def _extract_mcc_code(case_data: dict[str, Any] | None) -> str | None:
    if not isinstance(case_data, dict):
        return None
    raw = case_data.get("mccCode") or case_data.get("mcc_code")
    if raw is None and isinstance(case_data.get("evidence"), dict):
        raw = case_data["evidence"].get("mccCode") or case_data["evidence"].get("mcc_code")
    if raw is None:
        return None
    code = str(raw).strip()
    return code or None


def _extract_case_occurred_date(case_data: dict[str, Any] | None) -> str | None:
    if not isinstance(case_data, dict):
        return None
    raw = case_data.get("occurredAt") or case_data.get("occurred_at")
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    return s[:10]


def build_rule_first_constraints(
    case_data: dict[str, Any] | None,
    *,
    settings_obj: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {"articles": [], "index_version": None}
    mcc_code = _extract_mcc_code(case_data)
    if mcc_code:
        out["mcc_code"] = mcc_code
    # 운영 정책: payload의 mcc_related_article은 품질 이슈로 현재 검색 제약에 사용하지 않음.
    related_articles: list[str] = []
    idx_ver = getattr(settings_obj, "rag_index_version", None)
    if idx_ver:
        out["index_version"] = str(idx_ver).strip()
    logger.info(
        "rag_quality: article_constraints source=disabled mcc=%s articles=%s related_article_hint_ignored=%s",
        mcc_code,
        out.get("articles") or [],
        _extract_related_articles(case_data),
    )
    return out


def apply_rule_first_filter(
    results: list[dict[str, Any]],
    *,
    preferred_articles: list[str] | None = None,
    effective_date: str | None = None,
) -> list[dict[str, Any]]:
    if not results:
        return []
    out = list(results)
    if effective_date:
        eff = []
        for r in out:
            meta = r.get("metadata_json") if isinstance(r.get("metadata_json"), dict) else {}
            if not meta:
                eff.append(r)
                continue
            eff_from = str(meta.get("effective_from") or meta.get("effectiveDateFrom") or "").strip()
            eff_to = str(meta.get("effective_to") or meta.get("effectiveDateTo") or "").strip()
            if eff_from and effective_date < eff_from:
                continue
            if eff_to and effective_date > eff_to:
                continue
            eff.append(r)
        out = eff
    articles = [str(a).replace(" ", "") for a in (preferred_articles or []) if str(a).strip()]
    if not articles:
        return out
    filtered: list[dict[str, Any]] = []
    for r in out:
        article = str(r.get("regulation_article") or r.get("regulationArticle") or "").replace(" ", "")
        location = str(r.get("location") or "").replace(" ", "")
        if any(a and (a == article or a in location) for a in articles):
            filtered.append(r)
    return filtered if filtered else out


def sanitize_external_reference_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    lines: list[str] = []
    for line in text.splitlines():
        low = line.lower()
        if any(p in low for p in _PROMPT_INJECTION_PATTERNS):
            continue
        if re.search(r"`{3,}|<script|</script>", low):
            continue
        lines.append(line)
    out = "\n".join(lines).strip()
    if len(out) > 3500:
        out = out[:3500]
    return out


def rerank_vector_results(
    results: list[dict[str, Any]],
    *,
    case_data: dict[str, Any] | None = None,
    preferred_articles: list[str] | None = None,
) -> list[dict[str, Any]]:
    if not results:
        return []
    expense = ""
    hr_status = ""
    is_holiday = False
    budget_exceeded = False
    risk_type = ""
    if isinstance(case_data, dict):
        expense = str(case_data.get("expenseType") or case_data.get("expense_type") or "").strip().lower()
        hr_status = str(case_data.get("hrStatus") or case_data.get("hr_status") or "").strip().upper()
        is_holiday = bool(case_data.get("isHoliday") is True or case_data.get("is_holiday") is True)
        budget_exceeded = bool(
            case_data.get("budgetExceeded") is True
            or str(case_data.get("budget_exceeded") or "").strip().upper() in {"Y", "TRUE", "1"}
        )
        risk_type = str(
            case_data.get("case_type")
            or case_data.get("caseType")
            or case_data.get("intended_risk_type")
            or ""
        ).strip().upper()
    preferred_set = {str(a).replace(" ", "") for a in (preferred_articles or []) if str(a).strip()}

    def _rank(d: dict[str, Any]) -> tuple[float, float, float]:
        score = float(d.get("score", 0) or 0)
        has_rule = 1.0 if (d.get("location") or d.get("regulation_article") or d.get("regulationArticle")) else 0.0
        article = str(d.get("regulation_article") or d.get("regulationArticle") or "").replace(" ", "")
        location = str(d.get("location") or "").replace(" ", "")
        rule_link_bonus = 1.0 if (preferred_set and any(a and (a == article or a in location) for a in preferred_set)) else 0.0
        text = (
            str(d.get("title") or "")
            + " "
            + str(d.get("location") or "")
            + " "
            + str(d.get("excerpt") or d.get("content") or "")
        ).lower()
        meta_penalty_keywords = (
            "ai 에이전트의 역할",
            "판정 근거 및 로그",
            "문서 개요",
            "제1장 문서 개요",
        )
        semantic_bonus = 1.0 if (expense and expense in text) else 0.0
        policy_bonus = 0.0
        risk_bonus = 0.0
        penalty = 0.0
        if any(k in text for k in meta_penalty_keywords):
            penalty += 1.2
        if is_holiday and any(t in text for t in ("휴일", "주말", "공휴일", "휴무")):
            policy_bonus += 0.8
        if is_holiday and any(t in text for t in ("심야", "야간", "시간대")):
            policy_bonus += 0.4
        if hr_status == "LEAVE" and any(t in text for t in ("휴가", "휴무", "근태")):
            policy_bonus += 0.4
        if budget_exceeded and any(t in text for t in ("한도", "초과", "예산")):
            policy_bonus += 0.6
        if risk_type == "HOLIDAY_USAGE":
            if any(t in text for t in ("휴일", "주말", "공휴일", "휴무", "휴가", "심야", "야간", "시간대")):
                risk_bonus += 1.0
            if any(t in text for t in ("식대", "업무상 식대")):
                risk_bonus += 0.3
            # 경과조치 단독 조항은 휴일 위험유형과 정합도가 낮음
            if "경과조치" in text and not any(t in text for t in ("휴일", "주말", "공휴일", "심야", "야간")):
                penalty += 0.9
        weighted = (
            (score * 0.35)
            + (has_rule * 0.2)
            + (semantic_bonus * 0.1)
            + (rule_link_bonus * 0.1)
            + (policy_bonus * 0.15)
            + (risk_bonus * 0.2)
            - penalty
        )
        return (weighted, has_rule, score)

    return sorted(results, key=_rank, reverse=True)
