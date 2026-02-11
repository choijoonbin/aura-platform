"""
metadata_json 규격 유틸리티 (통합 워크벤치 UI)

agent_activity_log.payload_json / metadata_json 스키마 강제: title, reasoning, evidence, status.
"""

from typing import Any

from core.agent_stream.constants import METADATA_STATUSES, METADATA_STATUS_SUCCESS


def format_metadata(
    title: str,
    reasoning: str,
    evidence: dict[str, Any] | None = None,
    status: str = "SUCCESS",
    policy_reference: dict[str, Any] | None = None,
    rag_contributions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    metadata_json 규격 딕셔너리 생성. title, reasoning, evidence, status 필드 강제.
    Phase 4: policy_reference, rag_contributions를 evidence 내부에 포함 가능.

    Args:
        title: 단계 제목 (한 줄).
        reasoning: 사고 과정/메시지.
        evidence: 단계별 상세(docIds, actionId 등). None이면 {}.
        status: SUCCESS | WARNING | ERROR. 그 외 값이면 SUCCESS로 정규화.
        policy_reference: 정책 참조 정보 (configSource, profileName 등). evidence에 병합.
        rag_contributions: RAG 참조 목록 (location, title 등). evidence에 병합.

    Returns:
        {"title", "reasoning", "evidence", "status"} 키를 가진 dict.
    """
    if status not in METADATA_STATUSES:
        status = METADATA_STATUS_SUCCESS
    ev = dict(evidence) if evidence is not None else {}
    if policy_reference is not None and isinstance(policy_reference, dict):
        ev["policy_reference"] = policy_reference
    if rag_contributions is not None and isinstance(rag_contributions, list):
        ev["ragContributions"] = rag_contributions
    return {
        "title": title or "",
        "reasoning": reasoning or "",
        "evidence": ev,
        "status": status,
    }
