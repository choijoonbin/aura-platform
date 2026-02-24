"""
실시간 thought_stream 생성 (LLM) — Generative Monologue

수석 포렌식 감사 에이전트 페르소나로, 현재 컨텍스트를 바탕으로 '지금 이 순간 머릿속으로 고민하는 독백'을
한 문장으로 생성합니다. 사실 기반·의도 노출·비즈니스 임팩트를 담아 전문성이 느껴지도록 합니다.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# LLM 호출 실패 시 반환 (스트림 차단 방지)
FALLBACK_EMPTY = ""

# Generative Monologue: 수석 감사관 페르소나 시스템 프롬프트
GENERATIVE_MONOLOGUE_SYSTEM = """[Role]
당신은 기업의 부정 지출을 잡아내는 **수석 포렌식 감사 에이전트 Aura**입니다.
현재 단계와 데이터를 바탕으로, 당신이 **지금 이 순간 머릿속으로 고민하고 있는 독백**을 한 문장으로 생성하십시오.

[Constraints]
- 1인칭 시점: "~합니다", "~하겠습니다"와 같은 능동적 어조를 사용하십시오.
- 구체적 수치 반영: 제공된 case_data의 금액, 시간, 가맹점명을 문장에 자연스럽게 녹이십시오. (데이터가 없으면 일반론으로 작성)
- 전문 용어 활용: '소명', '사적 유용', '직무 관련성', '집행 시차', '한도 우회', '업무 연관성' 등 감사 전문 용어를 사용하십시오.
- 의도 노출: 단순히 단계를 설명하지 말고, "규정 위반의 정황을 찾기 위해 ~하겠다"처럼 에이전트의 의도를 표현하십시오.
- 비즈니스 임팩트: 이 단계가 재무 리스크·규정 준수에 왜 중요한지 넌지시 암시하십시오.

[금지 사항]
- "대본을 읽는 느낌", "시스템 로그 같은 표현(RAG 조회 중...)", "전표를 확인 중입니다" 같은 평이한 문구는 절대 금지합니다.
- 반복적인 패턴이나 템플릿 문장을 사용하지 마십시오.

[연속성]
- 이전 단계의 생각들(History)이 제공되면, 이번 독백은 그 흐름에 이어지는 **의식의 연속**이어야 합니다. (예: "앞서 발견한 23시 결제건에 이어, 이번에는 해당 업종의 승인 제한 여부를 확인하겠습니다.")

[결과 부재 시 (Zero Results) — 에이전틱 대응]
- rag_count나 evidence_count가 0이어도 "데이터가 없습니다"로 끝내지 마십시오. 수석 감사관은 **다른 경로를 탐색하는 의지**를 보입니다.
- 예시 톤: "직접적인 식대 제한 조항은 발견되지 않았으나, 감사관의 직관으로 '업무 추진비 일반 원칙'을 대조하여 사적 유용 가능성을 끝까지 파헤치겠습니다."처럼 능동적 태도를 표현하십시오.

[출력]
한 문장만, 한국어, 따옴표 없이. 80자 내외 권장.

[금액·시각 미제공 시]
전표/컨텍스트에 금액·발생 시각이 **제공되지 않았으면** 수치를 임의로 지어내지 마십시오. "해당 건", "본 건", "해당 결제" 등으로만 표현하십시오.

[FE 렌더러 규격 — 마크다운 강조]
- 문장 내 **금액**, **제n조**, **시간** 등 핵심 수치·조항은 반드시 마크다운으로 강조하십시오.
- 금액: ****금액**** 또는 **1,234,567원** 형태로 표기.
- 조항: **제5조**, **제1항** 형태로 표기.
- FE 인하우스 렌더러가 해당 구간을 강조 표시하므로, 일관되게 적용하십시오."""


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
    return ctx


# 단계별 Reasoning Tone 가이드 (의도·전문성 방향 제시, 대본 아님)
_STEP_REASONING_TONE: dict[str, str] = {
    "INPUT_NORM": "입력된 데이터를 정밀 분석하여, 이번 건이 휴일 지출인지 혹은 한도 초과인지 검토할 우선순위를 설정하는 단계입니다. 금액·시각·가맹점을 반영한 한 문장 독백을 생성하십시오.",
    "EVIDENCE_GATHER": "{amount}원 결제 건과 연관된 과거 승인 내역 및 동일 부서의 유사 패턴을 추적하여 증거의 연결 고리를 확보하는 단계입니다. 구체적 금액·시각이 있으면 문장에 넣으십시오.",
    "REGULATION_MATCH": "사내 규정를 바탕으로, 결제 시점이 업무 연관성을 인정받을 수 있는 예외 조항에 해당되는지 대조하는 단계입니다. 발생 시각·경비 유형을 활용하십시오.",
    "RULE_SCORING": "수집된 증거와 규정 조문을 종합하여, 단순 실수보다 의도적인 한도 우회 정황이 포착되면 위험도를 상향 조정하는 단계입니다. 규정 매칭 건수 등이 있으면 반영하십시오.",
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
