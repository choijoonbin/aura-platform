"""
규정 인용 기반 XAI reasoning용 유틸.

RAG/검색 결과 문서에서 regulationArticle, location, excerpt를 추출해
LLM 프롬프트에 넣을 "참조 규정" 블록 문자열을 만든다.
"""

import re
from typing import Any

_ARTICLE_LOC_PATTERN = re.compile(r"(제\s*\d+\s*조(?:\s*제\s*\d+\s*항)?)")
_UUID_LIKE_PATTERN = re.compile(r"[0-9a-fA-F]{8,}(?:-[0-9a-fA-F]{4,}){2,}")


def _humanize_location(location: Any, *, article: Any = None, clause: Any = None) -> str:
    loc = str(location or "").strip()
    if loc:
        m = _ARTICLE_LOC_PATTERN.search(loc)
        if m:
            return f"규정 {m.group(1).replace(' ', '')}"
    a = str(article or "").strip()
    c = str(clause or "").strip()
    if a or c:
        return f"규정 {a} {c}".strip()
    return "규정"


def _humanize_title(doc: dict[str, Any]) -> str:
    for key in ("title", "file_name", "fileName"):
        v = str(doc.get(key) or "").strip()
        if not v:
            continue
        v = _UUID_LIKE_PATTERN.sub("", v)
        v = re.sub(r"[_\-]{3,}", " ", v).strip(" _-.")
        # 내부 UUID/path 노출 제거
        if re.fullmatch(r"[0-9a-fA-F\-]{24,}", v):
            continue
        if not v:
            continue
        if ">" in v:
            parts = [p.strip() for p in v.split(">") if p.strip()]
            if parts:
                v = parts[-1]
        v = re.sub(r"\.(txt|md|pdf)$", "", v, flags=re.IGNORECASE).strip()
        if v.lower() in {"txt", "md", "pdf", "file"}:
            continue
        if len(v) > 60:
            v = v[:60]
        return v
    return "내부 규정"


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
        location = _humanize_location(location, article=article, clause=clause)
        if not location:
            continue
        key = location
        if key in seen:
            continue
        seen.add(key)
        # 출처 형식: [내부규정: 파일명 p.N] — LLM이 답변 시 동일 형식 사용 유도
        file_name = _humanize_title(doc)
        page_number = doc.get("page_number") if doc.get("page_number") is not None else doc.get("pageNumber")
        citation_prefix = ""
        if file_name or page_number is not None:
            p_str = f" p.{int(page_number)}" if page_number is not None else ""
            citation_prefix = f"[내부규정: {file_name or '내부 규정'}{p_str}] "
        excerpt = (
            doc.get("excerpt")
            or doc.get("summary")
            or (doc.get("content") or "")[:300]
        )
        if isinstance(excerpt, str) and excerpt.strip():
            lines.append(f"- {citation_prefix}{location}: {excerpt.strip()[:350]}")
        else:
            lines.append(f"- {citation_prefix}{location}")

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
                location = _humanize_location(
                    doc.get("location") or doc.get("regulationLocation"),
                    article=a,
                    clause=c,
                )
                content = doc.get("content") or doc.get("excerpt") or ""
                excerpt = (content[:500] if len(content) > 500 else content).strip() if content else ""
                return {
                    "location": location or _humanize_location(None, article=a, clause=c),
                    "excerpt": excerpt,
                    "content": content,
                    "doc_id": doc.get("doc_id") or doc.get("docId") or doc.get("rag_document_id"),
                    "chunk_id": doc.get("chunk_id") or doc.get("chunkId"),
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
    RAG 검색 결과(doc_list)의 location, title, excerpt만 사용하며 고정 문구는 사용하지 않음.

    Args:
        doc_list: RAG 검색 결과 (regulation_article, regulation_clause, location, title 포함 가능).
        risk_level: 리스크 수준 (HIGH, MEDIUM, LOW).
        default_subject: 규정이 없을 때 사용할 주어 (예: "본 건", "본 야간 결제 건").

    Returns:
        한 문장 인용형 reasoning.
    """
    if not doc_list or not isinstance(doc_list, list):
        return f"{default_subject}의 규정 적합성을 검토한 결과를 제시합니다."
    doc = next((d for d in doc_list if isinstance(d, dict) and (d.get("regulation_article") or d.get("location"))), None)
    if not doc:
        return f"{default_subject}의 규정 적합성을 검토한 결과를 제시합니다."
    location = _humanize_location(
        doc.get("location") or doc.get("regulationLocation"),
        article=doc.get("regulation_article") or doc.get("section"),
        clause=doc.get("regulation_clause") or doc.get("regulationClause"),
    )
    article = doc.get("regulation_article") or doc.get("section")
    clause = doc.get("regulation_clause") or doc.get("regulationClause")
    title_short = (_humanize_title(doc) or "").strip()[:50]
    if not title_short and location:
        title_short = location.replace("규정 ", "")[:30]
    cite = f"{location}({title_short})" if title_short else (location or "규정")
    return f"{cite}에 의거하여, {default_subject}의 규정 적합성을 판단했습니다."
