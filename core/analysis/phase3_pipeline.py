"""
Phase3 Analysis Pipeline (PHASE3_SPEC §C, PHASE3_MVP_PLAN)

Normalize Evidence (20%) → RAG Retrieve (55%) → Scoring + reasonText (70%) → Proposals (85%) → Callback
"""

import json
import logging
import uuid
from typing import Any, AsyncGenerator

from core.analysis.phase3_events import (
    Phase3StartedEvent,
    Phase3StepEvent,
    Phase3AgentEvent,
    Phase3CompletedEvent,
    Phase3FailedEvent,
)
from core.analysis.rag import chunk_artifacts, retrieve_rag
from core.analysis.reasoning_citations import build_regulation_citations
from core.analysis.proposal_utils import score_from_evidence, proposal_fingerprint
from core.llm import get_llm_client

logger = logging.getLogger(__name__)


def _normalize_evidence(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    """artifacts에서 evidence 목록 구성 (document 없어도 openItems/fiDocument 기반)."""
    evidence: list[dict[str, Any]] = []
    if not artifacts or not isinstance(artifacts, dict):
        return evidence

    fi = artifacts.get("fiDocument") or {}
    if isinstance(fi, dict) and fi:
        evidence.append({"key": "fiDocument", "source": "fiDocument", "summary": json.dumps(fi)[:500]})

    open_items = artifacts.get("openItems") or []
    if isinstance(open_items, list) and open_items:
        evidence.append({"key": "openItems", "source": "openItems", "count": len(open_items)})
        for i, o in enumerate(open_items[:5]):
            if isinstance(o, dict):
                evidence.append({"key": f"openItem_{i}", "source": "openItems", "item": o})

    docs = artifacts.get("documents") or []
    if isinstance(docs, list) and docs:
        evidence.append({"key": "documents", "source": "documents", "count": len(docs)})
        for i, d in enumerate(docs[:5]):
            if isinstance(d, dict):
                evidence.append({"key": f"doc_{i}", "source": "documents", "doc": d})

    line_items = artifacts.get("lineItems") or []
    if isinstance(line_items, list) and line_items:
        evidence.append({"key": "lineItems", "source": "lineItems", "count": len(line_items)})

    policies = artifacts.get("policies") or []
    if isinstance(policies, list) and policies:
        evidence.append({"key": "policies", "source": "policies", "count": len(policies)})

    return evidence[:20]


async def run_phase3_analysis(
    case_id: str,
    run_id: str,
    artifacts: dict[str, Any],
    callbacks: dict[str, Any],
    options: dict[str, Any] | None = None,
    test_fail: str | None = None,
) -> AsyncGenerator[tuple[str, dict[str, Any]], None]:
    """
    Phase3 분석 파이프라인.

    test_fail: "rag" | "llm" 이면 해당 단계에서 의도적 실패(FAILED callback + failed 이벤트).
    Yields:
        (event_type, payload) — started, step, agent, completed | failed
    """
    opts = options or {}
    top_k = int(opts.get("ragTopK", 5))
    temperature = float(opts.get("temperature", 0.2))
    prompt_version = str(opts.get("promptVersion", "phase3-mvp-v1"))
    aura_trace_id = f"aura-{run_id[:8]}-{uuid.uuid4().hex[:8]}"

    try:
        yield ("started", Phase3StartedEvent(runId=run_id, status="started").model_dump())
        yield ("step", Phase3StepEvent(label="Normalize evidence", detail="", percent=20).model_dump())

        evidence = _normalize_evidence(artifacts)
        chunks = chunk_artifacts(artifacts)
        if test_fail == "rag":
            raise RuntimeError("Simulated RAG failure (X-Aura-Test-Fail: rag)")
        rag_refs = retrieve_rag(chunks, top_k)

        yield ("step", Phase3StepEvent(label="RAG retrieve", detail="", percent=45).model_dump())
        yield ("agent", Phase3AgentEvent(agent="PolicyAgent", message="RAG 참조 완료", percent=45).model_dump())

        score = score_from_evidence(evidence)
        severity = "HIGH" if score >= 0.8 else "MEDIUM" if score >= 0.6 else "LOW"

        yield ("step", Phase3StepEvent(label="Scoring + reasonText", detail="", percent=70).model_dump())
        doc_list = (artifacts.get("documents") or []) if isinstance(artifacts.get("documents"), list) else []
        regulation_citations = build_regulation_citations(doc_list)
        reason_text = f"케이스 {case_id}: 증거 {len(evidence)}건, RAG 참조 {len(rag_refs)}건. "
        if test_fail == "llm":
            raise RuntimeError("Simulated LLM failure (X-Aura-Test-Fail: llm)")
        try:
            llm = get_llm_client()
            prompt_parts = [
                f"케이스 {case_id} 분석. 스코어 {score:.2f}, 심각도 {severity}. ",
            ]
            if regulation_citations:
                prompt_parts.append(
                    regulation_citations + "\n\n"
                    "위 참조 규정이 있으면 반드시 규정 조문(예: 규정 제5조, 제5조 2항)을 명시하여 인용하고, "
                    "구체적 사안(발생 시각·금액·경비 유형·업무 연관성 등)을 한 문장에 포함하여 작성. "
                    "예시: '규정 제5조 2항에 의거, 토요일 오후 11시에 발생한 식대는 업무 연관성이 낮아 위험군으로 분류함.' "
                )
            prompt_parts.append(
                "한국어로 2~3문장 reasonText 작성. "
                "고객이 이해할 수 있도록, 참고한 증거와 그에 따른 판단을 설명 가능한 문장으로 작성."
            )
            prompt = "".join(prompt_parts)
            resp = await llm.ainvoke(prompt)
            if resp:
                reason_text = resp.strip()
        except Exception as e:
            logger.warning("Phase3 LLM reasonText failed: %s", e)
            reason_text += f"스코어 {score:.2f}, 심각도 {severity}."

        yield ("agent", Phase3AgentEvent(agent="PolicyAgent", message=reason_text[:200], percent=70).model_dump())
        yield ("step", Phase3StepEvent(label="Propose actions", detail="", percent=80).model_dump())

        # Proposals: 룰 후보 + rationale, riskLevel, requiresApproval, checklist, fingerprint
        proposals: list[dict[str, Any]] = []
        if score >= 0.6:
            payload_hold = {
                "companyCode": "1000",
                "docKey": f"{case_id}-doc",
                "reasonCode": "POLICY_72H_VENDOR_CHANGE",
            }
            proposals.append({
                "proposalId": str(uuid.uuid4()),
                "type": "HOLD_PAYMENT",
                "status": "PROPOSED",
                "riskLevel": severity,
                "rationale": "계좌 변경 72시간 룰 위반 가능",
                "payload": payload_hold,
                "requiresApproval": True,
                "checklist": [],
                "fingerprint": proposal_fingerprint("HOLD_PAYMENT", payload_hold),
            })
        proposals.append({
            "proposalId": str(uuid.uuid4()),
            "type": "REQUEST_INFO",
            "status": "PROPOSED",
            "riskLevel": "MEDIUM",
            "rationale": "거래처 확인 요청",
            "payload": {"caseId": case_id},
            "requiresApproval": True,
            "checklist": [],
            "fingerprint": proposal_fingerprint("REQUEST_INFO", {"caseId": case_id}),
        })

        yield ("step", Phase3StepEvent(label="Callback sending", detail="", percent=95).model_dump())

        evidence_for_callback = [{"key": e.get("key", ""), "detail": e.get("source", "") or ""} for e in evidence[:10]]
        callback_payload = {
            "runId": run_id,
            "caseId": case_id,
            "status": "COMPLETED",
            "analysis": {
                "score": round(score * 100, 1),
                "severity": severity,
                "reasonText": reason_text,
                "confidenceBreakdown": {"overall": round(score, 2)},
                "evidence": evidence_for_callback,
                "ragRefs": rag_refs,
            },
            "proposals": proposals,
            "error": None,
            "trace": {"auraTraceId": aura_trace_id, "policyVersion": prompt_version},
            "meta": {
                "promptVersion": prompt_version,
                "model": "gpt-4.x",
                "temperature": temperature,
            },
        }
        yield ("_phase3_callback_payload", callback_payload)
        yield ("completed", Phase3CompletedEvent(runId=run_id, status="completed").model_dump())

    except Exception as e:
        logger.exception("Phase3 analysis failed case=%s run=%s", case_id, run_id)
        fail_stage = "rag" if test_fail == "rag" else ("llm" if test_fail == "llm" else "pipeline")
        # FAILED 콜백용 페이로드 먼저 yield (백그라운드가 전송 후 failed 이벤트 처리)
        yield ("_phase3_callback_payload", {
            "runId": run_id,
            "caseId": case_id,
            "status": "FAILED",
            "error": {"message": str(e), "stage": fail_stage},
            "proposals": [],
            "trace": {"auraTraceId": aura_trace_id, "policyVersion": prompt_version},
        })
        # FE 정합: failed 이벤트에도 error를 { message, stage } 객체로 전달 (FE에서 message 표시·stage로 재시도 안내)
        yield ("failed", {
            "runId": run_id,
            "status": "failed",
            "error": {"message": str(e), "stage": fail_stage},
            "retryable": True,
        })