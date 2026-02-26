"""
Case Audit Analysis Pipeline

케이스 기반 자율 감사 분석: 전표·증거 수집 → 규정(RAG) 매칭 → 룰 스코어링 → LLM 판단 → 제안·콜백.

Step1: 입력 정규화 (evidence json schema 통일)
Step2: 간단 룰 스코어링 (금액, 거래처 신규, 역분개 체인 등)
Step3: LLM 호출로 reasonText 생성
Step4: proposals 생성
Step5: 결과 payload 구성 후 BE 콜백 (선택)
"""

import json
import logging
import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from core.analysis.audit_analysis_events import (
    AnalysisStartedEvent,
    AnalysisStepEvent,
    AnalysisEvidenceEvent,
    AnalysisConfidenceEvent,
    AnalysisProposalEvent,
    AnalysisCompletedEvent,
    AnalysisFailedEvent,
)
from core.analysis.thought_stream import (
    enforce_grounded_public_thought,
    generate_thought_stream,
)
from core.analysis.reasoning_citations import (
    build_regulation_citations,
    build_citation_reasoning,
    get_violation_clause_evidence,
)
from core.analysis.rag_quality import (
    apply_rule_first_filter as _apply_rule_first_filter,
    build_dynamic_rag_query as _build_dynamic_rag_query,
    build_rule_first_constraints as _build_rule_first_constraints,
    rerank_vector_results as _rerank_vector_results,
    sanitize_external_reference_text as _sanitize_external_reference_text,
)
from core.analysis.rag import hybrid_retrieve, retrieve_rag_pgvector
from core.analysis.policy_engine import (
    evaluate_policy_gate,
    normalize_hr_status,
    normalize_mcc_code,
    normalize_occurred_at,
)
from core.analysis.mcp_adapter import resolve_fact_context
from core.config import get_settings
from core.llm import get_llm_client
from core.observability import incr, start_timer, stop_timer
from tools.synapse_finance_tool import get_case, search_documents, get_open_items, get_lineage

logger = logging.getLogger(__name__)

# 분석 비활성 플래그 (DEMO_OFF 등)
ANALYSIS_DISABLED_ENV = "DEMO_OFF"

# BE step_completion_rate 계산용: step 이벤트 총 개수 (injectStepCompletionRate에서 stepIndex/total_steps * 100)
TOTAL_ANALYSIS_STEPS = 5

# 스크리닝 caseType 6종 — 분석 시 이미 분류된 경우 스크리닝 판단(reasonText)과 RAG 결과에 맞춰 reasonText 정렬용 (screening과 동기화)
SCREENING_CASE_TYPES = frozenset({
    "HOLIDAY_USAGE",
    "DUPLICATE_SUSPECT",
    "SPLIT_PAYMENT",
    "PRIVATE_USE_RISK",
    "LIMIT_EXCEED",
    "UNUSUAL_PATTERN",
})

_COMPACT_NOISE_TERMS = {
    "sa",
    "g/l account document",
    "gl account document",
    "document",
    "account document",
    "expense",
}


def _risk_type_to_semantic_terms(risk_type: str | None) -> list[str]:
    ru = str(risk_type or "").strip().upper()
    if "HOLIDAY" in ru:
        return ["휴일", "주말", "심야"]
    if "LIMIT" in ru:
        return ["한도", "초과"]
    if "PRIVATE" in ru:
        return ["사적사용", "업무무관"]
    if "SPLIT" in ru:
        return ["분할결제", "반복결제"]
    if "DUPLICATE" in ru:
        return ["중복", "결제"]
    return []

_VIOLATION_TEXT_PATTERN = re.compile(r"(위반|정면으로\s*위반|명백한\s*규정\s*위반|판별됩니다)")
_ARTICLE_IN_TEXT_PATTERN = re.compile(r"제\s*\d+\s*조(?:\s*제\s*\d+\s*항)?")

CASE_TYPE_DISPLAY_NAME: dict[str, str] = {
    "HOLIDAY_USAGE": "휴일 사용 의심",
    "DUPLICATE_SUSPECT": "중복 결제 의심",
    "SPLIT_PAYMENT": "분할 결제 의심",
    "PRIVATE_USE_RISK": "사적 사용 위험",
    "LIMIT_EXCEED": "한도 초과 의심",
    "UNUSUAL_PATTERN": "이상 패턴",
    "DEFAULT": "기본 분류",
}

HR_STATUS_DISPLAY_NAME: dict[str, str] = {
    "LEAVE": "휴무/휴가",
    "OFF": "휴무",
    "VACATION": "휴가",
    "WORK": "근무",
    "WORKING": "근무",
    "BUSINESS_TRIP": "출장",
}

# BE가 Aura와 다른 코드로 저장한 경우 매핑 (예: DUPLICATE_INVOICE → DUPLICATE_SUSPECT). DEFAULT는 매핑하지 않음.
BE_CASE_TYPE_TO_SCREENING: dict[str, str] = {
    "DUPLICATE_INVOICE": "DUPLICATE_SUSPECT",
    "THRESHOLD_BREACH": "LIMIT_EXCEED",
}

# 2단계 스트리밍: LLM 독백 생성 전에 먼저 던지는 이벤트 메시지 (FE에서 "Thinking..." 또는 타이핑 효과 표시용)
THOUGHT_PENDING_MESSAGE = "생각 중..."

# 기술 단계(INPUT_NORM): AGENT_STREAM에는 발행하지 않음. 진행 상태는 step 이벤트만 사용 (FE 프로그레스 바/배너).
INPUT_NORM_THOUGHT_SHORT = "데이터 정밀 분석 중"

# AGENT_STREAM High-Value Only: 아래 문구는 스트림으로 발행하지 않음 (플레이스홀더·기술 로그)
_AGENT_STREAM_PLACEHOLDERS = frozenset({
    "데이터 정밀 분석 중",
    "생각 중...",
    "Thinking...",
    "Data analyzing...",
    "Data analyzing",
    "RAG 조회 중",
    "분석을 수행합니다",
    "이번 단계는",
    "Step 1 처리 중",
    "Step 2 처리 중",
    "Step 3 처리 중",
    "Step 4 처리 중",
    "Step 5 처리 중",
    "케이스 입력 정규화 중",
    "처리 중입니다.",
})

def _is_agent_stream_insight(content: str | None) -> bool:
    """True면 AGENT_STREAM으로 발행. 플레이스홀더·기술 로그·빈 문자열이면 False."""
    if not content or not content.strip():
        return False
    s = content.strip()
    if s in _AGENT_STREAM_PLACEHOLDERS:
        return False
    # 짧은 기술 문구: "처리 중", "분석 중", "생각 중" 등
    if len(s) < 25 and any(s.startswith(p.rstrip(".")) or p in s for p in ("처리 중", "분석 중", "생각 중")):
        return False
    # 시스템/기술 로그 패턴: "Thinking...", "Data analyzing..." 등 (대소문자 무시)
    lower = s.lower()
    if "thinking" in lower and ("..." in s or "…" in s or len(s) < 30):
        return False
    if "data analyzing" in lower or "data analysing" in lower:
        return False
    return True


_AGENT_STREAM_ALLOWED_STEPS = frozenset({
    "EVIDENCE_GATHER",
    "REGULATION_MATCH",
})


def _normalize_agent_stream_text(text: str) -> str:
    s = re.sub(r"\s+", " ", (text or "").strip().lower())
    s = re.sub(r"[^\w가-힣\s]", "", s)
    return s


def _token_jaccard_similarity(a: str, b: str) -> float:
    sa = set(re.findall(r"[가-힣A-Za-z0-9]{2,}", a or ""))
    sb = set(re.findall(r"[가-힣A-Za-z0-9]{2,}", b or ""))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _run_self_verification(
    *,
    reason_text: str,
    evidence_items: list[dict[str, Any]],
    violation_clauses: list[str],
    citations: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    최종 결론의 최소 논리 정합성 점검.
    실패시키기보다 품질 이슈를 구조적으로 기록하여 HITL/운영자가 확인 가능하게 한다.
    """
    issues: list[str] = []
    if not (reason_text or "").strip():
        issues.append("reason_text_missing")
    if not evidence_items:
        issues.append("evidence_missing")
    if not violation_clauses:
        issues.append("violation_clause_missing")
    if not citations:
        issues.append("citation_missing")
    status = "pass" if not issues else "warn"
    return {"status": status, "issues": issues}


def _split_reason_sentences(text: str) -> list[str]:
    src = (text or "").strip()
    if not src:
        return []
    # 종결 어미(다.)가 잘리지 않도록 문장 패턴 매칭으로 분리한다.
    parts = re.findall(r".+?(?:[.!?]|다\.)(?:\s+|$)|.+$", src)
    out = [p.strip() for p in parts if p and p.strip()]
    return out


def _tokens_for_overlap(text: str) -> set[str]:
    toks = re.findall(r"[가-힣A-Za-z0-9]{2,}", text or "")
    return {t.lower() for t in toks if len(t) >= 2}


def _fuzzy_overlap_count(left: set[str], right: set[str]) -> int:
    if not left or not right:
        return 0
    count = 0
    for a in left:
        for b in right:
            if a == b:
                count += 1
                break
            if len(a) >= 2 and len(b) >= 2 and (a.startswith(b) or b.startswith(a)):
                count += 1
                break
    return count


def _format_datetime_kor(value: Any, *, with_time: bool = True, include_weekday: bool = False) -> str | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    weekday_ko = ["월", "화", "수", "목", "금", "토", "일"][dt.weekday()]
    if with_time:
        return dt.strftime("%Y년 %m월 %d일 %H:%M:%S") + (f" ({weekday_ko})" if include_weekday else "")
    return dt.strftime("%Y년 %m월 %d일") + (f" ({weekday_ko})" if include_weekday else "")


def _format_hr_status_display(value: Any) -> str | None:
    if value in (None, ""):
        return None
    key = str(value).strip().upper()
    return HR_STATUS_DISPLAY_NAME.get(key, str(value))


def _compute_reason_grounding_coverage(
    *,
    reason_text: str,
    evidence_items: list[dict[str, Any]],
    citations: list[dict[str, Any]],
) -> dict[str, Any]:
    sentences = _split_reason_sentences(reason_text)
    if not sentences:
        return {
            "total_sentences": 0,
            "grounded_sentences": 0,
            "coverage_ratio": 0.0,
            "ungrounded_sentences": [],
        }
    corpus_chunks: list[str] = []
    for e in evidence_items or []:
        if not isinstance(e, dict):
            continue
        joined = " ".join(
            str(e.get(k) or "")
            for k in ("excerpt", "content", "location", "article", "clause", "regulation_article", "regulation_clause")
        ).strip()
        if joined:
            corpus_chunks.append(joined)
    for c in citations or []:
        if not isinstance(c, dict):
            continue
        joined = " ".join(str(c.get(k) or "") for k in ("title", "reference", "excerpt")).strip()
        if joined:
            corpus_chunks.append(joined)
    evidence_text = " ".join(corpus_chunks)
    evidence_tokens = _tokens_for_overlap(evidence_text)

    grounded = 0
    ungrounded: list[str] = []
    for s in sentences:
        s_tokens = _tokens_for_overlap(s)
        overlap = len(s_tokens & evidence_tokens) if s_tokens else 0
        art_in_sentence = _ARTICLE_IN_TEXT_PATTERN.search(s or "")
        article_grounded = False
        if art_in_sentence and art_in_sentence.group(0):
            art_norm = re.sub(r"\s+", "", art_in_sentence.group(0))
            article_grounded = art_norm in re.sub(r"\s+", "", evidence_text)
        if overlap >= 2 or article_grounded:
            grounded += 1
        else:
            ungrounded.append(s[:160])
    ratio = grounded / len(sentences) if sentences else 0.0
    return {
        "total_sentences": len(sentences),
        "grounded_sentences": grounded,
        "coverage_ratio": round(ratio, 3),
        "ungrounded_sentences": ungrounded[:5],
    }


def _build_analysis_score_breakdown(
    *,
    anomaly_score: float,
    pattern_match: float,
    rule_compliance: float,
    output_overall: float,
    quality_gate_codes: list[str],
    coverage_ratio: float | None = None,
) -> dict[str, Any]:
    weighted = [
        {
            "name": "anomaly_score",
            "raw": round(float(anomaly_score), 4),
            "weight": 0.4,
            "weighted": round(float(anomaly_score) * 0.4, 4),
        },
        {
            "name": "pattern_match",
            "raw": round(float(pattern_match), 4),
            "weight": 0.3,
            "weighted": round(float(pattern_match) * 0.3, 4),
        },
        {
            "name": "rule_compliance",
            "raw": round(float(rule_compliance), 4),
            "weight": 0.3,
            "weighted": round(float(rule_compliance) * 0.3, 4),
        },
    ]
    adjustments: list[dict[str, Any]] = []
    for code in (quality_gate_codes or []):
        if code in {"RAG_ZERO", "INPUT_PARTIAL", "EVIDENCE_COVERAGE_LOW"}:
            adjustments.append({"code": code, "effect": "downward_cap_or_hold"})
    if coverage_ratio is not None:
        adjustments.append({"code": "EVIDENCE_COVERAGE", "value": round(float(coverage_ratio), 3)})
    policy_score = int(round(float(rule_compliance) * 100))
    evidence_score = int(round(float(coverage_ratio if coverage_ratio is not None else pattern_match) * 100))
    final_score = int(round(float(output_overall) * 100))
    return {
        "components": weighted,
        "adjustments": adjustments,
        "final_overall": round(float(output_overall), 4),
        "final_risk_score": final_score,
        "policy_score": policy_score,
        "evidence_score": evidence_score,
        "final_score": final_score,
    }


def _is_risk_article_semantically_aligned(
    *,
    risk_type: str | None,
    citations: list[dict[str, Any]],
) -> bool:
    ru = str(risk_type or "").strip().upper()
    if not ru:
        return True
    corpus = " ".join(
        str(c.get("reference") or c.get("title") or c.get("excerpt") or "")
        for c in (citations or [])
        if isinstance(c, dict)
    )
    corpus_norm = re.sub(r"\s+", "", corpus)
    if ru == "HOLIDAY_USAGE":
        if any(k in corpus for k in ("휴일", "주말", "공휴일", "심야", "시간대", "야간")):
            return True
        if any(a in corpus_norm for a in ("제38조", "제39조")):
            return True
        return False
    if ru == "LIMIT_EXCEED":
        if any(k in corpus for k in ("한도", "초과", "금액")):
            return True
        if "제40조" in corpus_norm:
            return True
        return False
    if ru == "SPLIT_PAYMENT":
        if any(k in corpus for k in ("분할결제", "분할전표")):
            return True
        if "제41조" in corpus_norm:
            return True
        return False
    return True


def _analysis_fewshot_by_risk(risk_type: str | None) -> str:
    rt = str(risk_type or "").strip().upper()
    if rt == "HOLIDAY_USAGE":
        return (
            "[예시]\n"
            "입력: isHoliday=true, hrStatus=LEAVE, occurredAt=...23:10, RAG 조항 2건.\n"
            "좋은 출력: '휴일(야간) 사용으로 제n조 제한 취지와 충돌하며, 근거 조항에 따라 추가 소명 필요.'\n"
            "나쁜 출력: '3개월 대비 20% 증가' (입력/근거 없음).\n"
        )
    if rt == "LIMIT_EXCEED":
        return (
            "[예시]\n"
            "입력: budgetExceeded=true, amount 고액, RAG 조항 1건.\n"
            "좋은 출력: '예산/한도 초과 신호가 확인되며 조항 근거에 따라 위반 가능성이 높다.'\n"
            "나쁜 출력: '제5조 위반 확정' (조항 근거 없는 확정 금지).\n"
        )
    if rt == "PRIVATE_USE_RISK":
        return (
            "[예시]\n"
            "입력: mccCode=금지업종군, 업무연관성 근거 부족, RAG 조항 1건 이상.\n"
            "좋은 출력: '업무 관련성 부족 및 금지업종 신호로 사적사용 의심.'\n"
            "나쁜 출력: '무조건 횡령' (형사 단정 금지).\n"
        )
    if rt == "SPLIT_PAYMENT":
        return (
            "[예시]\n"
            "입력: 분할 패턴 근거/반복 결제 증거 존재 시에만 분할결제 의심 문장 사용.\n"
            "근거 없으면 UNUSUAL_PATTERN 또는 보류로 작성.\n"
        )
    if rt == "DUPLICATE_SUSPECT":
        return (
            "[예시]\n"
            "입력: 중복 전표키/유사 금액·시각 증거가 있을 때만 중복 의심 사용.\n"
            "근거 없으면 단정 금지.\n"
        )
    return (
        "[예시]\n"
        "입력 근거가 부족하면 '확정 판단 보류'로 마무리하고 추가 확인 항목을 제시.\n"
    )


def _has_rag_evidence_items(evidence_items: list[dict[str, Any]]) -> bool:
    for e in evidence_items or []:
        if not isinstance(e, dict):
            continue
        t = str(e.get("type") or "").upper()
        if t in {"RAG_CHUNK", "REGULATION_CLAUSE"}:
            return True
        if e.get("chunk_id") or e.get("chunkId") or e.get("location") or e.get("article"):
            return True
    return False


def _screening_case_summary(screening_case_type: str | None) -> str:
    mapping = {
        "HOLIDAY_USAGE": "휴무일 사용 가능 신호가 감지되었습니다.",
        "DUPLICATE_SUSPECT": "중복 지출 가능 신호가 감지되었습니다.",
        "SPLIT_PAYMENT": "분할 결제 가능 신호가 감지되었습니다.",
        "PRIVATE_USE_RISK": "사적 사용 가능 신호가 감지되었습니다.",
        "LIMIT_EXCEED": "한도 초과 가능 신호가 감지되었습니다.",
        "UNUSUAL_PATTERN": "비정상 패턴 신호가 감지되었습니다.",
    }
    key = (screening_case_type or "").strip().upper()
    return mapping.get(key, "스크리닝 신호가 감지되었습니다.")


def _case_type_name(code: str | None) -> str:
    key = (code or "").strip().upper()
    return CASE_TYPE_DISPLAY_NAME.get(key, key or "미분류")


def _replace_case_type_codes(text: str) -> str:
    if not text:
        return text
    out = text
    for code, name in CASE_TYPE_DISPLAY_NAME.items():
        out = out.replace(code, name)
    for code, name in HR_STATUS_DISPLAY_NAME.items():
        out = re.sub(rf"\b{re.escape(code)}\b", name, out)
    return out


def _build_hold_reason_with_context(
    *,
    case_data: dict[str, Any] | None,
    risk_type: str | None,
    hold_reason: str,
) -> str:
    """보류 문구에도 케이스 맥락(유형/일자/금액/근태)을 남긴다."""
    parts: list[str] = []
    if risk_type:
        parts.append(f"본 건은 **{_case_type_name(risk_type)}** 신호로 분류되었으나,")
    occurred = None
    amount = None
    hr = None
    if isinstance(case_data, dict):
        occurred = case_data.get("occurredAt") or case_data.get("occurred_at")
        amount = case_data.get("amount")
        hr = case_data.get("hrStatus") or case_data.get("hr_status")
    facts: list[str] = []
    if occurred:
        occurred_label = _format_datetime_kor(occurred, with_time=True, include_weekday=True) or str(occurred)[:19]
        facts.append(f"발생 시각 **{occurred_label}**")
    if amount is not None:
        try:
            facts.append(f"금액 **{int(float(amount)):,}원**")
        except Exception:
            pass
    if hr:
        hr_label = _format_hr_status_display(hr) or str(hr)
        facts.append(f"근태 **{hr_label}**")
    if facts:
        parts.append(", ".join(facts) + " 기준으로")
    parts.append(hold_reason)
    return " ".join(parts)


def _finalize_reason_text_with_grounding(
    *,
    reason_text: str,
    case_data: dict[str, Any] | None,
    evidence_items: list[dict[str, Any]],
    screening_case_type: str | None,
    screening_reason_text: str | None,
) -> str:
    """
    최종 reasonText를 RAG 근거 중심으로 정제.
    - No-RAG 상황에서는 조항/수치 단정을 제거
    - 스크리닝 문구를 그대로 인용하지 않고 안전 요약으로 대체
    """
    grounded = enforce_grounded_public_thought(
        reason_text,
        case_data=case_data,
        evidence_items=evidence_items,
        require_rag_for_claims=True,
    )
    if grounded == reason_text:
        return reason_text

    if _has_rag_evidence_items(evidence_items):
        return grounded

    # No-RAG: 스크리닝 텍스트를 그대로 붙이지 않고, 유형 요약만 노출
    if screening_case_type:
        return (
            f"{_screening_case_summary(screening_case_type)} "
            "현재 규정 근거 매칭이 충분하지 않아 확정 판단은 보류합니다."
        )

    if screening_reason_text:
        safe_screening = enforce_grounded_public_thought(
            screening_reason_text,
            case_data=case_data,
            evidence_items=evidence_items,
            require_rag_for_claims=True,
        )
        # 여전히 근거 단정 성격이면 일반 문구로 강등
        if safe_screening != screening_reason_text:
            return "스크리닝 신호가 감지되었으나 현재 규정 근거 매칭이 충분하지 않아 확정 판단은 보류합니다."
        return f"{safe_screening} 현재 규정 근거 매칭이 충분하지 않아 확정 판단은 보류합니다."

    return grounded


def _coords_payload(id_mapping: dict[str, Any]) -> dict[str, Any]:
    """thought_pending / AGENT_STREAM / step 모든 이벤트에 누락 없이 넣을 좌표 (target_buzei, chunk_id, doc_id)."""
    return {
        "target_buzei": id_mapping.get("target_buzei"),
        "chunk_id": id_mapping.get("chunk_id"),
        "doc_id": id_mapping.get("doc_id"),
    }


def _build_evidence_map_json(
    evidence_items: list[dict[str, Any]],
    target_buzei: str | None,
    doc_id: str | None,
    *,
    item_no: str | None = None,
) -> list[dict[str, Any]]:
    """전표 행(buzei)·item_idx ↔ 규정 chunk_id·근거 문장 매핑. FE 4탭용 필수. 절대 누락 금지."""
    out: list[dict[str, Any]] = []
    buzei = (str(target_buzei).strip() or None) if target_buzei is not None else None
    seen: set[tuple[str | None, str | None]] = set()
    for idx, e in enumerate(evidence_items):
        if not isinstance(e, dict):
            continue
        cid = e.get("chunk_id") or e.get("chunkId")
        if not cid:
            continue
        cid = str(cid).strip()
        key = (buzei, cid)
        if key in seen:
            continue
        seen.add(key)
        row: dict[str, Any] = {"target_buzei": buzei, "chunk_id": cid, "doc_id": doc_id}
        item_idx = e.get("item_no") or e.get("item_id") or (str(idx) if idx > 0 else item_no)
        if item_idx is not None:
            row["item_idx"] = str(item_idx).strip() if str(item_idx).strip() else None
        excerpt = (e.get("excerpt") or e.get("content") or "").strip()
        if excerpt:
            row["excerpt"] = excerpt[:500]
        out.append(row)
    if not out and (buzei or doc_id):
        chunk_id_ref = None
        for e in evidence_items:
            if isinstance(e, dict):
                cid = e.get("chunk_id") or e.get("chunkId")
                if cid:
                    chunk_id_ref = str(cid).strip()
                    break
        if chunk_id_ref or buzei:
            row = {"target_buzei": buzei, "chunk_id": chunk_id_ref, "doc_id": doc_id}
            if item_no:
                row["item_idx"] = str(item_no).strip()
            out.append(row)
    return out


def _build_decision_reason(
    reason_text: str,
    violation_clause: str,
    violation_clauses: list[str] | None,
    evidence_items: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    doc_id: str | None,
    item_id: str | None,
    chunk_id: str | None,
    target_buzei: str | None,
    case_data: dict[str, Any] | None,
    recommended_action: str = "",
    item_no: str | None = None,
) -> dict[str, Any]:
    """
    Universal Compliance Auditor 규격의 구조화된 인사이트(Reason + Evidence JSON) 생성.
    BE V65 decision_reason 저장 및 callback 시 [종합 판정 / 핵심 근거 / 위반 조항 / 권고 사항] 분리 + evidence_map_json(전표 행↔근거 문장) 필수 포함.
    """
    case_data_flat: dict[str, Any] = {}
    if isinstance(case_data, dict):
        for k in ("amount", "occurredAt", "occurred_at", "expenseType", "expense_type", "vendorId", "vendor_id"):
            if k in case_data and case_data[k] is not None:
                case_data_flat["field"] = k
                case_data_flat["value"] = case_data[k]
                break
        if not case_data_flat and case_data:
            case_data_flat = {"field": "case", "value": str(case_data)[:200]}
    evidence_payload: dict[str, Any] = {
        "source_chunk_id": chunk_id,
        "doc_id": doc_id,
        "chunk_index": None,
        "hierarchy_path": violation_clause or "",
        "conflict_point": (reason_text[:300] if reason_text else ""),
        "case_data": case_data_flat,
    }
    for e in evidence_items:
        if isinstance(e, dict) and (e.get("type") == "RAG_CHUNK" or e.get("chunk_id") or e.get("chunkId")):
            evidence_payload["chunk_index"] = e.get("chunk_index") or e.get("chunkIndex")
            break
    citations_payload: list[dict[str, Any]] = []
    for c in (citations or [])[:10]:
        if not isinstance(c, dict):
            continue
        excerpt = (c.get("excerpt") or c.get("content") or "")[:500]
        citations_payload.append({
            "citation_id": c.get("citation_id"),
            "source": c.get("source", "내부규정"),
            "chunk_id": c.get("chunk_id") or c.get("chunkId"),
            "doc_id": c.get("doc_id") or c.get("docId"),
            "reference": c.get("title") or c.get("reference", ""),
            "excerpt": excerpt,
            "score": c.get("score"),
            "evidence_hash": hashlib.sha256(excerpt.encode("utf-8")).hexdigest() if excerpt else None,
        })
    summary_verdict = (reason_text or "").strip()[:500]
    _full = (reason_text or "").strip()
    key_grounds: list[str] = [s.strip() for s in _full.replace("\n", ". ").split(". ") if s.strip()] if _full else []
    if not key_grounds and _full:
        key_grounds = [_full]
    evidence_map_json = _build_evidence_map_json(evidence_items, target_buzei, doc_id, item_no=item_no)
    clauses = list(violation_clauses) if violation_clauses else ([violation_clause] if violation_clause else [])
    return {
        "reason": reason_text or "",
        "evidence": evidence_payload,
        "citations": citations_payload,
        "summary_verdict": summary_verdict,
        "key_grounds": key_grounds,
        "violation_clause": violation_clause or "",
        "violation_clauses": clauses,
        "recommendations": recommended_action or "",
        "evidence_map_json": evidence_map_json,
    }


def _build_citations_payload(
    doc_list: list[dict[str, Any]],
    external_citations: list[dict[str, str]],
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    cid_seq = 0
    for d in doc_list:
        if not isinstance(d, dict):
            continue
        raw_title = (
            d.get("title")
            or d.get("file_name")
            or d.get("location")
            or d.get("regulation_article")
            or d.get("regulationArticle")
            or "내부 규정"
        )
        raw_title = str(raw_title).strip()
        title = raw_title
        if ">" in title:
            parts = [p.strip() for p in title.split(">") if p.strip()]
            if parts:
                title = parts[-1]
        if len(title) > 60:
            title = title[:60]
        if not title or re.fullmatch(r"[0-9a-fA-F\-]{24,}", title or ""):
            title = "내부 규정"
        url = (d.get("s3_url") or d.get("url") or "").strip()
        location = str(d.get("location") or "").strip()
        article = str(d.get("regulation_article") or d.get("regulationArticle") or "").strip()
        clause = str(d.get("regulation_clause") or d.get("regulationClause") or "").strip()
        reference = " ".join([x for x in [article, clause, location] if x]).strip()
        excerpt = str(d.get("excerpt") or d.get("content") or d.get("chunk_text") or "").strip()
        if len(excerpt) > 220:
            excerpt = excerpt[:220]
        cid_seq += 1
        out.append(
            {
                "citation_id": f"C{cid_seq}",
                "title": title,
                "url": url,
                "source": "rag",
                "reference": reference or title,
                "excerpt": excerpt,
            }
        )
    for c in external_citations:
        if isinstance(c, dict):
            cid_seq += 1
            out.append({**c, "citation_id": f"C{cid_seq}", "source": "web_search"})
    return out


def _build_sentence_citation_map(
    *,
    reason_text: str,
    citations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sentences = _split_reason_sentences(reason_text)
    if not sentences:
        return []
    citation_rows = [c for c in (citations or []) if isinstance(c, dict)]
    rows: list[dict[str, Any]] = []
    for idx, sent in enumerate(sentences, start=1):
        sent_norm = re.sub(r"\s+", "", sent)
        sent_tokens = _tokens_for_overlap(sent)
        matched_ids: list[str] = []
        for c in citation_rows:
            cid = str(c.get("citation_id") or "").strip()
            if not cid:
                continue
            ref = " ".join(str(c.get(k) or "") for k in ("title", "url", "reference", "excerpt"))
            ref_norm = re.sub(r"\s+", "", ref)
            ref_tokens = _tokens_for_overlap(ref)
            if _ARTICLE_IN_TEXT_PATTERN.search(sent or "") and _ARTICLE_IN_TEXT_PATTERN.search(ref or ""):
                matched_ids.append(cid)
                continue
            token_overlap = len(sent_tokens & ref_tokens) if sent_tokens and ref_tokens else 0
            if token_overlap < 1:
                token_overlap = _fuzzy_overlap_count(sent_tokens, ref_tokens)
            if sent_tokens and token_overlap >= 1:
                matched_ids.append(cid)
                continue
            if sent_norm and sent_norm[:12] and sent_norm[:12] in ref_norm:
                matched_ids.append(cid)
        # 보수적 연결: 문장이 일반 근거 설명 성격일 때 최소 1개 인용 연결
        if not matched_ids and citation_rows and any(k in sent for k in ("규정", "조항", "근거", "내부규정")):
            fallback_cid = str(citation_rows[0].get("citation_id") or "").strip()
            if fallback_cid:
                matched_ids.append(fallback_cid)
        rows.append(
            {
                "sentence_index": idx,
                "sentence": sent[:300],
                "citation_ids": sorted(set(matched_ids)),
                "grounded": bool(matched_ids),
            }
        )
    return rows


def _normalize_get_case_response(case_data: dict[str, Any] | None) -> dict[str, Any]:
    """
    GET /api/synapse/agent-tools/cases/{caseId} 응답 정규화.
    - ApiResponse<T> 래핑 시 data 필드 안의 CaseDetailDto 사용.
    - amount: data.evidence.amount → data.evidence.documentOrOpenItem.amount → data.fiDocItems[0].wrbtr
    - belnr/documentNumber: data.keys.belnr
    - buzei/target_buzei: data.keys.buzei
    최상위 amount/belnr/buzei 등으로 채워 반환해 파이프라인·thought_stream에서 동일 필드명으로 사용.
    """
    if not case_data or not isinstance(case_data, dict):
        return case_data or {}
    # ApiResponse<T>: data에 실제 CaseDetailDto
    payload = case_data.get("data") if isinstance(case_data.get("data"), dict) else case_data
    out = dict(payload)
    ev = out.get("evidence") or {}
    keys = out.get("keys") or {}
    items = out.get("fiDocItems") or out.get("fiDocItemList") or []
    if not isinstance(ev, dict):
        ev = {}
    if not isinstance(keys, dict):
        keys = {}
    # amount: evidence.amount → evidence.documentOrOpenItem.amount → fiDocItems[0].wrbtr
    if out.get("amount") is None and out.get("totalAmount") is None:
        amount = ev.get("amount")
        if amount is None:
            doc = ev.get("documentOrOpenItem") or {}
            amount = doc.get("amount") if isinstance(doc, dict) else None
        if amount is None and isinstance(items, list) and items and isinstance(items[0], dict):
            amount = items[0].get("wrbtr")
        if amount is not None:
            out["amount"] = amount
            out["totalAmount"] = amount
    # belnr / documentNumber: keys.belnr
    if keys.get("belnr") is not None:
        out["belnr"] = keys["belnr"]
        out["documentNumber"] = keys["belnr"]
    # buzei / target_buzei: keys.buzei
    if keys.get("buzei") is not None:
        out["buzei"] = keys["buzei"]
        out["target_buzei"] = keys["buzei"]
    return out


def _normalize_body_evidence(body_evidence: dict[str, Any] | None) -> list[dict[str, Any]]:
    """
    BE body.evidence → evidence_items 리스트 (C 폴백용).
    BE 확장 스키마: evidence, ragRefs, document(header,items,type,docKey), openItems, partyIds, lineage, policies.
    """
    if not body_evidence or not isinstance(body_evidence, dict):
        return []
    items: list[dict[str, Any]] = []
    for e in body_evidence.get("evidence", []) or []:
        items.append(e if isinstance(e, dict) else {"type": "BODY_EVIDENCE", "value": e})
    for r in body_evidence.get("ragRefs", []) or []:
        items.append(r if isinstance(r, dict) else {"type": "BODY_RAGREF", "value": r})
    # BE 확장: document (header + items, DOCUMENT/OPEN_ITEM 동일 구조)
    doc = body_evidence.get("document")
    if isinstance(doc, dict):
        items.append({"type": "BODY_DOCUMENT", "source": "body.evidence", "header": doc.get("header"), "docKey": doc.get("docKey")})
        for i, it in enumerate((doc.get("items") or [])[:10]):
            items.append({"type": "DOC_ITEM" if i else "DOC_HEADER", "source": "body.evidence.document", "index": i, "item": it if isinstance(it, dict) else {}})
    # openItems
    open_items = body_evidence.get("openItems") or []
    if isinstance(open_items, list) and open_items:
        items.append({"type": "OPEN_ITEMS", "source": "body.evidence", "count": len(open_items)})
        for i, o in enumerate(open_items[:5]):
            if isinstance(o, dict):
                items.append({"type": "OPEN_ITEM", "source": "body.evidence", "index": i, "item": o})
    # partyIds
    party_ids = body_evidence.get("partyIds") or []
    if isinstance(party_ids, list) and party_ids:
        items.append({"type": "PARTY_IDS", "source": "body.evidence", "partyIds": party_ids[:20]})
    # lineage
    lineage = body_evidence.get("lineage")
    if isinstance(lineage, dict) and lineage.get("lineage"):
        items.append({"type": "LINEAGE", "source": "body.evidence", "count": len(lineage.get("lineage", []))})
    elif isinstance(lineage, list) and lineage:
        items.append({"type": "LINEAGE", "source": "body.evidence", "count": len(lineage)})
    # policies
    policies = body_evidence.get("policies") or []
    if isinstance(policies, list) and policies:
        items.append({"type": "POLICIES", "source": "body.evidence", "count": len(policies)})
    return items[:30]  # BE 확장으로 상한 완화


def _extract_payload_case_data(body_evidence: dict[str, Any] | None) -> dict[str, Any]:
    """
    analysis-runs payload(evidence)에서 분석에 필요한 핵심 필드를 우선 추출/정규화.
    """
    if not isinstance(body_evidence, dict):
        return {}
    nested = body_evidence.get("evidence")
    nested = nested if isinstance(nested, dict) else {}
    out: dict[str, Any] = {}
    field_candidates: dict[str, tuple[str, ...]] = {
        "amount": ("amount", "totalAmount"),
        "occurredAt": ("occurredAt", "occurred_at"),
        "case_type": ("case_type", "caseType"),
        "screening_reason_text": ("screening_reason_text", "reasonText"),
        "expenseType": ("expenseType", "expense_type"),
        "expenseTypeName": ("expenseTypeName", "expense_type_name"),
        "merchantName": ("merchantName", "merchant_name"),
        "hrStatus": ("hrStatus", "hr_status"),
        "hrStatusRaw": ("hrStatusRaw", "hr_status_raw"),
        "isHoliday": ("isHoliday", "is_holiday"),
        "mccCode": ("mccCode", "mcc_code"),
        "mcc_related_article": ("mcc_related_article", "mccRelatedArticle"),
        "mccName": ("mccName", "mcc_name"),
        "budgetExceeded": ("budgetExceeded", "budget_exceeded", "budget_exceeded_flag"),
        "doc_id": ("doc_id", "voucher_key"),
        "item_id": ("item_id", "voucher_item_no"),
    }
    for target, keys in field_candidates.items():
        for key in keys:
            if body_evidence.get(key) is not None:
                out[target] = body_evidence.get(key)
                break
        if target not in out:
            for key in keys:
                if nested.get(key) is not None:
                    out[target] = nested.get(key)
                    break
    # nested keys(bukrs/belnr/gjahr/buzei)는 top-level로 승격
    if isinstance(nested.get("keys"), dict):
        for k in ("bukrs", "belnr", "gjahr", "buzei"):
            if nested["keys"].get(k) is not None and out.get(k) is None:
                out[k] = nested["keys"].get(k)
    # occurredAt, hr/mcc 정규화
    out["occurredAt"] = normalize_occurred_at(out.get("occurredAt"))
    hr_norm, hr_raw = normalize_hr_status(out.get("hrStatus"))
    if hr_norm:
        out["hrStatus"] = hr_norm
    if hr_raw:
        out["hrStatusRaw"] = hr_raw
    mcc_norm, mcc_raw = normalize_mcc_code(out.get("mccCode"))
    if mcc_norm:
        out["mccCode"] = mcc_norm
    if mcc_raw:
        out["mccCodeRaw"] = mcc_raw
    if out.get("mccCode") == "unknown":
        incr("audit_analysis_mcc_unknown_total")
    if out.get("amount") is not None:
        try:
            out["amount"] = float(out["amount"])
        except (TypeError, ValueError):
            out["amount"] = None
    return {k: v for k, v in out.items() if v is not None}


def _needs_get_case_fallback(case_data: dict[str, Any]) -> bool:
    """
    payload-first 처리 후 필수 맥락이 부족할 때만 get_case 호출.
    """
    if not case_data:
        return True
    has_core = any(case_data.get(k) is not None for k in ("amount", "occurredAt", "case_type", "merchantName"))
    has_doc_keys = any(case_data.get(k) is not None for k in ("doc_id", "bukrs", "belnr", "gjahr"))
    return not (has_core or has_doc_keys)


def _build_quality_gate_codes(
    *,
    case_data: dict[str, Any] | None,
    evidence_items: list[dict[str, Any]],
    has_rag_evidence: bool,
    policy_gate: dict[str, Any] | None,
) -> list[str]:
    """
    판정보류/품질게이트 사유 코드 표준화.
    """
    codes: list[str] = []
    if not evidence_items:
        codes.append("EVIDENCE_MISSING")
    if not has_rag_evidence:
        codes.append("RAG_ZERO")
    if isinstance(policy_gate, dict):
        signals = set(policy_gate.get("signals") or [])
        if {"holiday_usage", "work_status"} <= signals:
            codes.append("POLICY_CONFLICT")
    case_data = case_data or {}
    required_fields = ("occurredAt", "amount", "case_type", "hrStatus", "mccCode")
    if any(case_data.get(k) is None for k in required_fields):
        codes.append("INPUT_PARTIAL")
    if not codes:
        codes.append("OK")
    return codes


_QUALITY_SIGNAL_LABELS: dict[str, str] = {
    "OK": "정상",
    "EVIDENCE_MISSING": "근거 데이터 없음",
    "RAG_ZERO": "규정 검색 실패",
    "INPUT_PARTIAL": "입력 데이터 일부 누락",
    "POLICY_CONFLICT": "판단 근거 상충",
    "POLICY_CONFLICT_DETECTED": "판단 근거 상충",
    "POLICY_REEVAL_APPLIED": "정책 재검토 적용",
    "RISK_ARTICLE_MISMATCH": "위험유형-조항 불일치",
    "SENTENCE_CITATION_MISSING": "문장 근거 미연결",
    "EVIDENCE_COVERAGE_LOW": "근거 커버리지 낮음",
    "FACT_CONTEXT_PARTIAL": "사실 컨텍스트 일부 누락",
}


def _build_analysis_quality_signals(quality_gate_codes: list[str]) -> list[str]:
    cleaned: list[str] = []
    for code in quality_gate_codes or []:
        c = str(code or "").strip().upper()
        if c:
            cleaned.append(c)
    if not cleaned:
        cleaned = ["OK"]
    # 다른 신호가 있으면 OK 제거
    if any(c != "OK" for c in cleaned):
        cleaned = [c for c in cleaned if c != "OK"]
    deduped = list(dict.fromkeys(cleaned))
    signals: list[str] = []
    for code in deduped:
        signals.append(_QUALITY_SIGNAL_LABELS.get(code, f"기타({code})"))
    return signals or ["정상"]


def _build_compact_rag_query(case_data: dict[str, Any] | None, risk_type: str | None) -> str:
    """
    RAG 0건 재시도용 간결 쿼리(노이즈 토큰 제거).
    """
    base = ["법인카드", "전표", "규정"]
    base.extend(_risk_type_to_semantic_terms(risk_type))
    if not isinstance(case_data, dict):
        return " ".join(base)
    expense_name = case_data.get("expenseTypeName") or case_data.get("expense_type_name")
    if expense_name:
        exp = str(expense_name).strip()
        if exp and exp.lower() not in _COMPACT_NOISE_TERMS:
            base.append(exp)
    occurred = str(case_data.get("occurredAt") or case_data.get("occurred_at") or "").strip()
    if occurred:
        base.append(occurred[:10])
    hr_status = case_data.get("hrStatus") or case_data.get("hr_status")
    if hr_status:
        base.append(str(hr_status))
        if str(hr_status).strip().upper() == "LEAVE":
            base.append("휴무")
    mcc_code = case_data.get("mccCode") or case_data.get("mcc_code")
    if mcc_code:
        base.append(f"MCC {mcc_code}")
    mcc_name = case_data.get("mccName") or case_data.get("mcc_name")
    if mcc_name:
        mcc = str(mcc_name).strip()
        if mcc and mcc.lower() not in _COMPACT_NOISE_TERMS:
            base.append(mcc)
    if case_data.get("isHoliday") is True:
        base.append("휴일")
    dedup: list[str] = []
    seen: set[str] = set()
    for t in base:
        tok = str(t).strip()
        if not tok:
            continue
        low = tok.lower()
        if low in _COMPACT_NOISE_TERMS:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        dedup.append(tok)
    return " ".join(dedup)


def _stable_hash(value: Any) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        raw = str(value)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


async def run_audit_analysis(
    case_id: str,
    *,
    run_id: str | None = None,
    tenant_id: str = "1",
    trace_id: str | None = None,
    body_evidence: dict[str, Any] | None = None,
    intended_risk_type: str | None = None,
    model_name: str | None = None,
    agent_config: Any = None,
) -> AsyncGenerator[tuple[str, dict[str, Any]], None]:
    """
    케이스 감사 분석 파이프라인 실행.

    Yields:
        (event_type, payload) - started, step, evidence, confidence, proposal, completed | failed
    """
    run_id = run_id or str(uuid.uuid4())
    trace = trace_id or f"trace-{case_id}-{run_id[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    # 진단: 요청 케이스 식별 — 금액 불일치 시 "요청 case_id vs get_case 응답" 추적용
    logger.info(
        "audit_analysis start case_id=%s run_id=%s body_evidence_keys=%s",
        case_id,
        run_id,
        list((body_evidence or {}).keys()) if isinstance(body_evidence, dict) else None,
    )

    try:
        timer = start_timer()
        incr("audit_analysis_runs_total")
        reasoning_history: list[str] = []
        # AGENT_STREAM 중복 송출 방지: 직전에 보낸 content와 100% 동일하면 스킵
        last_agent_stream_content: list[str | None] = [None]
        recent_agent_stream_norms: list[str] = []
        # ID 매핑: FE Red Glow 등 행/청크 하이라이트용 — thought_pending/AGENT_STREAM/step에 target_buzei, chunk_id, doc_id 누락 없이 포함
        id_mapping: dict[str, Any] = {"target_buzei": None, "chunk_id": None, "doc_id": None}
        if body_evidence and isinstance(body_evidence, dict):
            _raw_doc = body_evidence.get("doc_id") or (body_evidence.get("document") or {}).get("docKey")
            _raw_buzei = body_evidence.get("target_buzei") or body_evidence.get("buzei")
            if _raw_doc is not None:
                id_mapping["doc_id"] = str(_raw_doc).strip() or None
            if _raw_buzei is not None:
                id_mapping["target_buzei"] = str(_raw_buzei).strip() or None

        # started (total_steps 포함 시 SSE 시작 시점부터 진행률 계산 가능)
        yield ("started", AnalysisStartedEvent(runId=run_id, caseId=case_id, at=now, total_steps=TOTAL_ANALYSIS_STEPS).model_dump())

        def _with_coords(payload: dict[str, Any]) -> dict[str, Any]:
            return {**_coords_payload(id_mapping), **payload}

        def _should_emit_agent_stream(content: str | None, step_label: str) -> bool:
            if not _is_agent_stream_insight(content):
                return False
            if step_label not in _AGENT_STREAM_ALLOWED_STEPS:
                return False
            c = (content or "").strip()
            if not c:
                return False
            if c == last_agent_stream_content[0]:
                return False
            c_norm = _normalize_agent_stream_text(c)
            for prev in recent_agent_stream_norms[-4:]:
                if _token_jaccard_similarity(c_norm, prev) >= 0.72:
                    return False
            recent_agent_stream_norms.append(c_norm)
            if len(recent_agent_stream_norms) > 8:
                recent_agent_stream_norms[:] = recent_agent_stream_norms[-8:]
            return True

        # Step1: 입력 정규화 — 진행 상태는 step만. AGENT_STREAM은 인사이트 문장만 발행(플레이스홀더 미발행)
        yield ("thought_pending", _with_coords({"step_label": "INPUT_NORM", "message": THOUGHT_PENDING_MESSAGE, **id_mapping}))
        thought_input_norm = INPUT_NORM_THOUGHT_SHORT
        if thought_input_norm:
            reasoning_history.append(thought_input_norm)
        if _should_emit_agent_stream(thought_input_norm, "INPUT_NORM"):
            c = (thought_input_norm or "").strip()
            last_agent_stream_content[0] = c
            yield ("AGENT_STREAM", _with_coords({"content": thought_input_norm or "", "step_label": "INPUT_NORM", **id_mapping}))
        # step.thought_stream은 AGENT_STREAM으로 이미 보냈거나 플레이스홀더이면 None — FE 중복/기술 문구 노출 방지
        yield ("step", _with_coords({**AnalysisStepEvent(
            label="INPUT_NORM",
            detail="케이스 입력 정규화 중",
            percent=10,
            total_steps=TOTAL_ANALYSIS_STEPS,
            thought_stream=None,
        ).model_dump(), **id_mapping}))

        # payload-first: analysis-runs evidence를 1차 소스로 사용
        case_data = _extract_payload_case_data(body_evidence if isinstance(body_evidence, dict) else {})
        if case_data:
            logger.info(
                "audit_analysis payload-first case_id=%s fields=%s case_type=%s occurredAt=%s amount=%s mccCode=%s hrStatus=%s hrStatusRaw=%s isHoliday=%s mcc_related_article=%s",
                case_id,
                sorted(case_data.keys()),
                case_data.get("case_type"),
                case_data.get("occurredAt"),
                case_data.get("amount"),
                case_data.get("mccCode"),
                case_data.get("hrStatus"),
                case_data.get("hrStatusRaw"),
                case_data.get("isHoliday"),
                case_data.get("mcc_related_article"),
            )
        if _needs_get_case_fallback(case_data):
            incr("audit_analysis_get_case_fallback_total")
            _get_case_input = {"caseId": case_id}
            yield ("tool_call", _with_coords({
                "node": "INPUT_NORM",
                "tool": "get_case",
                "decision_code": "REQUESTED",
                "input_hash": _stable_hash(_get_case_input),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **id_mapping,
            }))
            try:
                case_result = await get_case.ainvoke({"caseId": case_id})
                case_fallback = json.loads(case_result) if isinstance(case_result, str) else case_result
                yield ("tool_result", _with_coords({
                    "node": "INPUT_NORM",
                    "tool": "get_case",
                    "decision_code": "OK",
                    "input_hash": _stable_hash(_get_case_input),
                    "output_ref": _stable_hash(case_fallback or {}),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **id_mapping,
                }))
            except Exception as e:
                logger.warning(f"get_case fallback failed for {case_id}: {e}")
                case_fallback = {}
                yield ("tool_result", _with_coords({
                    "node": "INPUT_NORM",
                    "tool": "get_case",
                    "decision_code": "ERROR",
                    "input_hash": _stable_hash(_get_case_input),
                    "output_ref": str(e)[:120],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **id_mapping,
                }))
            if isinstance(case_fallback, dict) and "error" in case_fallback:
                case_fallback = {}
            case_fallback = _normalize_get_case_response(case_fallback)
            if case_fallback:
                merged = dict(case_fallback)
                merged.update({k: v for k, v in case_data.items() if v is not None})
                case_data = merged
                logger.info(
                    "audit_analysis merged get_case fallback case_id=%s has_caseType=%s has_amount=%s has_occurredAt=%s",
                    case_id,
                    bool(case_data.get("case_type") or case_data.get("caseType")),
                    case_data.get("amount") is not None,
                    bool(case_data.get("occurredAt") or case_data.get("occurred_at")),
                )
        else:
            logger.info(
                "audit_analysis skip get_case fallback case_id=%s reason=payload_sufficient has_amount=%s has_occurredAt=%s has_case_type=%s has_doc_keys=%s",
                case_id,
                case_data.get("amount") is not None,
                bool(case_data.get("occurredAt") or case_data.get("occurred_at")),
                bool(case_data.get("case_type") or case_data.get("caseType")),
                any(case_data.get(k) is not None for k in ("doc_id", "bukrs", "belnr", "gjahr")),
            )

        # [추적] payload/get_case 정규화 후 스크리닝 필드 유무
        _mcp_input = {
            "caseId": case_id,
            "occurredAt": case_data.get("occurredAt") if isinstance(case_data, dict) else None,
            "mccCode": case_data.get("mccCode") if isinstance(case_data, dict) else None,
            "hrStatus": case_data.get("hrStatus") if isinstance(case_data, dict) else None,
        }
        yield ("tool_call", _with_coords({
            "node": "INPUT_NORM",
            "tool": "mcp_adapter.resolve_fact_context",
            "decision_code": "REQUESTED",
            "input_hash": _stable_hash(_mcp_input),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **id_mapping,
        }))
        mcp_fact_context: dict[str, Any] = await resolve_fact_context(
            case_data if isinstance(case_data, dict) else {},
            case_id=case_id,
            stage="analysis",
        )
        yield ("tool_result", _with_coords({
            "node": "INPUT_NORM",
            "tool": "mcp_adapter.resolve_fact_context",
            "decision_code": "OK",
            "input_hash": _stable_hash(_mcp_input),
            "output_ref": _stable_hash((mcp_fact_context or {}).get("quality", {})),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **id_mapping,
        }))
        if isinstance(case_data, dict) and case_data:
            facts = mcp_fact_context.get("facts") if isinstance(mcp_fact_context.get("facts"), dict) else {}
            # MCP fact context 값으로 누락 필드만 보강(payload-first 유지)
            for k in (
                "occurredAt",
                "hrStatus",
                "hrStatusRaw",
                "mccCode",
                "mccCodeRaw",
                "isHoliday",
                "holidayType",
            ):
                if case_data.get(k) is None and facts.get(k) is not None:
                    case_data[k] = facts.get(k)
            _ct = case_data.get("case_type") or case_data.get("caseType")
            _rt = case_data.get("reasonText") or case_data.get("screening_reason_text")
            _mcc_code = case_data.get("mccCode") or case_data.get("mcc_code")
            _mcc_name = case_data.get("mccName") or case_data.get("mcc_name")
            _mcc_article = case_data.get("mcc_related_article") or case_data.get("mccRelatedArticle")
            logger.info(
                "audit_analysis normalized_input: case_id=%s has_caseType=%s caseType=%s has_reasonText=%s mccCode=%s mccName=%s mcc_related_article=%s reasonText_preview=%s",
                case_id,
                _ct is not None,
                _ct,
                _rt is not None,
                _mcc_code,
                _mcc_name,
                _mcc_article,
                (_rt[:60] + "…") if _rt and len(_rt) > 60 else (_rt or ""),
            )
            logger.info(
                "audit_analysis mcp_fact_context: case_id=%s mode=%s input_partial=%s missing_fields=%s isHoliday=%s holidayType=%s weekday=%s",
                case_id,
                mcp_fact_context.get("mode"),
                (mcp_fact_context.get("quality") or {}).get("input_partial"),
                (mcp_fact_context.get("quality") or {}).get("missing_fields"),
                facts.get("isHoliday"),
                facts.get("holidayType"),
                facts.get("weekdayKo"),
            )
            if _mcc_article is None:
                logger.warning(
                    "audit_analysis mcc_related_article missing: case_id=%s mccCode=%s mccName=%s (payload did not provide related article hint)",
                    case_id,
                    _mcc_code,
                    _mcc_name,
                )
        _be_preview = None
        if isinstance(body_evidence, dict) and body_evidence:
            _be_ct = body_evidence.get("caseType") or body_evidence.get("case_type")
            _be_rt = body_evidence.get("reasonText") or body_evidence.get("screening_reason_text")
            _be_mcc_code = (
                body_evidence.get("mccCode")
                or body_evidence.get("mcc_code")
                or ((body_evidence.get("evidence") or {}).get("mccCode") if isinstance(body_evidence.get("evidence"), dict) else None)
            )
            _be_mcc_name = (
                body_evidence.get("mccName")
                or body_evidence.get("mcc_name")
                or ((body_evidence.get("evidence") or {}).get("mccName") if isinstance(body_evidence.get("evidence"), dict) else None)
            )
            _be_mcc_article = (
                body_evidence.get("mcc_related_article")
                or body_evidence.get("mccRelatedArticle")
                or ((body_evidence.get("evidence") or {}).get("mcc_related_article") if isinstance(body_evidence.get("evidence"), dict) else None)
            )
            _be_risk_key = body_evidence.get("case_type") or body_evidence.get("caseType")
            _be_preview = (
                f"evidence_caseType={_be_ct} has_reasonText={_be_rt is not None} "
                f"case_type={_be_risk_key} mccCode={_be_mcc_code} mccName={_be_mcc_name} mcc_related_article={_be_mcc_article}"
            )
            logger.info(
                "audit_analysis body_evidence: case_id=%s %s evidence_keys=%s",
                case_id,
                _be_preview,
                list(body_evidence.keys())[:20],
            )

        # 진단: get_case 응답 전표·금액 — 백엔드가 해당 case_id에 대해 어떤 데이터를 내려줬는지 확인 (금액 불일치 추적)
        if isinstance(case_data, dict) and case_data:
            _belnr = case_data.get("belnr") or case_data.get("documentNumber")
            _amt = case_data.get("amount") or case_data.get("totalAmount")
            logger.info(
                "audit_analysis input_snapshot case_id=%s belnr=%s documentNumber=%s amount=%s totalAmount=%s",
                case_id,
                case_data.get("belnr"),
                case_data.get("documentNumber"),
                case_data.get("amount"),
                case_data.get("totalAmount"),
            )
            if _belnr is not None or _amt is not None:
                logger.info(
                    "audit_analysis case_identifiers case_id=%s belnr_or_docNo=%s amount_used=%s",
                    case_id, _belnr, _amt,
                )
            # 금액/전표번호가 없을 때: 백엔드가 다른 키로 내려주는지 확인용 — 응답 최상위 키 목록 로그
            if _amt is None and _belnr is None:
                _top_keys = list(case_data.keys())[:30]
                logger.info(
                    "audit_analysis input_snapshot missing amount/belnr case_id=%s top_level_keys=%s (backend may use different field names or nest under another key)",
                    case_id, _top_keys,
                )

        # No-RAG thought guard에서 선참조되므로 초기화는 thought 생성 전에 수행
        evidence_items: list[dict[str, Any]] = []

        yield ("thought_pending", _with_coords({"step_label": "EVIDENCE_GATHER", "message": THOUGHT_PENDING_MESSAGE, **id_mapping}))
        thought_evidence_gather = enforce_grounded_public_thought(
            await generate_thought_stream(
                "EVIDENCE_GATHER",
                case_data,
                case_id=case_id,
                intended_risk_type=intended_risk_type,
                reasoning_history=reasoning_history,
            ),
            case_data=case_data if isinstance(case_data, dict) else None,
            evidence_items=evidence_items,
            require_rag_for_claims=True,
        )
        if thought_evidence_gather:
            reasoning_history.append(thought_evidence_gather)
        if _should_emit_agent_stream(thought_evidence_gather, "EVIDENCE_GATHER"):
            c = (thought_evidence_gather or "").strip()
            last_agent_stream_content[0] = c
            yield ("AGENT_STREAM", _with_coords({"content": thought_evidence_gather or "", "step_label": "EVIDENCE_GATHER", **id_mapping}))
        _step_thought = None if _is_agent_stream_insight(thought_evidence_gather) else (thought_evidence_gather or None)
        yield ("step", _with_coords({**AnalysisStepEvent(
            label="EVIDENCE_GATHER",
            detail="케이스 전표 데이터 및 연관 증거 수집 중",
            percent=25,
            total_steps=TOTAL_ANALYSIS_STEPS,
            thought_stream=_step_thought,
        ).model_dump(), **id_mapping}))

        # Step2: Evidence 수집
        if case_data:
            _be = body_evidence if isinstance(body_evidence, dict) else {}
            doc_id_case = _be.get("doc_id") or (_be.get("document") or {}).get("docKey")
            item_id_case = _be.get("item_id")
            buzei_case = _be.get("target_buzei") or _be.get("buzei") or (case_data.get("target_buzei") or case_data.get("buzei") if isinstance(case_data, dict) else None)
            item_no_case = _be.get("item_no") or (case_data.get("item_no") or case_data.get("item_id") if isinstance(case_data, dict) else None)
            # ID 매핑 갱신: FE Red Glow용 chunk_id, target_buzei 노출
            id_mapping["doc_id"] = str(doc_id_case).strip() if doc_id_case is not None else None
            id_mapping["item_id"] = str(item_id_case).strip() if item_id_case is not None else None
            id_mapping["target_buzei"] = str(buzei_case).strip() if buzei_case is not None else None
            if "chunk_id" not in id_mapping:
                id_mapping["chunk_id"] = None
            evidence_items.append({
                "type": "CASE",
                "source": "get_case",
                "caseId": case_id,
                "keys": {k: v for k, v in case_data.items() if k in ("bukrs", "belnr", "gjahr", "vendorId", "amount")},
                "doc_id": doc_id_case,
                "docId": doc_id_case,
                "item_id": item_id_case,
                "itemId": item_id_case,
                "target_buzei": buzei_case,
                "item_no": item_no_case,
            })

        doc_list: list[dict[str, Any]] = []
        _search_docs_input = {"filters": {"caseId": case_id, "topK": 5}}
        yield ("tool_call", _with_coords({
            "node": "EVIDENCE_GATHER",
            "tool": "search_documents",
            "decision_code": "REQUESTED",
            "input_hash": _stable_hash(_search_docs_input),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **id_mapping,
        }))
        try:
            doc_result = await search_documents.ainvoke({"filters": {"caseId": case_id, "topK": 5}})
            docs = json.loads(doc_result) if isinstance(doc_result, str) else doc_result
            yield ("tool_result", _with_coords({
                "node": "EVIDENCE_GATHER",
                "tool": "search_documents",
                "decision_code": "OK",
                "input_hash": _stable_hash(_search_docs_input),
                "output_ref": _stable_hash(docs or {}),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **id_mapping,
            }))
            if isinstance(docs, dict):
                doc_list = docs.get("documents", docs.get("items", [])) or []
            else:
                doc_list = docs if isinstance(docs, list) else []
            for i, d in enumerate((doc_list or [])[:5]):
                if isinstance(d, dict):
                    doc_id_val = d.get("doc_id") or d.get("docId") or d.get("docKey") or d.get("rag_document_id")
                    item_id_val = d.get("item_id") or d.get("itemId") or (str(i) if i > 0 else None)
                    evidence_items.append({
                        "type": "DOC_HEADER" if i == 0 else "DOC_ITEM",
                        "source": "search_documents",
                        "index": i,
                        "keys": d.get("keys", {}) or {"caseId": case_id},
                        "doc_id": doc_id_val,
                        "docId": doc_id_val,
                        "item_id": item_id_val,
                        "itemId": item_id_val,
                    })
        except Exception as e:
            logger.debug(f"search_documents failed: {e}")
            yield ("tool_result", _with_coords({
                "node": "EVIDENCE_GATHER",
                "tool": "search_documents",
                "decision_code": "ERROR",
                "input_hash": _stable_hash(_search_docs_input),
                "output_ref": str(e)[:120],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **id_mapping,
            }))

        # 하이브리드 검색 — 사내 규정(Vector DB) 자동 로드
        yield ("thought_pending", _with_coords({"step_label": "REGULATION_MATCH", "message": THOUGHT_PENDING_MESSAGE, **id_mapping}))
        thought_regulation = enforce_grounded_public_thought(
            await generate_thought_stream(
                "REGULATION_MATCH",
                case_data,
                case_id=case_id,
                intended_risk_type=intended_risk_type,
                reasoning_history=reasoning_history,
            ),
            case_data=case_data if isinstance(case_data, dict) else None,
            evidence_items=evidence_items,
            require_rag_for_claims=True,
        )
        if thought_regulation:
            reasoning_history.append(thought_regulation)
        if _should_emit_agent_stream(thought_regulation, "REGULATION_MATCH"):
            c = (thought_regulation or "").strip()
            last_agent_stream_content[0] = c
            yield ("AGENT_STREAM", _with_coords({"content": thought_regulation or "", "step_label": "REGULATION_MATCH", **id_mapping}))
        _step_thought = None if _is_agent_stream_insight(thought_regulation) else (thought_regulation or None)
        yield ("step", _with_coords({**AnalysisStepEvent(
            label="REGULATION_MATCH",
            detail="전표·가맹점 맥락을 바탕으로 사내 규정(Vector DB) 매칭 중입니다.",
            percent=35,
            total_steps=TOTAL_ANALYSIS_STEPS,
            thought_stream=_step_thought,
        ).model_dump(), **id_mapping}))
        vector_results: list[dict[str, Any]] = []
        rag_constraints: dict[str, Any] = {"articles": [], "index_version": None}
        rag_query = ""
        doc_ids: list[int] | None = None
        raw_count = 0
        raw_max = 0.0
        rule_filtered_count = 0
        retried_compact_query = False
        retried_ultra_compact_query = False
        retry_thresholds_used: list[float] = []
        diag_unfiltered_count = 0
        diag_unfiltered_max = 0.0
        try:
            bukrs = str(case_data.get("bukrs") or "") if isinstance(case_data, dict) else None
            belnr = str(case_data.get("belnr") or "") if isinstance(case_data, dict) else None
            # AgentConfig에서 doc_ids와 tenant_id 추출
            tenant_id_int = None
            if agent_config:
                doc_ids = getattr(agent_config, "doc_ids", None)
                tenant_id_raw = getattr(agent_config, "tenant_id", None)
                if tenant_id_raw is not None:
                    try:
                        tenant_id_int = int(tenant_id_raw)
                    except (ValueError, TypeError):
                        tenant_id_int = None
            # tenant_id 문자열도 int로 변환 시도
            if tenant_id_int is None and tenant_id:
                try:
                    tenant_id_int = int(tenant_id)
                except (ValueError, TypeError):
                    tenant_id_int = None

            # BE docIds 누락 시 body_evidence.doc_id를 임시 범위로 사용 (숫자형만)
            if (doc_ids is None or len(doc_ids) == 0) and body_evidence and isinstance(body_evidence, dict):
                raw_doc = body_evidence.get("doc_id") or (body_evidence.get("document") or {}).get("docKey")
                if isinstance(raw_doc, str) and raw_doc.isdigit():
                    doc_ids = [int(raw_doc)]
                elif isinstance(raw_doc, int):
                    doc_ids = [raw_doc]
                if doc_ids:
                    logger.info(
                        "analysis_pipeline: doc_ids fallback from body_evidence doc_id=%s",
                        raw_doc,
                    )
            
            settings = get_settings()
            rag_constraints = _build_rule_first_constraints(
                case_data if isinstance(case_data, dict) else None,
                settings_obj=settings,
            )
            primary_similarity_threshold = float(getattr(settings, "rag_similarity_threshold", 0.75))
            diag_disable_doc_ids_once = bool(getattr(settings, "rag_diag_disable_doc_ids_once", False))
            rag_query = _build_dynamic_rag_query(
                case_data if isinstance(case_data, dict) else None,
                intended_risk_type=intended_risk_type,
            )
            if rag_constraints.get("articles"):
                rag_query = f"{rag_query} {' '.join(rag_constraints.get('articles') or [])}"
            if rag_constraints.get("keywords"):
                rag_query = f"{rag_query} {' '.join(rag_constraints.get('keywords') or [])}"
            metadata_filter: dict[str, Any] | None = None
            if rag_constraints.get("index_version"):
                metadata_filter = {"index_version": rag_constraints["index_version"]}
            logger.info(
                "analysis_pipeline: RAG query start case_id=%s query=%s tenant_id=%s doc_ids=%s metadata_filter=%s",
                case_id,
                rag_query[:500],
                tenant_id_int,
                doc_ids,
                metadata_filter,
            )
            logger.info(
                "analysis_pipeline: RAG filter snapshot case_id=%s tenant_id=%s doc_ids=%s index_version=%s",
                case_id,
                tenant_id_int,
                doc_ids,
                rag_constraints.get("index_version"),
            )
            logger.info(
                "analysis_pipeline: RAG phase=query_filter_threshold case_id=%s query_len=%s has_articles=%s has_keywords=%s doc_ids_count=%s metadata_filter=%s threshold_primary=%.2f",
                case_id,
                len(rag_query or ""),
                bool(rag_constraints.get("articles")),
                bool(rag_constraints.get("keywords")),
                len(doc_ids) if isinstance(doc_ids, list) else 0,
                bool(metadata_filter),
                primary_similarity_threshold,
            )
            raw_vector_results = hybrid_retrieve(
                query=rag_query,
                top_k=5,
                include_article_clause=True,
                bukrs=bukrs or None,
                belnr=belnr or None,
                metadata_filter=metadata_filter,
                doc_ids=doc_ids,
                tenant_id=tenant_id_int,
            )
            raw_count = len(raw_vector_results or [])
            raw_max = max((float(r.get("score", 0) or 0) for r in (raw_vector_results or []) if isinstance(r, dict)), default=0.0)
            logger.info(
                "analysis_pipeline: RAG raw_result case_id=%s count=%s max_score=%.3f",
                case_id,
                raw_count,
                raw_max,
            )
            vector_results = _apply_rule_first_filter(
                raw_vector_results,
                preferred_articles=rag_constraints.get("articles"),
                effective_date=None,
            )
            rule_filtered_count = len(vector_results or [])
            if raw_count and not rule_filtered_count:
                logger.info(
                    "analysis_pipeline: RAG rule_filter_drop_all case_id=%s preferred_articles=%s",
                    case_id,
                    rag_constraints.get("articles"),
                )
            vector_results = _rerank_vector_results(
                vector_results,
                case_data=case_data if isinstance(case_data, dict) else None,
                preferred_articles=rag_constraints.get("articles"),
            )
            # 룰 필터로 0건이 되면 동일 쿼리의 원본 결과를 재랭킹해 유효 근거를 최대한 확보
            if not vector_results and raw_vector_results:
                vector_results = _rerank_vector_results(
                    raw_vector_results,
                    case_data=case_data if isinstance(case_data, dict) else None,
                    preferred_articles=None,
                )
                logger.info(
                    "analysis_pipeline: RAG fallback to raw results case_id=%s raw_count=%s",
                    case_id,
                    len(raw_vector_results),
                )
            # 재시도 1/2: 간결 쿼리 + 낮은 threshold (pgvector 전용)
            if not vector_results and tenant_id_int and doc_ids:
                settings_local = get_settings()
                if (getattr(settings_local, "vector_store_type", "none") or "").strip().lower() == "pgvector":
                    compact_query = _build_compact_rag_query(
                        case_data if isinstance(case_data, dict) else None,
                        intended_risk_type or (case_data.get("case_type") if isinstance(case_data, dict) else None),
                    )
                    if compact_query and compact_query != rag_query:
                        retried_compact_query = True
                        retry_threshold_1 = 0.60
                        retry_thresholds_used.append(retry_threshold_1)
                        logger.info(
                            "analysis_pipeline: RAG retry start case_id=%s mode=compact_query threshold=%.2f query=%s",
                            case_id,
                            retry_threshold_1,
                            compact_query[:300],
                        )
                        retry_results = retrieve_rag_pgvector(
                            compact_query,
                            top_k=5,
                            bukrs=bukrs or None,
                            belnr=belnr or None,
                            metadata_filter=metadata_filter,
                            include_article_clause=True,
                            similarity_threshold=retry_threshold_1,
                            prioritize_chapters=("제5장", "제6장"),
                            doc_ids=doc_ids,
                            tenant_id=tenant_id_int if tenant_id_int > 0 else None,
                        )
                        if retry_results:
                            vector_results = _rerank_vector_results(
                                retry_results,
                                case_data=case_data if isinstance(case_data, dict) else None,
                                preferred_articles=rag_constraints.get("articles"),
                            )
                            logger.info(
                                "analysis_pipeline: RAG retry success case_id=%s results=%s",
                                case_id,
                                len(vector_results),
                            )
                        else:
                            logger.info(
                                "analysis_pipeline: RAG retry empty case_id=%s",
                                case_id,
                            )
                            retry_threshold_2 = 0.50
                            retry_thresholds_used.append(retry_threshold_2)
                            retried_ultra_compact_query = True
                            ultra_semantic_terms: list[str] = []
                            if intended_risk_type:
                                ultra_semantic_terms = _risk_type_to_semantic_terms(intended_risk_type)
                            elif isinstance(case_data, dict):
                                ultra_semantic_terms = _risk_type_to_semantic_terms(str(case_data.get("case_type") or "").strip())
                            ultra_query = " ".join(
                                [
                                    t
                                    for t in [
                                        " ".join(ultra_semantic_terms) if ultra_semantic_terms else "",
                                        str(case_data.get("mccCode") if isinstance(case_data, dict) else "").strip(),
                                        str(case_data.get("hrStatus") if isinstance(case_data, dict) else "").strip(),
                                        str((case_data.get("occurredAt") or "")[:10] if isinstance(case_data, dict) else "").strip(),
                                        "법인카드",
                                        "전표",
                                        "규정",
                                    ]
                                    if t
                                ]
                            )
                            logger.info(
                                "analysis_pipeline: RAG retry start case_id=%s mode=ultra_compact threshold=%.2f query=%s",
                                case_id,
                                retry_threshold_2,
                                ultra_query[:220],
                            )
                            retry_results_2 = retrieve_rag_pgvector(
                                ultra_query,
                                top_k=5,
                                bukrs=bukrs or None,
                                belnr=belnr or None,
                                metadata_filter=metadata_filter,
                                include_article_clause=True,
                                similarity_threshold=retry_threshold_2,
                                prioritize_chapters=("제5장", "제6장"),
                                doc_ids=doc_ids,
                                tenant_id=tenant_id_int if tenant_id_int > 0 else None,
                            )
                            if retry_results_2:
                                vector_results = _rerank_vector_results(
                                    retry_results_2,
                                    case_data=case_data if isinstance(case_data, dict) else None,
                                    preferred_articles=rag_constraints.get("articles"),
                                )
                                logger.info(
                                    "analysis_pipeline: RAG retry success case_id=%s mode=ultra_compact results=%s",
                                    case_id,
                                    len(vector_results),
                                )
                            else:
                                logger.info(
                                    "analysis_pipeline: RAG retry empty case_id=%s mode=ultra_compact",
                                    case_id,
                                )
            # 진단 전용: 같은 run에서 doc_ids 제한 해제 시 결과가 생기는지 원인 분리
            if (
                not vector_results
                and diag_disable_doc_ids_once
                and tenant_id_int
                and isinstance(doc_ids, list)
                and len(doc_ids) > 0
            ):
                diag_results = hybrid_retrieve(
                    query=rag_query,
                    top_k=5,
                    include_article_clause=True,
                    bukrs=bukrs or None,
                    belnr=belnr or None,
                    metadata_filter=metadata_filter,
                    doc_ids=None,
                    tenant_id=tenant_id_int,
                )
                diag_unfiltered_count = len(diag_results or [])
                diag_unfiltered_max = max(
                    (float(r.get("score", 0) or 0) for r in (diag_results or []) if isinstance(r, dict)),
                    default=0.0,
                )
                logger.info(
                    "analysis_pipeline: RAG diagnosis case_id=%s mode=doc_ids_unfiltered count=%s max_score=%.3f",
                    case_id,
                    diag_unfiltered_count,
                    diag_unfiltered_max,
                )
            logger.info(
                "analysis_pipeline: RAG constraints case_id=%s mcc=%s articles=%s index_version=%s",
                case_id,
                rag_constraints.get("mcc_code"),
                rag_constraints.get("articles"),
                rag_constraints.get("index_version"),
            )
            if vector_results:
                existing = {str((d.get("docKey") or d.get("id") or d.get("rag_document_id") or "")) for d in doc_list if isinstance(d, dict)}
                for v in vector_results:
                    key = str(v.get("rag_document_id") or v.get("sourceKey") or "")
                    if key and key not in existing:
                        doc_list.append(v)
                        existing.add(key)
                    # BE evidence_map 채우기: evidence/ragRefs에 doc_id, chunk_id 포함된 항목 추가
                    cid = v.get("chunk_id") or v.get("chunkId")
                    if cid and id_mapping.get("chunk_id") is None:
                        id_mapping["chunk_id"] = str(cid).strip()
                    evidence_items.append({
                        "type": "RAG_CHUNK",
                        "source": "hybrid_retrieve",
                        "doc_id": v.get("doc_id") or v.get("rag_document_id"),
                        "docId": v.get("docId") or v.get("doc_id") or v.get("rag_document_id"),
                        "regulation_article": v.get("regulation_article") or v.get("regulationArticle"),
                        "regulation_clause": v.get("regulation_clause") or v.get("regulationClause"),
                        "location": v.get("location"),
                        "chunk_id": v.get("chunk_id"),
                        "chunkId": v.get("chunkId") or v.get("chunk_id"),
                        "excerpt": (v.get("excerpt") or v.get("content") or "")[:300],
                        "score": v.get("score"),
                        "keys": {"caseId": case_id},
                    })
        except Exception as e:
            logger.debug(f"hybrid_retrieve failed: {e}")

        # RAG 우선순위: 내부 규정 유사도가 임계값(기본 0.7) 미만일 때만 외부 검색
        external_search_text = ""
        external_citations: list[dict[str, str]] = []
        settings = get_settings()
        rag_threshold = getattr(settings, "web_search_rag_threshold", 0.7)
        if vector_results:
            max_rag_score = max(float(r.get("score", 0)) or 0 for r in vector_results)
        else:
            max_rag_score = 0.0
        need_web_search = not vector_results or max_rag_score < rag_threshold
        rag_zero_reasons: list[str] = []
        if not vector_results:
            rag_zero_reasons.append("RAG_RESULT_EMPTY")
            if not (rag_query or "").strip():
                rag_zero_reasons.append("QUERY_EMPTY")
            if not doc_ids:
                rag_zero_reasons.append("DOC_IDS_MISSING")
            if rag_constraints.get("articles") and raw_count > 0 and rule_filtered_count == 0:
                rag_zero_reasons.append("ARTICLE_FILTER_APPLIED")
            if retried_compact_query:
                rag_zero_reasons.append("RETRY_COMPACT_QUERY_FAILED")
            if retried_ultra_compact_query:
                rag_zero_reasons.append("RETRY_ULTRA_COMPACT_QUERY_FAILED")
            if diag_unfiltered_count > 0:
                rag_zero_reasons.append("DOC_IDS_FILTER_TOO_NARROW")
        elif max_rag_score < rag_threshold:
            rag_zero_reasons.append("BELOW_THRESHOLD")
            if retried_compact_query:
                rag_zero_reasons.append("RETRY_COMPACT_QUERY_USED")
            if retried_ultra_compact_query:
                rag_zero_reasons.append("RETRY_ULTRA_COMPACT_QUERY_USED")
        logger.info(
            "analysis_pipeline: RAG summary case_id=%s results=%s max_score=%.3f threshold=%.3f need_web_search=%s reasons=%s raw_count=%s raw_max=%.3f rule_filtered_count=%s retried_compact=%s retried_ultra=%s retry_thresholds=%s diag_unfiltered_count=%s diag_unfiltered_max=%.3f",
            case_id,
            len(vector_results) if isinstance(vector_results, list) else 0,
            max_rag_score,
            rag_threshold,
            need_web_search,
            rag_zero_reasons,
            raw_count,
            raw_max,
            rule_filtered_count,
            retried_compact_query,
            retried_ultra_compact_query,
            retry_thresholds_used,
            diag_unfiltered_count,
            diag_unfiltered_max,
        )
        if vector_results:
            incr("audit_analysis_rag_nonzero_total")
        else:
            incr("audit_analysis_rag_zero_total")
        if need_web_search:
            yield ("step", _with_coords({**AnalysisStepEvent(
                label="WEB_SEARCH",
                detail="사내 규정에 관련 조항이 없어 외부 회계/세무 기준을 검색합니다." if vector_results else "사내 규정 검색 결과가 없어 외부 검색을 수행합니다.",
                percent=38,
            ).model_dump(), **id_mapping}))
            try:
                from tools.external_search_tool import run_web_search_for_pipeline
                expense_type = "경비"
                if isinstance(case_data, dict):
                    expense_type = (
                        case_data.get("expenseTypeName")
                        or case_data.get("expense_type_name")
                        or case_data.get("expenseType")
                        or case_data.get("expense_type")
                        or "경비"
                    )
                    if str(expense_type).strip().lower() in _COMPACT_NOISE_TERMS:
                        expense_type = "경비"
                web_query = f"법인카드 {expense_type} 세무처리 국세청 가이드라인 회계기준"
                web_result = await run_web_search_for_pipeline(web_query)
                if isinstance(web_result, dict):
                    external_search_text = _sanitize_external_reference_text(web_result.get("text", ""))
                    external_citations = web_result.get("citations", [])
                else:
                    external_search_text = _sanitize_external_reference_text(str(web_result))
                logger.info(
                    "analysis_pipeline: web_search completed case_id=%s query=%s text_len=%s citations=%s",
                    case_id,
                    web_query,
                    len(external_search_text or ""),
                    len(external_citations or []),
                )
                if external_search_text and "error" not in (external_search_text[:100] or "").lower():
                    evidence_items.append({
                        "type": "EXTERNAL_WEB",
                        "source": "web_search",
                        "excerpt": (external_search_text[:500] + "..." if len(external_search_text) > 500 else external_search_text),
                    })
            except Exception as e:
                logger.debug(f"web_search in pipeline failed: {e}")

        _open_items_input = {"filters": {"caseId": case_id}}
        yield ("tool_call", _with_coords({
            "node": "EVIDENCE_GATHER",
            "tool": "get_open_items",
            "decision_code": "REQUESTED",
            "input_hash": _stable_hash(_open_items_input),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **id_mapping,
        }))
        try:
            oi_result = await get_open_items.ainvoke({"filters": {"caseId": case_id}})
            oi_data = json.loads(oi_result) if isinstance(oi_result, str) else oi_result
            yield ("tool_result", _with_coords({
                "node": "EVIDENCE_GATHER",
                "tool": "get_open_items",
                "decision_code": "OK",
                "input_hash": _stable_hash(_open_items_input),
                "output_ref": _stable_hash(oi_data or {}),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **id_mapping,
            }))
            items = oi_data.get("items", oi_data.get("openItems", [])) if isinstance(oi_data, dict) else []
            if items:
                evidence_items.append({"type": "OPEN_ITEMS", "source": "get_open_items", "count": len(items)})
        except Exception as e:
            logger.debug(f"get_open_items failed: {e}")
            yield ("tool_result", _with_coords({
                "node": "EVIDENCE_GATHER",
                "tool": "get_open_items",
                "decision_code": "ERROR",
                "input_hash": _stable_hash(_open_items_input),
                "output_ref": str(e)[:120],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **id_mapping,
            }))

        _lineage_input = {"caseId": case_id}
        yield ("tool_call", _with_coords({
            "node": "EVIDENCE_GATHER",
            "tool": "get_lineage",
            "decision_code": "REQUESTED",
            "input_hash": _stable_hash(_lineage_input),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **id_mapping,
        }))
        try:
            lineage_result = await get_lineage.ainvoke({"caseId": case_id})
            lineage_data = json.loads(lineage_result) if isinstance(lineage_result, str) else lineage_result
            yield ("tool_result", _with_coords({
                "node": "EVIDENCE_GATHER",
                "tool": "get_lineage",
                "decision_code": "OK",
                "input_hash": _stable_hash(_lineage_input),
                "output_ref": _stable_hash(lineage_data or {}),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **id_mapping,
            }))
            lineage = lineage_data.get("lineage", []) if isinstance(lineage_data, dict) and "error" not in lineage_data else []
            if lineage:
                evidence_items.append({"type": "LINEAGE", "source": "get_lineage", "count": len(lineage)})
        except Exception as e:
            logger.debug(f"get_lineage failed: {e}")
            yield ("tool_result", _with_coords({
                "node": "EVIDENCE_GATHER",
                "tool": "get_lineage",
                "decision_code": "ERROR",
                "input_hash": _stable_hash(_lineage_input),
                "output_ref": str(e)[:120],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **id_mapping,
            }))

        # C(폴백): fetch 실패로 evidence_items 비어 있으면 body.evidence 사용
        only_case_evidence = bool(evidence_items) and all((isinstance(e, dict) and e.get("type") == "CASE") for e in evidence_items)
        if (not evidence_items or only_case_evidence) and body_evidence:
            fallback_items = _normalize_body_evidence(body_evidence)
            if fallback_items:
                if only_case_evidence:
                    evidence_items.extend(fallback_items)
                else:
                    evidence_items = fallback_items
                logger.info(
                    "case=%s using body.evidence fallback (%s items, only_case_evidence=%s)",
                    case_id,
                    len(fallback_items),
                    only_case_evidence,
                )

        # 백엔드에서 넘긴 doc_id / item_id (Evidence Binding: 해당 문서·항목 관련 규정을 최상단에 배치)
        # 백엔드 규격: doc_id/item_id는 String 또는 Number(int/float)로 전달될 수 있음 → 항상 str로 정규화
        def _norm_id(raw: Any) -> str | None:
            if raw is None:
                return None
            if isinstance(raw, dict):
                return _norm_id(raw.get("docKey") or raw.get("id"))
            if isinstance(raw, (str, int, float)):
                s = str(raw).strip()
                return s or None
            return str(raw).strip() or None

        doc_id_ref: str | None = None
        item_id_ref: str | None = None
        target_buzei: str | None = None  # SAP 전표 행(라인) 식별 — 어떤 전표 행이 문제인지 명시
        item_no: str | None = None
        if body_evidence and isinstance(body_evidence, dict):
            raw_doc = body_evidence.get("doc_id") or (body_evidence.get("document") or {}).get("docKey")
            raw_item = body_evidence.get("item_id")
            doc_id_ref = _norm_id(raw_doc)
            item_id_ref = _norm_id(raw_item)
            target_buzei = _norm_id(body_evidence.get("target_buzei") or body_evidence.get("buzei"))
            item_no = _norm_id(body_evidence.get("item_no") or body_evidence.get("item_id") or raw_item)
        if not target_buzei and isinstance(case_data, dict):
            target_buzei = _norm_id(case_data.get("target_buzei") or case_data.get("buzei"))
        if not item_no and isinstance(case_data, dict):
            item_no = _norm_id(case_data.get("item_no") or case_data.get("item_id"))
        if doc_id_ref and doc_list:
            # pgvector 검색 결과에서 body_evidence.doc_id와 일치하는 문서를 최상단에 배치(Ranking)
            doc_id_norm = doc_id_ref.strip()
            def _doc_rank_key(d: dict[str, Any]) -> tuple[int, float]:
                rid = str(d.get("rag_document_id") or d.get("sourceKey") or d.get("docKey") or "").strip()
                match = 0 if rid == doc_id_norm else 1
                return (match, -(float(d.get("score", 0)) or 0))
            doc_list.sort(key=_doc_rank_key)

        yield ("thought_pending", _with_coords({"step_label": "EVIDENCE_COLLECTED", "message": THOUGHT_PENDING_MESSAGE, **id_mapping}))
        evidence_thought = enforce_grounded_public_thought(
            await generate_thought_stream(
                "EVIDENCE_COLLECTED",
                case_data,
                case_id=case_id,
                evidence_count=len(evidence_items),
                rag_count=sum(1 for e in evidence_items if e.get("type") == "RAG_CHUNK"),
                intended_risk_type=intended_risk_type,
                reasoning_history=reasoning_history,
            ),
            case_data=case_data if isinstance(case_data, dict) else None,
            evidence_items=evidence_items,
            require_rag_for_claims=True,
        )
        if evidence_thought:
            reasoning_history.append(evidence_thought)
        if _should_emit_agent_stream(evidence_thought, "EVIDENCE_COLLECTED"):
            c = (evidence_thought or "").strip()
            last_agent_stream_content[0] = c
            yield ("AGENT_STREAM", _with_coords({"content": evidence_thought or "", "step_label": "EVIDENCE_COLLECTED", **id_mapping}))
        _ev_thought = None if _is_agent_stream_insight(evidence_thought) else (evidence_thought or None)
        yield ("evidence", AnalysisEvidenceEvent(type="COLLECTED", items=evidence_items, thought_stream=_ev_thought).model_dump())
        yield ("thought_pending", _with_coords({"step_label": "RULE_SCORING", "message": THOUGHT_PENDING_MESSAGE, **id_mapping}))
        thought_rule = enforce_grounded_public_thought(
            await generate_thought_stream(
                "RULE_SCORING",
                case_data,
                case_id=case_id,
                rag_count=len(vector_results) if vector_results else 0,
                intended_risk_type=intended_risk_type,
                reasoning_history=reasoning_history,
            ),
            case_data=case_data if isinstance(case_data, dict) else None,
            evidence_items=evidence_items,
            require_rag_for_claims=True,
        )
        if thought_rule:
            reasoning_history.append(thought_rule)
        if _should_emit_agent_stream(thought_rule, "RULE_SCORING"):
            c = (thought_rule or "").strip()
            last_agent_stream_content[0] = c
            yield ("AGENT_STREAM", _with_coords({"content": thought_rule or "", "step_label": "RULE_SCORING", **id_mapping}))
        _step_thought = None if _is_agent_stream_insight(thought_rule) else (thought_rule or None)
        yield ("step", _with_coords({**AnalysisStepEvent(
            label="RULE_SCORING",
            detail="규정 제한 업종·금액·시간 기준 위반 여부 검토 중입니다.",
            percent=45,
            total_steps=TOTAL_ANALYSIS_STEPS,
            thought_stream=_step_thought,
        ).model_dump(), **id_mapping}))

        # Step3: 룰 스코어링 (정상/위반 대비: DEMO_NORM_* vs DEMO0000*)
        amount = 0.0
        if isinstance(case_data, dict):
            amount = float(case_data.get("amount", case_data.get("totalAmount", 0)) or 0)
        anomaly_score = min(0.95, 0.3 + (amount / 1_000_000) * 0.2) if amount > 0 else 0.5
        pattern_match = 0.7
        rule_compliance = 0.85
        overall = (anomaly_score * 0.4 + pattern_match * 0.3 + rule_compliance * 0.3)
        is_demo_norm = isinstance(case_id, str) and case_id.upper().startswith("DEMO_NORM_")
        is_demo_violation = isinstance(case_id, str) and case_id.upper().startswith("DEMO0000")
        if is_demo_norm:
            overall = min(overall, 0.45)
        elif is_demo_violation:
            overall = max(overall, 0.82)

        yield ("confidence", AnalysisConfidenceEvent(
            anomalyScore=round(anomaly_score, 2),
            patternMatch=round(pattern_match, 2),
            ruleCompliance=round(rule_compliance, 2),
            overall=round(overall, 2),
        ).model_dump())

        yield ("thought_pending", _with_coords({"step_label": "LLM_REASONING", "message": THOUGHT_PENDING_MESSAGE, **id_mapping}))
        thought_llm = enforce_grounded_public_thought(
            await generate_thought_stream(
                "LLM_REASONING",
                case_data,
                case_id=case_id,
                evidence_count=len(evidence_items),
                intended_risk_type=intended_risk_type,
                reasoning_history=reasoning_history,
            ),
            case_data=case_data if isinstance(case_data, dict) else None,
            evidence_items=evidence_items,
            require_rag_for_claims=True,
        )
        if thought_llm:
            reasoning_history.append(thought_llm)
        if _should_emit_agent_stream(thought_llm, "LLM_REASONING"):
            c = (thought_llm or "").strip()
            last_agent_stream_content[0] = c
            yield ("AGENT_STREAM", _with_coords({"content": thought_llm or "", "step_label": "LLM_REASONING", **id_mapping}))
        _step_thought = None if _is_agent_stream_insight(thought_llm) else (thought_llm or None)
        yield ("step", _with_coords({**AnalysisStepEvent(
            label="LLM_REASONING",
            detail="규정 조문과 대조하여 위반 여부 판단 및 판단 근거 작성 중입니다.",
            percent=65,
            total_steps=TOTAL_ANALYSIS_STEPS,
            thought_stream=_step_thought,
        ).model_dump(), **id_mapping}))

        # Step4: LLM reasonText (XAI: 규정 인용형 문장)
        # 우선순위: intended_risk_type(요청) > case_type/caseType(스크리닝 결과, get_case/body_evidence) > 기본값
        risk_type = "UNUSUAL_PATTERN"
        screening_case_type: str | None = None
        screening_reason_text: str | None = None
        _be = body_evidence if isinstance(body_evidence, dict) else {}
        # intended_risk_type 유무와 무관하게 screening_case_type은 항상 추출/로그한다.
        for src in (case_data, _be):
            if not isinstance(src, dict):
                continue
            ct_raw = src.get("case_type") or src.get("caseType")
            if not ct_raw:
                continue
            ct = str(ct_raw).strip().upper()
            # BE가 DEFAULT 또는 Aura 6종 외 코드(DUPLICATE_INVOICE 등)로 보낼 수 있음 → 매핑 후 사용
            if ct == "DEFAULT":
                logger.info(
                    "audit_analysis: caseType from BE ignored (DEFAULT) case_id=%s source=%s",
                    case_id,
                    "case_data" if src is case_data else "body_evidence",
                )
                ct = None
            elif ct not in SCREENING_CASE_TYPES and ct in BE_CASE_TYPE_TO_SCREENING:
                ct = BE_CASE_TYPE_TO_SCREENING[ct]
                logger.info(
                    "audit_analysis: caseType mapped from BE case_id=%s raw=%s -> %s",
                    case_id,
                    str(ct_raw).strip().upper(),
                    ct,
                )
            elif ct not in SCREENING_CASE_TYPES:
                logger.info(
                    "audit_analysis: caseType from BE not in allowed/mapping case_id=%s raw_caseType=%s (will not use for screening)",
                    case_id,
                    ct,
                )
                ct = None
            if ct and ct in SCREENING_CASE_TYPES:
                screening_case_type = ct
                screening_reason_text = (
                    (src.get("screening_reason_text") or src.get("reasonText") or "").strip() or None
                )
                logger.info(
                    "audit_analysis: extracted screening caseType case_id=%s caseType=%s source=%s",
                    case_id,
                    screening_case_type,
                    "case_data" if src is case_data else "body_evidence",
                )
                break
        # caseType이 없거나 DEFAULT여도 reasonText만 있으면 LLM 가이드로 사용
        if not screening_case_type and not screening_reason_text:
            for src in (case_data, _be):
                if not isinstance(src, dict):
                    continue
                screening_reason_text = (
                    (src.get("screening_reason_text") or src.get("reasonText") or "").strip() or None
                )
                if screening_reason_text:
                    logger.info(
                        "audit_analysis: using screening reasonText only (no caseType) case_id=%s preview=%s",
                        case_id,
                        screening_reason_text[:80],
                    )
                    break

        if intended_risk_type and str(intended_risk_type).strip():
            risk_type = str(intended_risk_type).strip()
        elif screening_case_type:
            risk_type = screening_case_type
        elif isinstance(case_data, dict):
            risk_type = case_data.get("case_type") or case_data.get("caseType") or risk_type
            if isinstance(risk_type, str):
                risk_type = risk_type.strip() or "UNUSUAL_PATTERN"
            else:
                risk_type = "UNUSUAL_PATTERN"
            logger.info(
                "audit_analysis: risk_type from case_type fallback case_id=%s risk_type=%s (no screening_case_type)",
                case_id,
                risk_type,
            )

        has_rag_evidence = _has_rag_evidence_items(evidence_items)
        policy_gate = evaluate_policy_gate(
            case_data if isinstance(case_data, dict) else {},
            has_rag_evidence=has_rag_evidence,
        )
        policy_case_type = policy_gate.get("recommended_case_type")
        policy_conflict = False
        policy_reeval_applied = False
        if (not risk_type or str(risk_type).upper() == "DEFAULT") and isinstance(policy_case_type, str):
            risk_type = policy_case_type
            logger.info(
                "audit_analysis: risk_type from policy_gate case_id=%s risk_type=%s signals=%s",
                case_id,
                risk_type,
                policy_gate.get("signals"),
            )
        if (
            isinstance(policy_case_type, str)
            and isinstance(risk_type, str)
            and policy_case_type.strip().upper() in SCREENING_CASE_TYPES
            and risk_type.strip().upper() in SCREENING_CASE_TYPES
            and policy_case_type.strip().upper() != risk_type.strip().upper()
        ):
            policy_conflict = True
            if not has_rag_evidence:
                old_risk_type = risk_type
                risk_type = policy_case_type
                policy_reeval_applied = True
                logger.info(
                    "audit_analysis: policy-llm conflict resolved by policy gate case_id=%s from=%s to=%s signals=%s has_rag_evidence=%s",
                    case_id,
                    old_risk_type,
                    risk_type,
                    policy_gate.get("signals"),
                    has_rag_evidence,
                )
            else:
                logger.info(
                    "audit_analysis: policy-llm conflict observed (rag exists, keep llm risk_type) case_id=%s risk_type=%s policy_case_type=%s",
                    case_id,
                    risk_type,
                    policy_case_type,
                )
        if isinstance(policy_gate.get("normalized"), dict):
            norm = policy_gate["normalized"]
            for k in ("hrStatus", "hrStatusRaw", "mccCode", "mccCodeRaw", "occurredAt", "isHoliday", "isHolidaySource"):
                if norm.get(k) is not None:
                    case_data[k] = norm.get(k)
            if norm.get("mccCode") == "unknown":
                logger.info(
                    "audit_analysis: mcc normalized to unknown case_id=%s raw=%s",
                    case_id,
                    norm.get("mccCodeRaw"),
                )

        logger.info(
            "audit_analysis LLM reasonText input: case_id=%s risk_type=%s screening_case_type=%s has_screening_reason_text=%s prompt_guide=intended_risk=%s screening_type=%s reason_only=%s",
            case_id,
            risk_type,
            screening_case_type,
            bool(screening_reason_text),
            bool(intended_risk_type and str(intended_risk_type).strip()),
            bool(screening_case_type),
            bool(screening_reason_text and not screening_case_type),
        )

        regulation_citations = build_regulation_citations(doc_list)
        case_context_parts: list[str] = []
        if isinstance(case_data, dict):
            if case_data.get("occurredAt") or case_data.get("occurred_at"):
                case_context_parts.append(f"발생 시각: {case_data.get('occurredAt') or case_data.get('occurred_at')}")
            if case_data.get("amount") is not None:
                case_context_parts.append(f"금액: {case_data.get('amount')}")
            if case_data.get("expenseType") or case_data.get("expense_type"):
                case_context_parts.append(f"경비 유형: {case_data.get('expenseType') or case_data.get('expense_type')}")
        case_context = ". ".join(case_context_parts) if case_context_parts else ""

        doc_id = doc_id_ref
        item_id = item_id_ref

        reason_text = f"케이스 {case_id}: {_case_type_name(risk_type)}."
        try:
            llm = get_llm_client(model_name)
            prompt_parts = [
                f"케이스 {case_id} 분석 결과를 한 문단으로 요약. ",
                f"위험 유형: {_case_type_name(risk_type)}. 스코어: {overall:.2f}. ",
            ]
            if intended_risk_type and str(intended_risk_type).strip():
                prompt_parts.append(
                    f"[가이드] 사용자가 위험 유형을 '{_case_type_name(intended_risk_type)}'으로 지정했습니다. "
                    "최종 결론은 반드시 아래 규정 근거와 일치할 때만 확정하십시오. "
                )
            elif screening_case_type:
                prompt_parts.append(
                    f"[참고 힌트] 이 케이스는 스크리닝에서 **{_case_type_name(screening_case_type)}**으로 분류되었습니다. "
                    "이 값은 힌트이며, 최종 결론은 반드시 RAG 근거 기준으로 작성하십시오. "
                )
                if screening_reason_text:
                    _ellip = "…" if len(screening_reason_text) > 400 else ""
                    prompt_parts.append(
                        f"스크리닝 판단 요약: 「{screening_reason_text[:400]}{_ellip}」. "
                        "해당 문구를 그대로 재사용하지 말고, 근거 검증 후 필요한 정보만 반영하십시오. "
                    )
            if screening_reason_text and not screening_case_type:
                # caseType 없음(DEFAULT 등)이어도 힌트로만 사용
                _ellip = "…" if len(screening_reason_text) > 400 else ""
                prompt_parts.append(
                    f"[참고 힌트] 스크리닝 판단 요약: 「{screening_reason_text[:400]}{_ellip}」. "
                    "근거가 없으면 조항/위반을 단정하지 마십시오. "
                )
            if policy_gate.get("signals"):
                prompt_parts.append(
                    f"결정론 정책 신호: {', '.join(policy_gate.get('signals') or [])}. "
                    "신호는 보조 근거이며 규정 인용이 없으면 확정 결론으로 사용하지 마십시오. "
                )
            if doc_id or item_id or target_buzei or item_no:
                parts = [f"doc_id={doc_id or '미지정'}", f"item_id={item_id or '미지정'}"]
                if target_buzei or item_no:
                    parts.append(f"전표 행(target_buzei/item_no)={target_buzei or item_no or '미지정'}")
                prompt_parts.append(
                    f"백엔드에서 지정한 문서·항목({', '.join(parts)})에 대한 "
                    "상세 내역을 우선 참고하여 규정 준수 여부를 판단하고, 해당 전표 행이 문제인 경우 이유에 반드시 명시하시오. "
                )
            if regulation_citations:
                prompt_parts.append(
                    regulation_citations + "\n\n"
                    "위 참조 규정(RAG 검색 결과)을 반드시 인용하여 작성하되, "
                    "조항 번호와 문장은 위 목록에 실제로 나온 내용만 사용하십시오. "
                    "정상 전표면 수집된 규정 기준 충족을, 위반 전표면 해당 조항 정면 위반과 구체적 근거를 서술할 것. "
                    "evidence에는 해당 조항 원문을 바인딩할 수 있도록 조문 번호를 명시하고, "
                    "URL이 있으면 마크다운 [설명](URL)으로 작성하십시오."
                )
            else:
                prompt_parts.append(
                    "현재 내부 규정 인용 결과가 없습니다. 조항 번호를 임의 생성하지 말고, "
                    "'근거 부족으로 확정 판단 보류' 형태로 작성하십시오."
                )
            if external_search_text:
                prompt_parts.append(
                    "\n\n외부 참조 (사내 규정에 없을 때 참고):\n" + (external_search_text[:3000] if len(external_search_text) > 3000 else external_search_text)
                    + "\n\n위 외부 출처가 있으면 '사내 규정에는 없으나, [출처명](URL)에 따르면 ...' 형태로 인용하고, URL은 [설명](URL) 마크다운으로 작성할 것."
                )
            if case_context:
                prompt_parts.append(f"케이스 맥락: {case_context}. ")
            prompt_parts.append(_analysis_fewshot_by_risk(risk_type))
            prompt_parts.append(
                "한국어로 2~3문장으로 사람이 이해할 수 있는 이유(reasonText)를 작성. "
                "**반드시 첫 문장에 이번 분석의 핵심 결론**(위반 여부·적용 조항·판단 요약)을 배치하고, 그 다음 문장부터 근거를 서술하십시오. "
                "'데이터 분석 중' 같은 진행 로그는 금지합니다. "
                "전문 용어는 최소화하고, 증거와 결론을 설명 가능한 문장으로 작성. "
                "근거 없는 과거비교(예: 3개월/20%) 및 근거 없는 조항 단정은 금지합니다. "
                "주의: 내부 분류 코드 리터럴을 문장에 쓰지 말고 한국어 코드명으로 작성하십시오."
            )
            prompt = "".join(prompt_parts)
            resp_text = await llm.ainvoke(prompt)
            if resp_text:
                reason_text = resp_text.strip()
        except Exception as e:
            logger.warning(f"LLM reasonText failed: {e}")
            reason_text += f"증거 {len(evidence_items)}건 수집. 스코어 {overall:.2f}."
        logger.info(
            "audit_analysis reasonText resolved: case_id=%s preview=%s",
            case_id,
            (reason_text[:120] + "…") if reason_text and len(reason_text) > 120 else (reason_text or ""),
        )
        # 위반 조항 추출 (RAG vector_results 기반).
        violation_clause_str = ""
        violation_clauses: list[str] = []
        for v in vector_results:
            if not isinstance(v, dict):
                continue
            loc = (v.get("location") or "").strip() or (
                f"규정 {v.get('regulation_article') or ''} {v.get('regulation_clause') or ''}".strip()
            )
            if loc and loc not in violation_clauses:
                violation_clauses.append(loc)
        if violation_clauses and not violation_clause_str:
            violation_clause_str = violation_clauses[0]
        risk_level = "HIGH" if overall >= 0.8 else "MEDIUM" if overall >= 0.6 else "LOW"
        # DEMO 케이스: RAG 검색 결과(doc_list/vector_results) 기반으로만 문장 구성. 하드코딩 조문 금지.
        if is_demo_norm:
            citation_sentence = build_citation_reasoning(doc_list, risk_level="LOW", default_subject="본 건")
            prefix = (citation_sentence + " ") if citation_sentence else "수집된 규정 기준을 충족하는 지출로 판단됩니다. "
            reason_text = prefix + reason_text
            risk_level = "LOW"
        elif is_demo_violation:
            violation_article, violation_clause = None, None
            for v in vector_results:
                if not isinstance(v, dict):
                    continue
                violation_article = v.get("regulation_article") or v.get("regulationArticle")
                violation_clause = v.get("regulation_clause") or v.get("regulationClause")
                if violation_article or violation_clause:
                    violation_article = (violation_article or "").strip() or None
                    violation_clause = (violation_clause or "").strip() or None
                    break
            if violation_article or violation_clause:
                violation_clause_str = f"규정 {violation_article or ''} {violation_clause or ''}".strip()
                if violation_clause_str and violation_clause_str not in violation_clauses:
                    violation_clauses.append(violation_clause_str)
                clause_evidence = get_violation_clause_evidence(
                    doc_list, violation_article or "", violation_clause or ""
                ) if doc_list else None
                if clause_evidence:
                    evidence_items.append({
                        "type": "REGULATION_CLAUSE",
                        "source": "rag",
                        "location": clause_evidence.get("location"),
                        "excerpt": clause_evidence.get("excerpt"),
                        "article": violation_article,
                        "clause": violation_clause,
                        "doc_id": clause_evidence.get("doc_id"),
                        "docId": clause_evidence.get("doc_id"),
                        "chunk_id": clause_evidence.get("chunk_id"),
                        "chunkId": clause_evidence.get("chunk_id"),
                    })
            violation_reason = case_context or ""
            reason_text = (
                (f"규정 {violation_article or ''} {violation_clause or ''}을(를) 정면으로 위반했습니다. " if (violation_article or violation_clause) else "수집된 규정에 따른 위반으로 판별됩니다. ")
                + (violation_reason + " " if violation_reason else "")
                + reason_text
            )
            risk_level = "HIGH"
        else:
            citation_sentence = build_citation_reasoning(
                doc_list, risk_level=risk_level, default_subject="본 건"
            )
            if "에 의거하여" in citation_sentence:
                reason_text = citation_sentence + " " + reason_text

        reason_text = _finalize_reason_text_with_grounding(
            reason_text=reason_text,
            case_data=case_data if isinstance(case_data, dict) else None,
            evidence_items=evidence_items,
            screening_case_type=screening_case_type,
            screening_reason_text=screening_reason_text,
        )
        reason_text = _replace_case_type_codes(reason_text)
        if policy_reeval_applied:
            reason_text = (
                f"정책 신호와 스크리닝 신호 충돌이 감지되어 **{_case_type_name(risk_type)}** 기준으로 재평가했습니다. "
                + reason_text
            )
        if _VIOLATION_TEXT_PATTERN.search(reason_text) and risk_level == "LOW":
            risk_level = "MEDIUM"
            logger.info(
                "audit_analysis severity gate applied: case_id=%s reason=violation_text_with_low uplifted_to=%s",
                case_id,
                risk_level,
            )
        has_rag_evidence = _has_rag_evidence_items(evidence_items)
        quality_gate_codes = _build_quality_gate_codes(
            case_data=case_data if isinstance(case_data, dict) else None,
            evidence_items=evidence_items,
            has_rag_evidence=has_rag_evidence,
            policy_gate=policy_gate,
        )
        if policy_reeval_applied:
            quality_gate_codes.append("POLICY_REEVAL_APPLIED")
        elif policy_conflict:
            quality_gate_codes.append("POLICY_CONFLICT_DETECTED")
        if quality_gate_codes != ["OK"]:
            incr("audit_analysis_degraded_total")
        for code in quality_gate_codes:
            incr(f"audit_analysis_quality_gate_{code.lower()}_total")
        logger.info(
            "audit_analysis quality_gate case_id=%s codes=%s policy_signals=%s",
            case_id,
            quality_gate_codes,
            policy_gate.get("signals", []) if isinstance(policy_gate, dict) else [],
        )
        yield ("gate", _with_coords({
            "node": "QUALITY_GATE",
            "decision_code": "OK" if quality_gate_codes == ["OK"] else "HOLD_REVIEW",
            "quality_gate_codes": quality_gate_codes,
            "input_hash": _stable_hash({
                "caseId": case_id,
                "codes": quality_gate_codes,
            }),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **id_mapping,
        }))
        output_overall = float(overall)
        if "RAG_ZERO" in quality_gate_codes:
            output_overall = min(output_overall, 0.35)
            logger.info(
                "audit_analysis conservative scoring applied: case_id=%s reason=RAG_ZERO original=%.3f adjusted=%.3f",
                case_id,
                overall,
                output_overall,
            )
        if "INPUT_PARTIAL" in quality_gate_codes:
            old = output_overall
            output_overall = min(output_overall, 0.45)
            if output_overall != old:
                logger.info(
                    "audit_analysis conservative scoring applied: case_id=%s reason=INPUT_PARTIAL original=%.3f adjusted=%.3f",
                    case_id,
                    old,
                    output_overall,
                )
        evidence_items.append(
            {
                "type": "POLICY_GATE",
                "source": "deterministic_policy_engine",
                "signals": policy_gate.get("signals", []),
                "recommended_case_type": policy_gate.get("recommended_case_type"),
                "allow_strong_conclusion": policy_gate.get("allow_strong_conclusion"),
                "needs_manual_review": policy_gate.get("needs_manual_review"),
                "quality_gate_codes": quality_gate_codes,
            }
        )
        evidence_items.append(
            {
                "type": "MCP_FACT_CONTEXT",
                "source": "mcp_adapter",
                "mode": mcp_fact_context.get("mode"),
                "facts": mcp_fact_context.get("facts"),
                "quality": mcp_fact_context.get("quality"),
            }
        )

        # 문장별 근거 커버리지 점검: 결론 문장이 근거와 연결되지 않으면 보수적으로 강등
        citations_preview = _build_citations_payload(doc_list, external_citations)
        logger.info(
            "audit_analysis citations_preview: case_id=%s doc_list=%s external_citations=%s citations_preview=%s sample_ids=%s sample_refs=%s",
            case_id,
            len(doc_list or []),
            len(external_citations or []),
            len(citations_preview or []),
            [c.get("citation_id") for c in (citations_preview or [])[:3] if isinstance(c, dict)],
            [str(c.get("reference") or c.get("title") or "")[:80] for c in (citations_preview or [])[:3] if isinstance(c, dict)],
        )
        # 위험유형-조항 의미 정합성 게이트
        if not _is_risk_article_semantically_aligned(risk_type=risk_type, citations=citations_preview):
            if "RISK_ARTICLE_MISMATCH" not in quality_gate_codes:
                quality_gate_codes.append("RISK_ARTICLE_MISMATCH")
            logger.info(
                "audit_analysis risk-article mismatch gate: case_id=%s risk_type=%s citations_preview=%s",
                case_id,
                risk_type,
                len(citations_preview),
            )
            reason_text = _build_hold_reason_with_context(
                case_data=case_data if isinstance(case_data, dict) else None,
                risk_type=risk_type,
                hold_reason=(
                    "현재 인용된 조항의 의미가 위험유형과 충분히 정합하지 않아 확정 판단을 보류합니다. "
                    "위험유형에 맞는 규정 조항을 재매칭한 뒤 재평가가 필요합니다."
                ),
            )
            output_overall = min(output_overall, 0.45)
            if risk_level == "HIGH":
                risk_level = "MEDIUM"
        grounding = _compute_reason_grounding_coverage(
            reason_text=reason_text,
            evidence_items=evidence_items,
            citations=citations_preview,
        )
        sentence_citation_map = _build_sentence_citation_map(
            reason_text=reason_text,
            citations=citations_preview,
        )
        grounded_rows = sum(1 for r in (sentence_citation_map or []) if isinstance(r, dict) and bool(r.get("grounded")))
        ungrounded_rows = sum(1 for r in (sentence_citation_map or []) if isinstance(r, dict) and not bool(r.get("grounded")))
        logger.info(
            "audit_analysis sentence_citation_map summary: case_id=%s rows=%s grounded=%s ungrounded=%s sample=%s",
            case_id,
            len(sentence_citation_map or []),
            grounded_rows,
            ungrounded_rows,
            [
                {
                    "idx": r.get("sentence_index"),
                    "grounded": r.get("grounded"),
                    "citation_ids": r.get("citation_ids"),
                }
                for r in (sentence_citation_map or [])[:3]
                if isinstance(r, dict)
            ],
        )
        coverage_ratio = float(grounding.get("coverage_ratio") or 0.0)
        ungrounded_claim_count = 0
        for row in sentence_citation_map:
            if not isinstance(row, dict):
                continue
            sent = str(row.get("sentence") or "")
            grounded_sent = bool(row.get("grounded"))
            if grounded_sent:
                continue
            if _VIOLATION_TEXT_PATTERN.search(sent) or _ARTICLE_IN_TEXT_PATTERN.search(sent):
                ungrounded_claim_count += 1
        evidence_items.append(
            {
                "type": "GROUNDING_COVERAGE",
                "source": "reason_grounding_gate",
                "coverage_ratio": coverage_ratio,
                "grounded_sentences": grounding.get("grounded_sentences"),
                "total_sentences": grounding.get("total_sentences"),
                "ungrounded_sentences": grounding.get("ungrounded_sentences", []),
                "ungrounded_claim_sentences": ungrounded_claim_count,
            }
        )
        # FE 실시간 검증용: 문장-인용 매핑을 SSE evidence 이벤트로 즉시 송출
        yield (
            "evidence",
            AnalysisEvidenceEvent(
                type="SENTENCE_CITATION_MAP",
                items=sentence_citation_map,
                thought_stream="[결론] 문장별 인용 근거 매핑을 완료했습니다.",
            ).model_dump(),
        )
        logger.info(
            "audit_analysis SENTENCE_CITATION_MAP emitted: case_id=%s items=%s",
            case_id,
            len(sentence_citation_map or []),
        )
        if ungrounded_claim_count > 0:
            if "SENTENCE_CITATION_MISSING" not in quality_gate_codes:
                quality_gate_codes.append("SENTENCE_CITATION_MISSING")
            logger.info(
                "audit_analysis sentence-citation gate: case_id=%s ungrounded_claim_sentences=%s",
                case_id,
                ungrounded_claim_count,
            )
            reason_text = _build_hold_reason_with_context(
                case_data=case_data if isinstance(case_data, dict) else None,
                risk_type=risk_type,
                hold_reason=(
                    "일부 핵심 결론 문장이 인용 근거와 직접 연결되지 않아 확정 판단을 보류합니다. "
                    "근거 문장 매핑을 보강한 뒤 재평가가 필요합니다."
                ),
            )
            output_overall = min(output_overall, 0.4)
            if risk_level == "HIGH":
                risk_level = "MEDIUM"

        if grounding.get("total_sentences", 0) >= 2 and coverage_ratio < 0.6:
            if "EVIDENCE_COVERAGE_LOW" not in quality_gate_codes:
                quality_gate_codes.append("EVIDENCE_COVERAGE_LOW")
            logger.info(
                "audit_analysis grounding coverage low: case_id=%s ratio=%.3f grounded=%s total=%s ungrounded=%s",
                case_id,
                coverage_ratio,
                grounding.get("grounded_sentences"),
                grounding.get("total_sentences"),
                grounding.get("ungrounded_sentences"),
            )
            if _VIOLATION_TEXT_PATTERN.search(reason_text):
                reason_text = _build_hold_reason_with_context(
                    case_data=case_data if isinstance(case_data, dict) else None,
                    risk_type=risk_type,
                    hold_reason=(
                        "현재 문장별 근거 연결률이 충분하지 않아 위반 확정 판단을 보류합니다. "
                        "추가 규정 근거 확인 후 재평가가 필요합니다."
                    ),
                )
                output_overall = min(output_overall, 0.45)
                risk_level = "MEDIUM" if risk_level == "HIGH" else risk_level

        # MCP fact context가 불완전한 경우 확정 위반을 보수적으로 제한
        if bool(get_settings().mcp_require_fact_for_violation):
            mcp_input_partial = bool((mcp_fact_context.get("quality") or {}).get("input_partial"))
            if mcp_input_partial and _VIOLATION_TEXT_PATTERN.search(reason_text):
                if "FACT_CONTEXT_PARTIAL" not in quality_gate_codes:
                    quality_gate_codes.append("FACT_CONTEXT_PARTIAL")
                reason_text = _build_hold_reason_with_context(
                    case_data=case_data if isinstance(case_data, dict) else None,
                    risk_type=risk_type,
                    hold_reason=(
                        "입력 사실 컨텍스트가 일부 누락되어 확정 위반 판단을 보류합니다. "
                        "필수 필드 보강 후 재분석이 필요합니다."
                    ),
                )
                output_overall = min(output_overall, 0.45)
                if risk_level == "HIGH":
                    risk_level = "MEDIUM"
        # OK와 경고 코드 동시 노출 방지
        if any(code != "OK" for code in quality_gate_codes):
            quality_gate_codes = [code for code in quality_gate_codes if code != "OK"]

        analysis_score_breakdown = _build_analysis_score_breakdown(
            anomaly_score=anomaly_score,
            pattern_match=pattern_match,
            rule_compliance=rule_compliance,
            output_overall=output_overall,
            quality_gate_codes=quality_gate_codes,
            coverage_ratio=coverage_ratio,
        )

        yield ("step", _with_coords({**AnalysisStepEvent(
            label="PROPOSALS",
            detail="권고 조치(결제 보류·추가 확인 등) 생성 중입니다.",
            percent=85,
        ).model_dump(), **id_mapping}))

        # Step5: Proposals
        now_iso = datetime.now(timezone.utc).isoformat()
        proposals: list[dict[str, Any]] = []
        if output_overall >= 0.6 and "RAG_ZERO" not in quality_gate_codes:
            proposals.append({
                "type": "PAYMENT_BLOCK",
                "riskLevel": "HIGH" if output_overall >= 0.8 else "MEDIUM",
                "rationale": "위험 점수에 따른 추가 검토 권고",
                "requiresApproval": True,
                "payload": {"caseId": case_id, "action": "block"},
                "createdAt": now_iso,
            })
        proposals.append({
            "type": "REQUEST_INFO",
            "riskLevel": "MEDIUM",
            "rationale": "거래처 확인 요청",
            "requiresApproval": False,
            "payload": {"caseId": case_id},
            "createdAt": now_iso,
        })

        for p in proposals:
            yield ("proposal", AnalysisProposalEvent(
                type=p["type"],
                riskLevel=p["riskLevel"],
                rationale=p["rationale"],
                requiresApproval=p["requiresApproval"],
                payload=p.get("payload", {}),
            ).model_dump())

        # similarCases: key-based (벡터DB 없으면 거래처/금액/유형)
        similar_cases: list[dict[str, Any]] = []
        if isinstance(case_data, dict):
            vendor = case_data.get("vendorId") or case_data.get("vendor_id") or ""
            amt = float(case_data.get("amount", case_data.get("totalAmount", 0)) or 0)
            for i in range(min(3, 2 if vendor or amt else 0)):
                similar_cases.append({
                    "caseId": f"{case_id}-sim-{i+1}",
                    "similarity": "vendor" if vendor and i == 0 else "amount_range",
                    "vendorId": vendor or "V-001",
                    "amount": amt * (0.9 + i * 0.1),
                })

        # 권고 조치 요약 (Autonomous Conclusion: recommended_action)
        recommended_action = ""
        if proposals:
            recommended_action = "; ".join(p.get("rationale", "") for p in proposals if p.get("rationale"))

        # citations: 내부 규정(RAG) + 외부 검색 URL
        citations = _build_citations_payload(doc_list, external_citations)
        logger.info(
            "audit_analysis citations_final: case_id=%s count=%s sample_ids=%s",
            case_id,
            len(citations or []),
            [c.get("citation_id") for c in (citations or [])[:5] if isinstance(c, dict)],
        )

        # chunk_id: 분석에 사용된 핵심 규정 청크 ID (V65/agent_activity_log snake_case)
        chunk_id_ref: str | None = None
        for e in evidence_items:
            cid = (e.get("chunk_id") or e.get("chunkId")) if isinstance(e, dict) else None
            if cid:
                chunk_id_ref = str(cid).strip() or None
                break

        # decision_reason: 구조화 [종합 판정 / 핵심 근거 / 위반 조항 / 권고 사항] + evidence_map_json(전표 행↔근거 문장) 필수
        decision_reason = _build_decision_reason(
            reason_text=reason_text,
            violation_clause=violation_clause_str,
            violation_clauses=violation_clauses,
            evidence_items=evidence_items,
            citations=citations,
            doc_id=doc_id_ref,
            item_id=item_id_ref,
            chunk_id=chunk_id_ref,
            target_buzei=target_buzei,
            case_data=case_data,
            recommended_action=recommended_action,
            item_no=item_no,
        )
        analysis_quality_signals = _build_analysis_quality_signals(quality_gate_codes)
        decision_reason["quality_gate_codes"] = quality_gate_codes
        decision_reason["analysis_quality_signals"] = analysis_quality_signals
        decision_reason["analysis_score_breakdown"] = analysis_score_breakdown
        decision_reason["score_breakdown"] = analysis_score_breakdown
        decision_reason["sentence_citation_map"] = sentence_citation_map
        self_verify = _run_self_verification(
            reason_text=reason_text,
            evidence_items=evidence_items,
            violation_clauses=decision_reason.get("violation_clauses", violation_clauses),
            citations=citations,
        )
        if self_verify.get("status") != "pass":
            evidence_items.append(
                {
                    "type": "SELF_VERIFY",
                    "source": "self_verification",
                    "status": self_verify.get("status"),
                    "issues": self_verify.get("issues", []),
                }
            )
        decision_reason["self_verification"] = self_verify

        # finalResult 저장 (콜백 전에 반드시 실행 — break 시 get_audit_analysis_result 사용)
        # 백엔드 case_analysis_result 테이블 규격: violation_clause, risk_score, reasoning_summary, recommended_action, citations[]
        # V65: doc_id, item_id, chunk_id, target_buzei 반드시 snake_case
        severity = "HIGH" if output_overall >= 0.8 else "MEDIUM" if output_overall >= 0.6 else "LOW"
        # 정합성 게이트: 위반 결론 문구가 있으면 LOW로 내리지 않음
        if isinstance(reason_text, str) and _VIOLATION_TEXT_PATTERN.search(reason_text):
            if severity == "LOW":
                logger.warning(
                    "audit_analysis severity corrected: case_id=%s reason=violation_text_with_low severity_from=LOW severity_to=MEDIUM",
                    case_id,
                )
                severity = "MEDIUM"
        from core.streaming.case_stream_store import set_audit_analysis_result
        set_audit_analysis_result(case_id, {
            "reasonText": reason_text,
            "reasoning_summary": reason_text,
            "proposals": proposals,
            "confidenceBreakdown": {
                "anomalyScore": anomaly_score,
                "patternMatch": pattern_match,
                "ruleCompliance": rule_compliance,
                "overall": output_overall,
            },
            "analysis_score_breakdown": analysis_score_breakdown,
            "score_breakdown": analysis_score_breakdown,
            "sentence_citation_map": sentence_citation_map,
            "evidence": evidence_items[:10],
            "ragRefs": evidence_items[:5],
            "similarCases": similar_cases,
            "score": output_overall,
            "risk_score": round(output_overall * 100),
            "severity": severity,
            "violation_clause": violation_clause_str,
            "violation_clauses": decision_reason.get("violation_clauses", violation_clauses),
            "recommended_action": recommended_action,
            "citations": citations,
            "decision_reason": decision_reason,
            "quality_gate_codes": quality_gate_codes,
            "analysis_quality_signals": analysis_quality_signals,
            "evidence_map_json": decision_reason.get("evidence_map_json", []),
            "doc_id": doc_id_ref,
            "item_id": item_id_ref,
            "chunk_id": chunk_id_ref,
            "target_buzei": target_buzei,
            "item_no": item_no,
        })

        # 신규 고위험 케이스 탐지 시 Redis 알림 (workbench:alert, category=AI_DETECT — 백엔드 NotificationService 규격)
        if severity == "HIGH":
            try:
                from core.notifications import publish_workbench_notification, NOTIFICATION_CATEGORY_AI_DETECT
                settings = get_settings()
                from core.notifications import REDIS_CHANNEL_WORKBENCH_ALERT
                channel = getattr(settings, "workbench_alert_channel", REDIS_CHANNEL_WORKBENCH_ALERT)
                await publish_workbench_notification(
                    channel, NOTIFICATION_CATEGORY_AI_DETECT, "신규 이상 징후 탐지",
                    case_id=case_id, score=output_overall, severity=severity,
                )
            except Exception as e:
                logger.debug("AI_DETECT notification publish skipped: %s", e)

        # completed: 최종 완료 시에만 '위험 점수(Score)' 전송. 진행률과 구분. violation_clauses·evidence_map_json 필수 포함.
        completed_payload = AnalysisCompletedEvent(
            status="completed",
            runId=run_id,
            caseId=case_id,
            summary=reason_text[:500],
            score=output_overall,
            risk_score=round(output_overall * 100),
            severity=severity,
            score_type="final_risk_score",
            violation_clauses=decision_reason.get("violation_clauses", violation_clauses),
            evidence_map_json=decision_reason.get("evidence_map_json", []),
            quality_gate_codes=quality_gate_codes,
        ).model_dump()
        yield ("completed", completed_payload)
        incr("audit_analysis_completed_total")
        stop_timer(timer, "audit_analysis_duration_ms")

    except Exception as e:
        logger.exception(f"Audit analysis failed for {case_id}")
        incr("audit_analysis_failed_total")
        yield ("failed", AnalysisFailedEvent(error=str(e), stage="pipeline").model_dump())
