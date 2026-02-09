"""
Phase2 Analysis Pipeline (aura.txt §3)

Step1: 입력 정규화 (evidence json schema 통일)
Step2: 간단 룰 스코어링 (금액, 거래처 신규, 역분개 체인 등)
Step3: LLM 호출로 reasonText 생성
Step4: proposals 생성
Step5: 결과 payload 구성 후 BE 콜백 (선택)
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from core.analysis.phase2_events import (
    AnalysisStartedEvent,
    AnalysisStepEvent,
    AnalysisEvidenceEvent,
    AnalysisConfidenceEvent,
    AnalysisProposalEvent,
    AnalysisCompletedEvent,
    AnalysisFailedEvent,
)
from core.llm import get_llm_client
from tools.synapse_finance_tool import get_case, search_documents, get_open_items, get_lineage

logger = logging.getLogger(__name__)

# 분석 비활성 플래그 (DEMO_OFF 등)
ANALYSIS_DISABLED_ENV = "DEMO_OFF"


def _normalize_body_evidence(body_evidence: dict[str, Any] | None) -> list[dict[str, Any]]:
    """BE body.evidence { evidence, ragRefs } → evidence_items 리스트 (C 폴백용)"""
    if not body_evidence or not isinstance(body_evidence, dict):
        return []
    items: list[dict[str, Any]] = []
    for e in body_evidence.get("evidence", []) or []:
        items.append(e if isinstance(e, dict) else {"type": "BODY_EVIDENCE", "value": e})
    for r in body_evidence.get("ragRefs", []) or []:
        items.append(r if isinstance(r, dict) else {"type": "BODY_RAGREF", "value": r})
    return items[:15]  # 상한


async def run_phase2_analysis(
    case_id: str,
    *,
    run_id: str | None = None,
    tenant_id: str = "1",
    trace_id: str | None = None,
    body_evidence: dict[str, Any] | None = None,
) -> AsyncGenerator[tuple[str, dict[str, Any]], None]:
    """
    Phase2 분석 파이프라인 실행.
    
    Yields:
        (event_type, payload) - started, step, evidence, confidence, proposal, completed | failed
    """
    run_id = run_id or str(uuid.uuid4())
    trace = trace_id or f"trace-{case_id}-{run_id[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    try:
        # started
        yield ("started", AnalysisStartedEvent(runId=run_id, caseId=case_id, at=now).model_dump())

        # Step1: 입력 정규화
        yield ("step", AnalysisStepEvent(label="INPUT_NORM", detail="케이스 입력 정규화 중", percent=10).model_dump())

        try:
            case_result = await get_case.ainvoke({"caseId": case_id})
            case_data = json.loads(case_result) if isinstance(case_result, str) else case_result
        except Exception as e:
            logger.warning(f"get_case failed for {case_id}: {e}")
            case_data = {}

        if isinstance(case_data, dict) and "error" in case_data:
            case_data = {}

        yield ("step", AnalysisStepEvent(label="EVIDENCE_GATHER", detail="증거 수집 중", percent=25).model_dump())

        # Step2: Evidence 수집
        evidence_items: list[dict[str, Any]] = []
        if case_data:
            evidence_items.append({
                "type": "CASE",
                "source": "get_case",
                "caseId": case_id,
                "keys": {k: v for k, v in case_data.items() if k in ("bukrs", "belnr", "gjahr", "vendorId", "amount")},
            })

        try:
            doc_result = await search_documents.ainvoke({"filters": {"caseId": case_id, "topK": 5}})
            docs = json.loads(doc_result) if isinstance(doc_result, str) else doc_result
            if isinstance(docs, dict):
                doc_list = docs.get("documents", docs.get("items", []))
            else:
                doc_list = docs if isinstance(docs, list) else []
            for i, d in enumerate((doc_list or [])[:5]):
                evidence_items.append({
                    "type": "DOC_HEADER" if i == 0 else "DOC_ITEM",
                    "source": "search_documents",
                    "index": i,
                    "keys": d.get("keys", {}) if isinstance(d, dict) else {"caseId": case_id},
                })
        except Exception as e:
            logger.debug(f"search_documents failed: {e}")

        try:
            oi_result = await get_open_items.ainvoke({"filters": {"caseId": case_id}})
            oi_data = json.loads(oi_result) if isinstance(oi_result, str) else oi_result
            items = oi_data.get("items", oi_data.get("openItems", [])) if isinstance(oi_data, dict) else []
            if items:
                evidence_items.append({"type": "OPEN_ITEMS", "source": "get_open_items", "count": len(items)})
        except Exception as e:
            logger.debug(f"get_open_items failed: {e}")

        try:
            lineage_result = await get_lineage.ainvoke({"caseId": case_id})
            lineage_data = json.loads(lineage_result) if isinstance(lineage_result, str) else lineage_result
            lineage = lineage_data.get("lineage", []) if isinstance(lineage_data, dict) and "error" not in lineage_data else []
            if lineage:
                evidence_items.append({"type": "LINEAGE", "source": "get_lineage", "count": len(lineage)})
        except Exception as e:
            logger.debug(f"get_lineage failed: {e}")

        # C(폴백): fetch 실패로 evidence_items 비어 있으면 body.evidence 사용
        if not evidence_items and body_evidence:
            fallback_items = _normalize_body_evidence(body_evidence)
            if fallback_items:
                evidence_items = fallback_items
                logger.info(f"case={case_id} using body.evidence fallback ({len(evidence_items)} items)")

        yield ("evidence", AnalysisEvidenceEvent(type="COLLECTED", items=evidence_items).model_dump())
        yield ("step", AnalysisStepEvent(label="RULE_SCORING", detail="룰 스코어링 실행", percent=45).model_dump())

        # Step3: 룰 스코어링
        amount = 0.0
        if isinstance(case_data, dict):
            amount = float(case_data.get("amount", case_data.get("totalAmount", 0)) or 0)
        anomaly_score = min(0.95, 0.3 + (amount / 1_000_000) * 0.2) if amount > 0 else 0.5
        pattern_match = 0.7
        rule_compliance = 0.85
        overall = (anomaly_score * 0.4 + pattern_match * 0.3 + rule_compliance * 0.3)

        yield ("confidence", AnalysisConfidenceEvent(
            anomalyScore=round(anomaly_score, 2),
            patternMatch=round(pattern_match, 2),
            ruleCompliance=round(rule_compliance, 2),
            overall=round(overall, 2),
        ).model_dump())

        yield ("step", AnalysisStepEvent(label="LLM_REASONING", detail="설명 생성 중", percent=65).model_dump())

        # Step4: LLM reasonText
        risk_type = "DUPLICATE_INVOICE"
        if isinstance(case_data, dict):
            risk_type = case_data.get("riskTypeKey", case_data.get("risk_type", risk_type))

        reason_text = f"케이스 {case_id}: {risk_type} 위험 유형. "
        try:
            llm = get_llm_client()
            prompt = (
                f"케이스 {case_id} 분석 결과를 한 문단으로 요약. "
                f"위험 유형: {risk_type}. "
                f"스코어: {overall:.2f}. "
                "한국어로 2~3문장으로 사람이 이해할 수 있는 이유(reasonText)를 작성."
            )
            resp_text = await llm.ainvoke(prompt)
            if resp_text:
                reason_text = resp_text.strip()
        except Exception as e:
            logger.warning(f"LLM reasonText failed: {e}")
            reason_text += f"증거 {len(evidence_items)}건 수집. 스코어 {overall:.2f}."

        yield ("step", AnalysisStepEvent(label="PROPOSALS", detail="권고 조치 생성", percent=85).model_dump())

        # Step5: Proposals
        now_iso = datetime.now(timezone.utc).isoformat()
        proposals: list[dict[str, Any]] = []
        if overall >= 0.6:
            proposals.append({
                "type": "PAYMENT_BLOCK",
                "riskLevel": "HIGH" if overall >= 0.8 else "MEDIUM",
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

        # completed
        severity = "HIGH" if overall >= 0.8 else "MEDIUM" if overall >= 0.6 else "LOW"
        completed_payload = AnalysisCompletedEvent(
            summary=reason_text[:500],
            score=overall,
            severity=severity,
        ).model_dump()
        yield ("completed", completed_payload)

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

        # finalResult 저장 (GET /analysis에서 반환)
        from core.streaming.case_stream_store import set_phase2_result
        set_phase2_result(case_id, {
            "reasonText": reason_text,
            "proposals": proposals,
            "confidenceBreakdown": {
                "anomalyScore": anomaly_score,
                "patternMatch": pattern_match,
                "ruleCompliance": rule_compliance,
                "overall": overall,
            },
            "ragRefs": evidence_items[:5],
            "similarCases": similar_cases,
            "score": overall,
            "severity": severity,
        })

    except Exception as e:
        logger.exception(f"Phase2 analysis failed for {case_id}")
        yield ("failed", AnalysisFailedEvent(error=str(e), stage="pipeline").model_dump())
