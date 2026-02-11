"""
규정 인용 기반 XAI reasoning용 유틸.

RAG/검색 결과 문서에서 regulationArticle, location, excerpt를 추출해
LLM 프롬프트에 넣을 "참조 규정" 블록 문자열을 만든다.
"""

from typing import Any


def build_regulation_citations(doc_list: list[dict[str, Any]]) -> str:
    """
    문서 목록에서 규정 조문 인용용 텍스트를 생성.

    각 문서에 regulationArticle, location, excerpt(또는 content)가 있으면
    "규정 제5조 2항: ..." 형태로 묶어 반환. evidence.ragContributions 및
    reasonText 프롬프트 주입용.

    Args:
        doc_list: search_documents/rag 결과 리스트. 항목은 dict이며
                  location, regulationArticle, regulationClause, excerpt, content 등 포함 가능.

    Returns:
        "참조 규정:\n- 규정 제5조 2항: 주말 식대는 원칙적으로 금지하며...\n- ..." 형태 문자열.
        규정 필드가 하나도 없으면 빈 문자열.
    """
    if not doc_list or not isinstance(doc_list, list):
        return ""

    lines: list[str] = []
    seen: set[str] = set()

    for doc in doc_list:
        if not isinstance(doc, dict):
            continue
        location = doc.get("location") or doc.get("regulationLocation")
        article = doc.get("regulationArticle") or doc.get("section")
        clause = doc.get("regulationClause") or doc.get("regulationClause")
        if not location and (article or clause):
            location = f"규정 {article or ''} {clause or ''}".strip() or None
        if not location:
            continue
        key = location
        if key in seen:
            continue
        seen.add(key)
        excerpt = (
            doc.get("excerpt")
            or doc.get("summary")
            or (doc.get("content") or "")[:300]
        )
        if isinstance(excerpt, str) and excerpt.strip():
            lines.append(f"- {location}: {excerpt.strip()[:350]}")
        else:
            lines.append(f"- {location}")

    if not lines:
        return ""
    return "참조 규정:\n" + "\n".join(lines)


def get_violation_clause_evidence(doc_list: list[dict[str, Any]], article: str, clause: str) -> dict[str, Any] | None:
    """
    위반 판정 시 evidence에 바인딩할 조문 원문을 doc_list에서 찾아 반환.

    Args:
        doc_list: RAG 검색 결과 (regulation_article, regulation_clause, content 등).
        article: 조 번호 (예: "제11조").
        clause: 항 번호 (예: "2항").

    Returns:
        {"location": "규정 제11조 2항", "excerpt": "원문 텍스트", "content": "전체 청크"} 또는 None.
    """
    if not doc_list or not isinstance(doc_list, list):
        return None
    article_norm = (article or "").strip().replace(" ", "")
    clause_norm = (clause or "").strip().replace(" ", "")
    for doc in doc_list:
        if not isinstance(doc, dict):
            continue
        a = (doc.get("regulation_article") or doc.get("regulationArticle") or "").strip().replace(" ", "")
        c = (doc.get("regulation_clause") or doc.get("regulationClause") or "").strip().replace(" ", "")
        if (article_norm and a and article_norm in a) or (not article_norm and a):
            if (not clause_norm) or (clause_norm and c and clause_norm in c):
                location = doc.get("location") or doc.get("regulationLocation")
                if not location and (a or c):
                    location = f"규정 {a or ''} {c or ''}".strip()
                content = doc.get("content") or doc.get("excerpt") or ""
                excerpt = (content[:500] if len(content) > 500 else content).strip() if content else ""
                return {
                    "location": location or f"규정 {a} {c}".strip(),
                    "excerpt": excerpt,
                    "content": content,
                }
    return None


def build_citation_reasoning(
    doc_list: list[dict[str, Any]],
    risk_level: str = "HIGH",
    *,
    default_subject: str = "본 건",
) -> str:
    """
    검색 결과에서 regulation_article, regulation_clause를 추출하여 인용형 reasoning 문장 생성.
    예: "사내 경비 규정 제5조 2항(주말 식대 제한)에 의거하여, 본 야간 결제 건은 리스크 수준 'HIGH'로 분류됨."

    Args:
        doc_list: RAG 검색 결과 (regulation_article, regulation_clause, location, title 포함 가능).
        risk_level: 리스크 수준 (HIGH, MEDIUM, LOW).
        default_subject: 규정이 없을 때 사용할 주어 (예: "본 건", "본 야간 결제 건").

    Returns:
        한 문장 인용형 reasoning.
    """
    if not doc_list or not isinstance(doc_list, list):
        return f"{default_subject}은(는) 리스크 수준 '{risk_level}'로 분류됨."
    doc = next((d for d in doc_list if isinstance(d, dict) and (d.get("regulation_article") or d.get("location"))), None)
    if not doc:
        return f"{default_subject}은(는) 리스크 수준 '{risk_level}'로 분류됨."
    location = doc.get("location") or doc.get("regulationLocation")
    article = doc.get("regulation_article") or doc.get("section")
    clause = doc.get("regulation_clause") or doc.get("regulationClause")
    if not location and (article or clause):
        location = f"규정 {article or ''} {clause or ''}".strip()
    title_short = (doc.get("title") or "")[:30]
    if title_short and "식대" in title_short:
        title_short = "주말 식대 제한"
    elif title_short and "시간" in title_short:
        title_short = "심야 시간대 제한"
    elif not title_short and location:
        title_short = location.replace("규정 ", "")[:20]
    cite = f"{location}({title_short})" if title_short else location
    return f"사내 경비 규정 {cite}에 의거하여, {default_subject}은(는) 리스크 수준 '{risk_level}'로 분류됨."
