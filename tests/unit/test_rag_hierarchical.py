"""
계층형(Hierarchical) 청킹 교차 검증 — 조/항 번호 인식 1건 이상.

FE에서 문서를 계층형으로 올렸을 때 Aura가 제대로 장/조/항을 인식하는지 검증합니다.
"""

import pytest

from core.analysis.rag import _hierarchical_chunk_text, HIERARCHICAL_DOC_TYPE


# FE 계층형 업로드 시나리오와 유사한 샘플 (제1장, 제12조, 1항, 2항)
SAMPLE_HIERARCHICAL_TEXT = """
제1장 총칙

제1조 목적
이 규정은 법인카드 및 경비 지출에 관한 사항을 정한다.

제2조 적용 범위
본 규정은 전 직원의 법인카드 사용에 적용된다.

제3장 지출

제12조 식대
1항 주말 및 공휴일 식대는 원칙적으로 인정하지 않는다.
2항 단, 업무상 불가피한 경우 사전 승인을 받은 경우에는 예외로 한다.
3항 1항 및 2항의 한도는 별도로 정한다.
"""


def test_hierarchical_chunk_recognizes_chapter_article_clause():
    """장(제1장), 조(제12조), 항(1항, 2항) 인식 및 violation_clause 메타데이터 검증."""
    chunks = _hierarchical_chunk_text(SAMPLE_HIERARCHICAL_TEXT, doc_title="운영규정", max_chunk_chars=500)
    assert len(chunks) >= 1, "계층형 청킹 결과가 1건 이상이어야 함"

    # 조(article) 또는 항(clause)이 포함된 청크가 있어야 함
    has_article = any(
        (m.get("regulation_article") or m.get("violation_clause")) for _, m in chunks
    )
    assert has_article, "regulation_article 또는 violation_clause 메타데이터가 1건 이상 있어야 함"

    # 샘플: "제12조" 또는 "1항" 인식 검증
    all_meta = [m for _, m in chunks]
    article_values = [m.get("regulation_article") for m in all_meta if m.get("regulation_article")]
    clause_values = [m.get("regulation_clause") for m in all_meta if m.get("regulation_clause")]
    violation_values = [m.get("violation_clause") for m in all_meta if m.get("violation_clause")]

    assert any("제12조" in (v or "") or "제1조" in (v or "") for v in article_values + violation_values), (
        "조 번호(제12조 등) 인식 검증"
    )
    assert any("항" in (v or "") for v in clause_values + violation_values), (
        "항 번호(1항, 2항) 인식 검증"
    )


def test_hierarchical_chunk_contextual_injection_prefix():
    """Contextual Injection: 청크 앞부분에 [doc_title > 장 > 조] 형식 접두사 존재."""
    chunks = _hierarchical_chunk_text(SAMPLE_HIERARCHICAL_TEXT, doc_title="운영규정", max_chunk_chars=800)
    assert len(chunks) >= 1
    content_first = chunks[0][0]
    assert "[운영규정]" in content_first or "제1장" in content_first or "제12조" in content_first, (
        "계층 접두사 [운영규정 > ...] 또는 장/조가 본문 앞에 포함되어야 함"
    )
