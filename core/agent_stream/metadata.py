"""
metadata_json 규격 유틸리티 (통합 워크벤치 UI)

agent_activity_log.payload_json / metadata_json 스키마:
- 필수: title, reasoning, evidence, status
- 에이전트 추론 고도화: insight_summary, logical_step, visual_hint (선택)
"""

from typing import Any

from core.agent_stream.constants import METADATA_STATUSES, METADATA_STATUS_SUCCESS

# agent_activity_log metadata_json 내 logical_step 허용값 (FE 타임라인 필터/배지용)
LOGICAL_STEPS = ("Hypothesis", "Investigation", "Evidence", "Conclusion")


def format_metadata(
    title: str,
    reasoning: str,
    evidence: dict[str, Any] | None = None,
    status: str = "SUCCESS",
    policy_reference: dict[str, Any] | None = None,
    rag_contributions: list[dict[str, Any]] | None = None,
    *,
    insight_summary: str | None = None,
    logical_step: str | None = None,
    visual_hint: str | list[str] | None = None,
) -> dict[str, Any]:
    """
    metadata_json 규격 딕셔너리 생성. title, reasoning, evidence, status 필드 강제.
    Phase 4: policy_reference, rag_contributions를 evidence 내부에 포함 가능.
    에이전트 추론 고도화: insight_summary, logical_step, visual_hint를 metadata 최상위에 포함.

    Args:
        title: 단계 제목 (한 줄).
        reasoning: 사고 과정/메시지.
        evidence: 단계별 상세(docIds, actionId 등). None이면 {}.
        status: SUCCESS | WARNING | ERROR. 그 외 값이면 SUCCESS로 정규화.
        policy_reference: 정책 참조 정보 (configSource, profileName 등). evidence에 병합.
        rag_contributions: RAG 참조 목록 (location, title 등). evidence에 병합.
        insight_summary: 현재 단계에서 발견된 결정적 단서 1줄 요약 (agent_activity_log용).
        logical_step: Hypothesis | Investigation | Evidence | Conclusion.
        visual_hint: FE에서 강조할 데이터 필드 (쉼표 구분 문자열 또는 필드명 리스트).

    Returns:
        {"title", "reasoning", "evidence", "status", "insight_summary"?, "logical_step"?, "visual_hint"?} dict.
    """
    if status not in METADATA_STATUSES:
        status = METADATA_STATUS_SUCCESS
    ev = dict(evidence) if evidence is not None else {}
    if policy_reference is not None and isinstance(policy_reference, dict):
        ev["policy_reference"] = policy_reference
    if rag_contributions is not None and isinstance(rag_contributions, list):
        ev["ragContributions"] = rag_contributions

    out: dict[str, Any] = {
        "title": title or "",
        "reasoning": reasoning or "",
        "evidence": ev,
        "status": status,
    }
    if insight_summary is not None and str(insight_summary).strip():
        out["insight_summary"] = str(insight_summary).strip()
    if logical_step is not None and str(logical_step).strip() in LOGICAL_STEPS:
        out["logical_step"] = str(logical_step).strip()
    if visual_hint is not None:
        if isinstance(visual_hint, list):
            out["visual_hint"] = [str(x).strip() for x in visual_hint if str(x).strip()]
        else:
            hint_str = str(visual_hint).strip()
            if hint_str:
                out["visual_hint"] = [s.strip() for s in hint_str.split(",") if s.strip()]
    return out
