"""
제안·스코어 유틸 (Phase2/Phase3 공통)

evidence 기반 스코어, proposal fingerprint 등.
"""

from typing import Any


def score_from_evidence(evidence: list[dict[str, Any]]) -> float:
    """Evidence 건수 기반 간단 스코어 (0~1)."""
    if not evidence:
        return 0.5
    n = min(len(evidence), 10)
    return min(0.95, 0.4 + n * 0.06)


def proposal_fingerprint(proposal_type: str, payload: dict[str, Any]) -> str:
    """
    proposalId 대체 fingerprint: type|key1|key2|... (소문자, 언더스코어).

    BE dedup_key와 동일 규칙으로 사용 가능.
    """
    parts = [proposal_type.lower().replace("-", "_")]
    for k in ("companyCode", "docKey", "reasonCode", "caseId"):
        v = payload.get(k)
        if v is not None:
            parts.append(str(v).lower().replace(" ", "_"))
    return "|".join(parts)
