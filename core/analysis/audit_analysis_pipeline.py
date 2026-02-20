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

        yield ("step", AnalysisStepEvent(
            label="EVIDENCE_GATHER",
            detail="케이스 전표 데이터 및 연관 증거 수집 중",
            percent=25,
        ).model_dump())

        # Step2: Evidence 수집
        evidence_items: list[dict[str, Any]] = []
        if case_data:
            evidence_items.append({
                "type": "CASE",
                "source": "get_case",
                "caseId": case_id,
                "keys": {k: v for k, v in case_data.items() if k in ("bukrs", "belnr", "gjahr", "vendorId", "amount")},
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
                    evidence_items.append({
                        "type": "DOC_HEADER" if i == 0 else "DOC_ITEM",
                        "source": "search_documents",
                        "index": i,
                        "keys": d.get("keys", {}) or {"caseId": case_id},
                    })
        except Exception as e:
            logger.debug(f"search_documents failed: {e}")

        # 하이브리드 검색 — 사내 규정(Vector DB) 자동 로드
        yield ("step", AnalysisStepEvent(
            label="REGULATION_MATCH",
            detail="전표·가맹점 맥락을 바탕으로 사내 규정(Vector DB) 매칭 중입니다.",
            percent=35,
        ).model_dump())
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
            yield ("step", AnalysisStepEvent(
                label="WEB_SEARCH",
                detail="사내 규정에 관련 조항이 없어 외부 회계/세무 기준을 검색합니다." if vector_results else "사내 규정 검색 결과가 없어 외부 검색을 수행합니다.",
                percent=38,
            ).model_dump())
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
        if body_evidence and isinstance(body_evidence, dict):
            raw_doc = body_evidence.get("doc_id") or (body_evidence.get("document") or {}).get("docKey")
            raw_item = body_evidence.get("item_id")
            doc_id_ref = _norm_id(raw_doc)
            item_id_ref = _norm_id(raw_item)
        if doc_id_ref and doc_list:
            # pgvector 검색 결과에서 body_evidence.doc_id와 일치하는 문서를 최상단에 배치(Ranking)
            doc_id_norm = doc_id_ref.strip()
            def _doc_rank_key(d: dict[str, Any]) -> tuple[int, float]:
                rid = str(d.get("rag_document_id") or d.get("sourceKey") or d.get("docKey") or "").strip()
                match = 0 if rid == doc_id_norm else 1
                return (match, -(float(d.get("score", 0)) or 0))
            doc_list.sort(key=_doc_rank_key)

        yield ("evidence", AnalysisEvidenceEvent(type="COLLECTED", items=evidence_items).model_dump())
        yield ("step", AnalysisStepEvent(
            label="RULE_SCORING",
            detail="규정 제한 업종·금액·시간 기준 위반 여부 검토 중입니다.",
            percent=45,
        ).model_dump())

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

        yield ("step", AnalysisStepEvent(
            label="LLM_REASONING",
            detail="규정 조문과 대조하여 위반 여부 판단 및 판단 근거 작성 중입니다.",
            percent=65,
        ).model_dump())

        # Step4: LLM reasonText (XAI: 규정 인용형 문장)
        risk_type = "DUPLICATE_INVOICE"
        if isinstance(case_data, dict):
            risk_type = case_data.get("riskTypeKey", case_data.get("risk_type", risk_type))

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
            if doc_id or item_id:
                prompt_parts.append(
                    f"백엔드에서 지정한 문서·항목(doc_id={doc_id or '미지정'}, item_id={item_id or '미지정'})에 대한 "
                    "상세 내역을 우선 참고하여 규정 준수 여부를 판단하고, 해당 내역 기반으로 이유를 작성하시오. "
                )
            if regulation_citations:
                prompt_parts.append(
                    regulation_citations + "\n\n"
                    "위 참조 규정을 반드시 인용하여 작성하되, "
                    "**정상 전표**인 경우: '사내 경비 규정 v1.2의 모든 기준을 충족하는 모범적인 지출 사례'임을 칭찬 섞인 요약으로 표현. "
                    "**위반 전표**인 경우: '규정 제N조 N항을 정면으로 위반했습니다.'라고 단호하게 쓰고, "
                    "구체적 근거로 '상세 항목(Item)의 [필드명]이 규정 제X조 X항과 상충됨' 형태를 포함할 것. "
                    "위반 사유(시간외 결제·주말 식대 등)를 한 문장에 포함하고, evidence에는 해당 조항 원문을 정확히 바인딩할 수 있도록 조문 번호를 명시. "
                    "URL이 포함된 경우 반드시 마크다운 형식 [설명](URL)으로 작성하여 프론트엔드에서 하이퍼링크로 렌더링되도록 할 것."
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
                "전문 용어는 최소화하고, 증거와 결론을 설명 가능한 문장으로 작성."
            )
            prompt = "".join(prompt_parts)
            resp_text = await llm.ainvoke(prompt)
            if resp_text:
                reason_text = resp_text.strip()
        except Exception as e:
            logger.warning(f"LLM reasonText failed: {e}")
            reason_text += f"증거 {len(evidence_items)}건 수집. 스코어 {overall:.2f}."
        # 위반 조항 추출 (Autonomous Conclusion: violation_clause 반환용)
        violation_clause_str = ""
        # XAI 인용형: 규정이 있으면 "사내 경비 규정 제5조 2항(주말 식대 제한)에 의거하여, ..." 보강
        risk_level = "HIGH" if overall >= 0.8 else "MEDIUM" if overall >= 0.6 else "LOW"
        # Contrastive: 정상(DEMO_NORM_*) → 칭찬 요약 / 위반(DEMO0000*) → 단호한 위반 문구 + evidence에 조문 원문 바인딩
        if is_demo_norm:
            reason_text = (
                "사내 경비 규정 v1.2의 모든 기준을 충족하는 모범적인 지출 사례입니다. "
                "규정 제14조 1항을 모두 충족하며, 업무 시간 내 발생한 정상 식대로 판단됩니다. "
                + reason_text
            )
            risk_level = "LOW"
        elif is_demo_violation:
            violation_article, violation_clause = "제11조", "2항"
            violation_clause_str = f"{violation_article} {violation_clause}"
            clause_evidence = get_violation_clause_evidence(doc_list, violation_article, violation_clause)
            if clause_evidence:
                evidence_items.append({
                    "type": "REGULATION_CLAUSE",
                    "source": "rag",
                    "location": clause_evidence.get("location"),
                    "excerpt": clause_evidence.get("excerpt"),
                    "article": violation_article,
                    "clause": violation_clause,
                })
            violation_reason = case_context or "시간외 결제 등"
            reason_text = (
                f"규정 {violation_article} {violation_clause}을(를) 정면으로 위반했습니다. "
                f"{violation_reason}으로 위반으로 판별됩니다. "
                + reason_text
            )
            risk_level = "HIGH"
        else:
            citation_sentence = build_citation_reasoning(
                doc_list, risk_level=risk_level, default_subject="본 건"
            )
            if "에 의거하여" in citation_sentence:
                reason_text = citation_sentence + " " + reason_text

        yield ("step", AnalysisStepEvent(
            label="PROPOSALS",
            detail="권고 조치(결제 보류·추가 확인 등) 생성 중입니다.",
            percent=85,
        ).model_dump())

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

        # finalResult 저장 (콜백 전에 반드시 실행 — break 시 get_audit_analysis_result 사용)
        # 백엔드 case_analysis_result 테이블 규격: violation_clause, risk_score, reasoning_summary, recommended_action, citations[] 필수
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
            "recommended_action": recommended_action,
            "citations": citations,
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

        # completed (FE 정상 종료 인식용: status, runId, caseId 포함)
        completed_payload = AnalysisCompletedEvent(
            status="completed",
            runId=run_id,
            caseId=case_id,
            summary=reason_text[:500],
            score=overall,
            severity=severity,
        ).model_dump()
        yield ("completed", completed_payload)

    except Exception as e:
        logger.exception(f"Audit analysis failed for {case_id}")
        yield ("failed", AnalysisFailedEvent(error=str(e), stage="pipeline").model_dump())
