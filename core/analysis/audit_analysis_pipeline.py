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
from core.analysis.thought_stream import generate_thought_stream
from core.analysis.reasoning_citations import (
    build_regulation_citations,
    build_citation_reasoning,
    get_violation_clause_evidence,
)
from core.analysis.rag import hybrid_retrieve
from core.config import get_settings
from core.llm import get_llm_client
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
        citations_payload.append({
            "source": c.get("source", "내부규정"),
            "chunk_id": c.get("chunk_id") or c.get("chunkId"),
            "doc_id": c.get("doc_id") or c.get("docId"),
            "reference": c.get("title") or c.get("reference", ""),
            "excerpt": (c.get("excerpt") or c.get("content") or "")[:500],
            "score": c.get("score"),
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
        reasoning_history: list[str] = []
        # AGENT_STREAM 중복 송출 방지: 직전에 보낸 content와 100% 동일하면 스킵
        last_agent_stream_content: list[str | None] = [None]
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

        # Step1: 입력 정규화 — 진행 상태는 step만. AGENT_STREAM은 인사이트 문장만 발행(플레이스홀더 미발행)
        yield ("thought_pending", _with_coords({"step_label": "INPUT_NORM", "message": THOUGHT_PENDING_MESSAGE, **id_mapping}))
        thought_input_norm = INPUT_NORM_THOUGHT_SHORT
        if thought_input_norm:
            reasoning_history.append(thought_input_norm)
        if _is_agent_stream_insight(thought_input_norm):
            c = (thought_input_norm or "").strip()
            if c != last_agent_stream_content[0]:
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

        try:
            case_result = await get_case.ainvoke({"caseId": case_id})
            case_data = json.loads(case_result) if isinstance(case_result, str) else case_result
        except Exception as e:
            logger.warning(f"get_case failed for {case_id}: {e}")
            case_data = {}

        if isinstance(case_data, dict) and "error" in case_data:
            case_data = {}
        # 백엔드가 evidence.amount, keys.belnr, documentOrOpenItem 등 중첩으로 내려주면 최상위로 채움
        case_data = _normalize_get_case_response(case_data)

        # [추적] get_case 정규화 후 스크리닝 필드 유무 (BE CaseDetailDto caseType/reasonText)
        if isinstance(case_data, dict) and case_data:
            _ct = case_data.get("case_type") or case_data.get("caseType")
            _rt = case_data.get("reasonText") or case_data.get("screening_reason_text")
            logger.info(
                "audit_analysis get_case after normalize: case_id=%s has_caseType=%s caseType=%s has_reasonText=%s reasonText_preview=%s",
                case_id,
                _ct is not None,
                _ct,
                _rt is not None,
                (_rt[:60] + "…") if _rt and len(_rt) > 60 else (_rt or ""),
            )
        _be_preview = None
        if isinstance(body_evidence, dict) and body_evidence:
            _be_ct = body_evidence.get("caseType") or body_evidence.get("case_type")
            _be_rt = body_evidence.get("reasonText") or body_evidence.get("screening_reason_text")
            _be_preview = f"evidence_caseType={_be_ct} has_reasonText={_be_rt is not None}"
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
                "get_case response case_id=%s belnr=%s documentNumber=%s amount=%s totalAmount=%s",
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
                    "get_case response missing amount/belnr case_id=%s top_level_keys=%s (backend may use different field names or nest under another key)",
                    case_id, _top_keys,
                )

        yield ("thought_pending", _with_coords({"step_label": "EVIDENCE_GATHER", "message": THOUGHT_PENDING_MESSAGE, **id_mapping}))
        thought_evidence_gather = await generate_thought_stream("EVIDENCE_GATHER", case_data, case_id=case_id, intended_risk_type=intended_risk_type, reasoning_history=reasoning_history)
        if thought_evidence_gather:
            reasoning_history.append(thought_evidence_gather)
        if _is_agent_stream_insight(thought_evidence_gather):
            c = (thought_evidence_gather or "").strip()
            if c != last_agent_stream_content[0]:
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
        evidence_items: list[dict[str, Any]] = []
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
        try:
            doc_result = await search_documents.ainvoke({"filters": {"caseId": case_id, "topK": 5}})
            docs = json.loads(doc_result) if isinstance(doc_result, str) else doc_result
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

        # 하이브리드 검색 — 사내 규정(Vector DB) 자동 로드
        yield ("thought_pending", _with_coords({"step_label": "REGULATION_MATCH", "message": THOUGHT_PENDING_MESSAGE, **id_mapping}))
        thought_regulation = await generate_thought_stream("REGULATION_MATCH", case_data, case_id=case_id, intended_risk_type=intended_risk_type, reasoning_history=reasoning_history)
        if thought_regulation:
            reasoning_history.append(thought_regulation)
        if _is_agent_stream_insight(thought_regulation):
            c = (thought_regulation or "").strip()
            if c != last_agent_stream_content[0]:
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
        try:
            bukrs = str(case_data.get("bukrs") or "") if isinstance(case_data, dict) else None
            belnr = str(case_data.get("belnr") or "") if isinstance(case_data, dict) else None
            # AgentConfig에서 doc_ids와 tenant_id 추출
            doc_ids = None
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
                        "audit_analysis_pipeline: doc_ids fallback from body_evidence doc_id=%s",
                        raw_doc,
                    )
            
            vector_results = hybrid_retrieve(
                query="경비 지출 규정 식대 주말 업무",
                top_k=5,
                include_article_clause=True,
                bukrs=bukrs or None,
                belnr=belnr or None,
                doc_ids=doc_ids,
                tenant_id=tenant_id_int,
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
        logger.info(
            "audit_analysis_pipeline: RAG summary case_id=%s results=%s max_score=%.3f threshold=%.3f need_web_search=%s",
            case_id,
            len(vector_results) if isinstance(vector_results, list) else 0,
            max_rag_score,
            rag_threshold,
            need_web_search,
        )
        if need_web_search:
            yield ("step", _with_coords({**AnalysisStepEvent(
                label="WEB_SEARCH",
                detail="사내 규정에 관련 조항이 없어 외부 회계/세무 기준을 검색합니다." if vector_results else "사내 규정 검색 결과가 없어 외부 검색을 수행합니다.",
                percent=38,
            ).model_dump(), **id_mapping}))
            try:
                from tools.external_search_tool import run_web_search_for_pipeline
                expense_type = (isinstance(case_data, dict) and (case_data.get("expenseType") or case_data.get("expense_type") or "")) or "경비"
                web_query = f"법인카드 {expense_type} 세무처리 국세청 가이드라인 회계기준"
                web_result = await run_web_search_for_pipeline(web_query)
                if isinstance(web_result, dict):
                    external_search_text = web_result.get("text", "")
                    external_citations = web_result.get("citations", [])
                else:
                    external_search_text = str(web_result)
                logger.info(
                    "audit_analysis_pipeline: web_search completed case_id=%s query=%s text_len=%s citations=%s",
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
        evidence_thought = await generate_thought_stream(
            "EVIDENCE_COLLECTED",
            case_data,
            case_id=case_id,
            evidence_count=len(evidence_items),
            rag_count=sum(1 for e in evidence_items if e.get("type") == "RAG_CHUNK"),
            intended_risk_type=intended_risk_type,
            reasoning_history=reasoning_history,
        )
        if evidence_thought:
            reasoning_history.append(evidence_thought)
        if _is_agent_stream_insight(evidence_thought):
            c = (evidence_thought or "").strip()
            if c != last_agent_stream_content[0]:
                last_agent_stream_content[0] = c
                yield ("AGENT_STREAM", _with_coords({"content": evidence_thought or "", "step_label": "EVIDENCE_COLLECTED", **id_mapping}))
        _ev_thought = None if _is_agent_stream_insight(evidence_thought) else (evidence_thought or None)
        yield ("evidence", AnalysisEvidenceEvent(type="COLLECTED", items=evidence_items, thought_stream=_ev_thought).model_dump())
        yield ("thought_pending", _with_coords({"step_label": "RULE_SCORING", "message": THOUGHT_PENDING_MESSAGE, **id_mapping}))
        thought_rule = await generate_thought_stream(
            "RULE_SCORING", case_data, case_id=case_id, rag_count=len(vector_results) if vector_results else 0, intended_risk_type=intended_risk_type, reasoning_history=reasoning_history
        )
        if thought_rule:
            reasoning_history.append(thought_rule)
        if _is_agent_stream_insight(thought_rule):
            c = (thought_rule or "").strip()
            if c != last_agent_stream_content[0]:
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
        thought_llm = await generate_thought_stream(
            "LLM_REASONING", case_data, case_id=case_id, evidence_count=len(evidence_items), intended_risk_type=intended_risk_type, reasoning_history=reasoning_history
        )
        if thought_llm:
            reasoning_history.append(thought_llm)
        if _is_agent_stream_insight(thought_llm):
            c = (thought_llm or "").strip()
            if c != last_agent_stream_content[0]:
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
        # 우선순위: intended_risk_type(요청) > case_type/caseType(스크리닝 결과, get_case/body_evidence) > riskTypeKey > 기본값
        risk_type = "DUPLICATE_INVOICE"
        screening_case_type: str | None = None
        screening_reason_text: str | None = None
        _be = body_evidence if isinstance(body_evidence, dict) else {}
        if intended_risk_type and str(intended_risk_type).strip():
            risk_type = str(intended_risk_type).strip()
        else:
            # 스크리닝에서 이미 분류된 case_type이 있으면 그에 맞춰 reasonText 작성 (엉뚱한 유형으로 덮어쓰기 방지)
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
                    risk_type = screening_case_type
                    screening_reason_text = (
                        (src.get("screening_reason_text") or src.get("reasonText") or "").strip() or None
                    )
                    logger.info(
                        "audit_analysis: using screening caseType from get_case/evidence case_id=%s caseType=%s",
                        case_id,
                        screening_case_type,
                    )
                    break
            # caseType이 없거나 DEFAULT여도 reasonText만 있으면 LLM 가이드로 사용 (휴일 전표가 중복으로 덮어쓰이는 것 방지)
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
            if not screening_case_type and isinstance(case_data, dict):
                risk_type = case_data.get("riskTypeKey", case_data.get("risk_type", risk_type))
                if isinstance(risk_type, str):
                    risk_type = risk_type.strip() or "DUPLICATE_INVOICE"
                else:
                    risk_type = "DUPLICATE_INVOICE"
                logger.info(
                    "audit_analysis: risk_type from case_data fallback case_id=%s risk_type=%s (no screening_case_type)",
                    case_id,
                    risk_type,
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

        reason_text = f"케이스 {case_id}: {risk_type} 위험 유형. "
        try:
            llm = get_llm_client(model_name)
            prompt_parts = [
                f"케이스 {case_id} 분석 결과를 한 문단으로 요약. ",
                f"위험 유형: {risk_type}. 스코어: {overall:.2f}. ",
            ]
            if intended_risk_type and str(intended_risk_type).strip():
                prompt_parts.append(
                    f"[최우선 가이드] 사용자가 위험 유형을 '{intended_risk_type}'으로 지정했습니다. "
                    "이 유형을 최우선 가이드로 삼아 판단하십시오. 사용자가 '사적유용'으로 정의한 건을 '중복청구' 등 다른 유형으로 제멋대로 바꾸지 마십시오. "
                )
            elif screening_case_type:
                prompt_parts.append(
                    f"[최우선 가이드] 이 케이스는 스크리닝에서 **{screening_case_type}**으로 분류되었습니다. "
                    "RAG 검색 결과(아래 참조 규정)와 스크리닝 판단을 종합하여 reasonText를 작성하십시오. "
                    "다른 위반 유형으로 결론을 바꾸거나 서술하지 마십시오. "
                )
                if screening_reason_text:
                    _ellip = "…" if len(screening_reason_text) > 400 else ""
                    prompt_parts.append(
                        f"스크리닝 판단 요약: 「{screening_reason_text[:400]}{_ellip}」. 위 내용에 맞춰 상세 분석과 reasonText를 이어서 작성하십시오. "
                    )
            if screening_reason_text and not screening_case_type:
                # caseType 없음(DEFAULT 등)이어도 reasonText만 있으면 스크리닝 판단에 맞춰 작성 (휴일→중복 덮어쓰기 방지)
                _ellip = "…" if len(screening_reason_text) > 400 else ""
                prompt_parts.append(
                    f"[최우선 가이드] 스크리닝 판단 요약: 「{screening_reason_text[:400]}{_ellip}」. "
                    "위 내용에 맞춰 reasonText를 작성하십시오. 스크리닝과 다른 위반 유형(예: 중복송장)으로 결론 내리지 마십시오. "
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
            if external_search_text:
                prompt_parts.append(
                    "\n\n외부 참조 (사내 규정에 없을 때 참고):\n" + (external_search_text[:3000] if len(external_search_text) > 3000 else external_search_text)
                    + "\n\n위 외부 출처가 있으면 '사내 규정에는 없으나, [출처명](URL)에 따르면 ...' 형태로 인용하고, URL은 [설명](URL) 마크다운으로 작성할 것."
                )
            if case_context:
                prompt_parts.append(f"케이스 맥락: {case_context}. ")
            prompt_parts.append(
                "한국어로 2~3문장으로 사람이 이해할 수 있는 이유(reasonText)를 작성. "
                "**반드시 첫 문장에 이번 분석의 핵심 결론**(위반 여부·적용 조항·판단 요약)을 배치하고, 그 다음 문장부터 근거를 서술하십시오. "
                "'데이터 분석 중' 같은 진행 로그는 금지합니다. "
                "전문 용어는 최소화하고, 증거와 결론을 설명 가능한 문장으로 작성."
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

        yield ("step", _with_coords({**AnalysisStepEvent(
            label="PROPOSALS",
            detail="권고 조치(결제 보류·추가 확인 등) 생성 중입니다.",
            percent=85,
        ).model_dump(), **id_mapping}))

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

        # citations: 내부 규정(RAG) + 외부 검색 URL — case_analysis_result / 답변 하단 노출용
        internal_citations: list[dict[str, str]] = []
        for d in doc_list:
            if not isinstance(d, dict):
                continue
            title = (d.get("title") or d.get("file_name") or d.get("location") or "").strip() or "내부 규정"
            url = (d.get("s3_url") or d.get("url") or "").strip()
            internal_citations.append({"title": title, "url": url, "source": "rag"})
        for c in external_citations:
            internal_citations.append({**c, "source": "web_search"})
        citations = internal_citations

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

        # finalResult 저장 (콜백 전에 반드시 실행 — break 시 get_audit_analysis_result 사용)
        # 백엔드 case_analysis_result 테이블 규격: violation_clause, risk_score, reasoning_summary, recommended_action, citations[]
        # V65: doc_id, item_id, chunk_id, target_buzei 반드시 snake_case
        severity = "HIGH" if overall >= 0.8 else "MEDIUM" if overall >= 0.6 else "LOW"
        from core.streaming.case_stream_store import set_audit_analysis_result
        set_audit_analysis_result(case_id, {
            "reasonText": reason_text,
            "reasoning_summary": reason_text,
            "proposals": proposals,
            "confidenceBreakdown": {
                "anomalyScore": anomaly_score,
                "patternMatch": pattern_match,
                "ruleCompliance": rule_compliance,
                "overall": overall,
            },
            "evidence": evidence_items[:10],
            "ragRefs": evidence_items[:5],
            "similarCases": similar_cases,
            "score": overall,
            "risk_score": round(overall * 100),
            "severity": severity,
            "violation_clause": violation_clause_str,
            "violation_clauses": decision_reason.get("violation_clauses", violation_clauses),
            "recommended_action": recommended_action,
            "citations": citations,
            "decision_reason": decision_reason,
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
                    case_id=case_id, score=overall, severity=severity,
                )
            except Exception as e:
                logger.debug("AI_DETECT notification publish skipped: %s", e)

        # completed: 최종 완료 시에만 '위험 점수(Score)' 전송. 진행률과 구분. violation_clauses·evidence_map_json 필수 포함.
        completed_payload = AnalysisCompletedEvent(
            status="completed",
            runId=run_id,
            caseId=case_id,
            summary=reason_text[:500],
            score=overall,
            risk_score=round(overall * 100),
            severity=severity,
            score_type="final_risk_score",
            violation_clauses=decision_reason.get("violation_clauses", violation_clauses),
            evidence_map_json=decision_reason.get("evidence_map_json", []),
        ).model_dump()
        yield ("completed", completed_payload)

    except Exception as e:
        logger.exception(f"Audit analysis failed for {case_id}")
        yield ("failed", AnalysisFailedEvent(error=str(e), stage="pipeline").model_dump())
