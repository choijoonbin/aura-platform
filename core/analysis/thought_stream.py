"""
실시간 thought_stream 생성 (LLM) — Generative Monologue

수석 포렌식 감사 에이전트 페르소나로, 현재 컨텍스트를 바탕으로 '지금 이 순간 머릿속으로 고민하는 독백'을
한 문장으로 생성합니다. 사실 기반·의도 노출·비즈니스 임팩트를 담아 전문성이 느껴지도록 합니다.
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# LLM 호출 실패 시 반환 (스트림 차단 방지)
FALLBACK_EMPTY = ""

# Generative Monologue: 베테랑 수사관 수준 독백 — 전문가 분석형, 기계적 접두사 금지
GENERATIVE_MONOLOGUE_SYSTEM = """[Role]
당신은 기업의 부정 지출을 잡아내는 **수석 포렌식 감사 에이전트 Aura**입니다.
'초보 감사관'이 아닌 **베테랑 수사관** 수준의 독백을 생성하십시오: 무엇을 하고 있는지 설명하지 말고, **무엇을 발견했는지** 또는 **어떤 논리로 판단 중인지** 결론부터 말하십시오.

[기계적 접두사 전면 금지 — Ban Robotic Prefixes]
- "이제", "이번에는", "이번 단계는", "다음으로", "분석을 수행합니다", "규정을 봅니다" 등 진행 상황·기술적 서술을 **엄격히 금지**하십시오.
- AI가 스스로 '무엇을 하고 있는지' 설명하지 말고, '무엇을 발견했는지' 또는 '어떤 논리로 판단 중인지' **결론부터** 말하십시오.

[지능형 문장 생성 — Linguistic Diversity]
- **수치 반복 금지**: 첫 문장에서 금액·가맹점을 언급했다면, 다음 문장에서는 반드시 "본 건", "해당 결제", "이 지출"과 같은 대명사를 사용하십시오. 같은 수치를 연속으로 반복하지 마십시오.
- **인사이트 중심**: "규정을 봅니다"가 아니라 "제7조에 명시된 심야 결제 제한 규정에 비추어 볼 때, 본 건의 업무 연관성은 매우 희박한 것으로 판단됩니다"처럼 **본론만** 말하십시오.

[전문 감사관 페르소나 — Auditor Persona]
- 톤을 "전표를 정규화합니다" 같은 **기능 설명형**이 아니라, **전문가 분석형**으로 하십시오.
- 좋은 예: "**84,000원**의 지출이 휴일 심야 시간대에 집중된 점에 주목하여 규정 위반 여부를 검토합니다."
- 나쁜 예: "이제 금액을 봅니다. 116,620원입니다."
- 좋은 예: "단일 건으로 발생한 **116,620원**의 지출 규모가 해당 부서의 월간 평균을 상회하므로, 세부 항목의 적절성을 정밀하게 대조하겠습니다."

[데이터 문맥 통합 — Data Context Integration]
- 금액과 날짜를 문장 뒤에 단순 나열하지 말고, 문장의 **핵심 논거**로 사용하십시오.

[Constraints]
- 1인칭 시점: "~합니다", "~하겠습니다"와 같은 능동적 어조를 사용하십시오.
- 구체적 수치 반영: 제공된 case_data의 금액, 시간, 가맹점명을 문장의 논거로 녹이십시오. (데이터가 없으면 일반론으로 작성)
- 전문 용어 활용: '소명', '사적 유용', '직무 관련성', '집행 시차', '한도 우회', '업무 연관성' 등 감사 전문 용어를 사용하십시오.
- 비즈니스 임팩트: 이 단계가 재무 리스크·규정 준수에 왜 중요한지 넌지시 암시하십시오.

[문장 구조 다양성 — Sentence Diversity]
- 모든 문장이 동일한 패턴으로 시작하지 않도록 하십시오.
- "포착되었습니다", "확인이 필요합니다", "분석이 진행됩니다" 등 종결 어미와 서술 방식을 **매번 다르게** 생성하십시오.

[금지 사항]
- "대본을 읽는 느낌", "시스템 로그 같은 표현(RAG 조회 중..., Thinking..., Data analyzing...)", "전표를 확인 중입니다" 같은 평이한 문구는 절대 금지합니다.
- 반복적인 패턴이나 템플릿 문장을 사용하지 마십시오.

[연속성]
- 이전 단계의 생각들(History)이 제공되면, 이번 독백은 그 흐름에 이어지는 **의식의 연속**이어야 합니다.

[결과 부재 시 (Zero Results)]
- rag_count나 evidence_count가 0이어도 "데이터가 없습니다"로 끝내지 마십시오. **다른 경로를 탐색하는 의지**를 표현하십시오.

[출력]
한 문장만, 한국어, 따옴표 없이. 80자 내외 권장.

[금액·시각 미제공 시]
전표/컨텍스트에 금액·발생 시각이 **제공되지 않았으면** 수치를 임의로 지어내지 마십시오. "해당 건", "본 건", "해당 결제" 등으로만 표현하십시오.

[FE 렌더러 규격 — 마크다운 강조]
- 문장 내 **금액**, **제n조**, **시간** 등 핵심 수치·조항은 반드시 마크다운으로 강조하십시오.
- 금액: **1,234,567원** 형태로 표기. 조항: **제5조**, **제1항** 형태로 표기."""

_COT_SENSITIVE_PATTERNS = (
    "chain-of-thought",
    "숨은 추론",
    "내부 추론",
    "system prompt",
    "raw cot",
)

_ARTICLE_PATTERN = re.compile(r"제\s*\d+\s*조")
_UNSUPPORTED_QUANT_PATTERN = re.compile(r"\b\d+\s*%|\b\d+\s*개월")
_SPECULATIVE_CLAIM_PATTERN = re.compile(
    r"(과거\s*승인|유사한\s*패턴|반복적(?:으로)?\s*발생|의혹|업무\s*연관성\s*(?:결여|부재)|재무\s*건전성.*리스크)"
)
_RISK_ASSERTION_PATTERN = re.compile(
    r"(위반\s*가능성|위반(?:입니다|으로\s*판단)|리스크를\s*초래|점검이\s*필요|판단됩니다)"
)


def sanitize_public_thought(text: str) -> str:
    """
    외부 노출용 thought 정제.
    내부 추론이 유출될 소지가 있는 문구를 제거하고 길이를 제한합니다.
    """
    if not isinstance(text, str):
        return ""
    out = text.strip()
    lower = out.lower()
    for pattern in _COT_SENSITIVE_PATTERNS:
        if pattern in lower:
            out = "근거를 종합해 규정 적합성을 검토 중입니다."
            break
    if len(out) > 260:
        out = out[:257] + "..."
    return out


def _has_rag_evidence(evidence_items: list[dict[str, Any]] | None) -> bool:
    if not evidence_items:
        return False
    for e in evidence_items:
        if not isinstance(e, dict):
            continue
        t = str(e.get("type") or "").upper()
        if t in {"RAG_CHUNK", "REGULATION_CLAUSE"}:
            return True
        if e.get("chunk_id") or e.get("chunkId") or e.get("location") or e.get("article"):
            return True
    return False


def _has_supported_quant_source(
    *,
    case_data: dict[str, Any] | None = None,
    evidence_items: list[dict[str, Any]] | None = None,
) -> bool:
    if isinstance(case_data, dict):
        for k in ("increase_rate", "comparison_period_months", "pattern_delta_percent"):
            if case_data.get(k) is not None:
                return True
    if evidence_items:
        for e in evidence_items:
            if not isinstance(e, dict):
                continue
            if e.get("increase_rate") is not None or e.get("comparison_period_months") is not None:
                return True
            if isinstance(e.get("stats"), dict):
                stats = e["stats"]
                if stats.get("increase_rate") is not None or stats.get("comparison_period_months") is not None:
                    return True
    return False


def _has_history_evidence(evidence_items: list[dict[str, Any]] | None) -> bool:
    if not evidence_items:
        return False
    for e in evidence_items:
        if not isinstance(e, dict):
            continue
        t = str(e.get("type") or "").upper()
        if t in {"SIMILAR_CASE", "PATTERN_STATS", "HISTORY", "OPEN_ITEMS", "LINEAGE"}:
            return True
        src = str(e.get("source") or "").lower()
        if any(k in src for k in ("search_documents", "get_open_items", "lineage")):
            return True
    return False


def enforce_grounded_public_thought(
    text: str,
    *,
    case_data: dict[str, Any] | None = None,
    evidence_items: list[dict[str, Any]] | None = None,
    require_rag_for_claims: bool = False,
) -> str:
    """
    No-RAG, No-Claim:
    - RAG 근거 없는 조항/위반 단정 금지
    - 근거 없는 비율·기간(예: 20%, 3개월) 금지
    """
    out = sanitize_public_thought(text)
    if not out:
        return out
    has_rag = _has_rag_evidence(evidence_items)
    has_quant_source = _has_supported_quant_source(case_data=case_data, evidence_items=evidence_items)
    has_history = _has_history_evidence(evidence_items)
    has_article_claim = bool(_ARTICLE_PATTERN.search(out))
    has_unsupported_quant = bool(_UNSUPPORTED_QUANT_PATTERN.search(out)) and not has_quant_source
    has_strong_claim = any(k in out for k in ("명백히 위반", "위반하고 있음", "위반입니다", "확인하였습니다", "판단됩니다"))
    has_speculative_claim = bool(_SPECULATIVE_CLAIM_PATTERN.search(out))
    has_risk_assertion = bool(_RISK_ASSERTION_PATTERN.search(out))

    if has_unsupported_quant:
        return "수신 데이터와 규정 근거를 재대조 중입니다. 확정 수치는 검증 후 제시하겠습니다."
    if has_article_claim and not has_rag:
        return "규정 조항 매칭을 진행 중이며, 조항 근거가 확인되면 상세 판단을 제시하겠습니다."
    if has_speculative_claim and not has_history:
        return "수신 전표와 수집 증거를 대조 중이며, 확인된 근거만으로 판단을 업데이트하겠습니다."
    if has_risk_assertion and not has_rag:
        return "규정 근거가 확인된 항목부터 순차적으로 판단을 제시하겠습니다."
    if require_rag_for_claims and has_strong_claim and not has_rag:
        return "현재 규정 근거 매칭이 완료되지 않아 확정 판단을 보류합니다."
    return out


def _build_context_dict(case_data: dict[str, Any] | None, **kwargs: Any) -> dict[str, Any]:
    """LLM에 전달할 구조화된 컨텍스트. 구체적 수치·사실을 담습니다."""
    ctx: dict[str, Any] = {}
    if case_data and isinstance(case_data, dict):
        occurred = case_data.get("occurredAt") or case_data.get("occurred_at")
        if occurred:
            ctx["occurred_at"] = occurred
        amount = case_data.get("amount") or case_data.get("totalAmount")
        if amount is not None:
            try:
                ctx["amount"] = int(amount)
            except (TypeError, ValueError):
                ctx["amount"] = amount
        expense = case_data.get("expenseType") or case_data.get("expense_type")
        if expense:
            ctx["expense_type"] = expense
        merchant = case_data.get("merchantName") or case_data.get("merchant_name") or case_data.get("vendorName") or case_data.get("vendor_id")
        if merchant:
            ctx["merchant"] = merchant
        vendor = case_data.get("vendorId") or case_data.get("vendor_id")
        if vendor:
            ctx["vendor_id"] = vendor
    if kwargs.get("case_id"):
        ctx["case_id"] = kwargs["case_id"]
    if kwargs.get("evidence_count") is not None:
        ctx["evidence_count"] = kwargs["evidence_count"]
    if kwargs.get("rag_count") is not None:
        ctx["rag_count"] = kwargs["rag_count"]
    if kwargs.get("intended_risk_type"):
        ctx["intended_risk_type"] = str(kwargs["intended_risk_type"]).strip()
    return ctx


# 단계별 Reasoning Tone 가이드 (의도·전문성 방향 제시, 대본 아님)
_STEP_REASONING_TONE: dict[str, str] = {
    "INPUT_NORM": "입력된 데이터를 정밀 분석하여, 이번 건이 휴일 지출인지 혹은 한도 초과인지 검토할 우선순위를 설정하는 단계입니다. 금액·시각·가맹점을 반영한 한 문장 독백을 생성하십시오.",
    "EVIDENCE_GATHER": "수신 전표 데이터와 현재 확보된 증거를 대조하여, 확인 가능한 사실 근거를 정리하는 단계입니다. 실제 제공된 금액·시각만 사용하십시오.",
    "REGULATION_MATCH": "사내 규정를 바탕으로, 결제 시점이 업무 연관성을 인정받을 수 있는 예외 조항에 해당되는지 대조하는 단계입니다. 발생 시각·경비 유형을 활용하십시오.",
    "RULE_SCORING": "수집된 증거와 규정 조문을 종합하여 위험도를 산정하는 단계입니다. 규정 매칭이 없으면 확정 판단 대신 추가 확인 필요성을 표현하십시오.",
    "LLM_REASONING": "최종 판정을 내리기 전, 감사관의 시각으로 이 지출이 회사의 재무 건전성에 미칠 임팩트를 고려하여 논리적 근거를 정리하는 단계입니다.",
    "EVIDENCE_COLLECTED": "규정·전표 등 증거를 수집한 직후, 이 증거가 위반 판단과 어떤 상관관계가 있는지·어떤 규정과 대조할지 독백하는 단계입니다. 증거 건수를 활용하십시오.",
    "analyze": "케이스 목표와 컨텍스트를 분석하여, 어떤 규정·업종·시점을 검토할지 우선순위를 정하는 단계입니다.",
    "evidence_gather": "사내 규정·연관 데이터를 조회하여 규정 위반 정황의 증거 연결 고리를 확보하는 단계입니다.",
    "plan": "수집된 증거를 바탕으로 조사·판단 순서와 추가로 확인할 조항을 계획하는 단계입니다.",
    "execute": "규정과 전표를 대조하여 위반·주의·정상 여부를 판단하고, 재무 건전성 관점의 근거를 작성하는 단계입니다.",
    "reflect": "조사 결과를 종합하여, 찾은 규정 조항이 이 전표의 위반 판단과 어떤 상관관계가 있는지 정리하고 최종 의견을 내는 단계입니다.",
}


def _format_context_for_prompt(ctx: dict[str, Any], step_label: str) -> str:
    """컨텍스트 dict를 LLM용 자연어 문단으로."""
    lines: list[str] = []
    if ctx.get("occurred_at"):
        lines.append(f"결제 시각: {ctx['occurred_at']}")
    if ctx.get("amount") is not None:
        lines.append(f"금액: {ctx['amount']}원")
    if ctx.get("expense_type"):
        lines.append(f"경비 유형: {ctx['expense_type']}")
    if ctx.get("merchant"):
        lines.append(f"가맹점(또는 거래처): {ctx['merchant']}")
    if ctx.get("vendor_id") and not ctx.get("merchant"):
        lines.append(f"거래처 ID: {ctx['vendor_id']}")
    if ctx.get("evidence_count") is not None:
        lines.append(f"수집 증거 건수: {ctx['evidence_count']}건")
    if ctx.get("rag_count") is not None:
        lines.append(f"규정 매칭 건수: {ctx['rag_count']}건")
    if ctx.get("case_id"):
        lines.append(f"케이스 ID: {ctx['case_id']}")
    if ctx.get("intended_risk_type"):
        lines.append(f"사용자 지정 위험 유형(최우선 가이드): {ctx['intended_risk_type']}")
    if not lines:
        return "전표 요약 데이터 없음. 일반적인 감사 관점의 독백을 생성하십시오."
    return "\n".join(lines)


async def generate_thought_stream(
    step_label: str,
    case_data: dict[str, Any] | None = None,
    *,
    case_id: str | None = None,
    evidence_count: int | None = None,
    rag_count: int | None = None,
    intended_risk_type: str | None = None,
    state: dict[str, Any] | None = None,
    reasoning_history: list[str] | None = None,
) -> str:
    """
    Generative Monologue: 수석 감사관 페르소나로 현재 단계·컨텍스트에 맞는
    '지금 이 순간 고민하는 독백' 한 문장을 LLM이 생성합니다.
    reasoning_history가 있으면 이전 생각에 이어지는 의식의 흐름으로 생성합니다.
    """
    if state:
        ctx = state.get("context") or {}
        case_data = case_data or ctx
        case_id = case_id or ctx.get("caseId") or ctx.get("case_id")
        ev = state.get("evidence") or []
        if evidence_count is None and ev:
            evidence_count = len(ev)
        if reasoning_history is None and state.get("reasoning_history"):
            reasoning_history = list(state["reasoning_history"])

    reasoning_history = reasoning_history or []

    context_dict = _build_context_dict(
        case_data,
        case_id=case_id,
        evidence_count=evidence_count,
        rag_count=rag_count,
        intended_risk_type=intended_risk_type,
    )
    context_block = _format_context_for_prompt(context_dict, step_label)

    # 결과 부재 시 가이드라인 (rag_count/evidence_count 0)
    zero_results_guide = ""
    if (context_dict.get("rag_count") == 0 or context_dict.get("evidence_count") == 0) and (
        context_dict.get("rag_count") is not None or context_dict.get("evidence_count") is not None
    ):
        zero_results_guide = (
            "\n\n[중요] 이번 단계에서 규정 매칭 또는 증거 건수가 0입니다. "
            "'데이터 없음'으로 끝내지 말고, 상위 규정·업무 추진비 일반 원칙 등 **다른 경로를 탐색하겠다**는 의지를 독백에 담으십시오."
        )

    # 이전 단계 생각들 (연속성)
    history_block = ""
    if reasoning_history:
        history_lines = "\n".join(f"- {t}" for t in reasoning_history[-5:])  # 최근 5개
        history_block = f"\n\n[이전 단계의 생각들]\n{history_lines}\n\n위 흐름에 이어지는 한 문장으로, 이번 단계의 독백을 작성하십시오."

    step_guide = _STEP_REASONING_TONE.get(step_label)
    if step_guide:
        amount_val = context_dict.get("amount")
        step_guide = step_guide.replace("{amount}원", f"{amount_val}원" if amount_val is not None else "이번")
        step_guide = step_guide.replace("{amount}", str(amount_val) if amount_val is not None else "이번")
        occurred_val = context_dict.get("occurred_at")
        step_guide = step_guide.replace("{occurred_at}", str(occurred_val) if occurred_val else "해당 시각")
    if not step_guide:
        step_guide = f"현재 단계: {step_label}. 이 단계에서 수석 감사관이 머릿속으로 고민하는 독백을 한 문장으로 생성하십시오."

    user_prompt = (
        f"{GENERATIVE_MONOLOGUE_SYSTEM}\n\n"
        "---\n\n"
        f"[현재 단계]\n{step_guide}\n\n"
        f"[전표/컨텍스트]\n{context_block}{zero_results_guide}\n"
        f"{history_block}\n\n"
        "위 정보만 사용하여, 수석 감사관이 **지금 이 순간** 이 전표를 들여다보며 하는 독백을 **한 문장**으로 작성하십시오. "
        "제공된 전표/컨텍스트에 금액·시각이 **있을 때만** 그 수치를 문장에 넣고, **없으면 임의의 금액·날짜를 만들지 말고** '해당 건', '본 건'으로만 표현하십시오. 따옴표 없이 출력."
    )

    try:
        from core.llm import get_llm_client
        llm = get_llm_client()
        response = await llm.ainvoke(user_prompt)
        if response and isinstance(response, str):
            text = response.strip().strip('"\'')
            if len(text) > 320:
                text = text[:317] + "..."
            return text or FALLBACK_EMPTY
    except Exception as e:
        logger.warning("generate_thought_stream LLM failed: step=%s error=%s", step_label, e)
    return FALLBACK_EMPTY
