from core.config import get_settings
from core.analysis.rag import (
    _run_chunk_quality_gate,
    _extract_document_standard_meta,
    _expand_hierarchical_with_subchunks,
)


def test_quality_gate_removes_noise_heading_and_duplicates():
    settings = get_settings()
    prepared = [
        {"content": "", "metadata": {}},
        {"content": "[문서 > 제1장 총칙] 제1장 총칙", "metadata": {}},
        {"content": "제7조 주말 및 공휴일 식대 지출은 원칙적으로 금지한다.", "metadata": {}},
        {"content": "제7조 주말 및 공휴일 식대 지출은 원칙적으로 금지한다.", "metadata": {}},
        {"content": "문서ID 6c8c438f-8074-4e7b-913c-62ea0c482d98 정보", "metadata": {}},
    ]
    out = _run_chunk_quality_gate(
        prepared,
        rag_document_id="23",
        base_meta={"tenant_id": 1, "title": "규정집"},
        doc_type="REGULATION",
        settings_obj=settings,
    )
    assert out["ok"] is True
    assert out["report"]["removed_empty"] >= 1
    assert out["report"]["removed_heading_only"] >= 1
    assert out["report"]["removed_duplicate_exact"] >= 1
    assert out["report"]["final_chunks"] >= 1
    assert "noise_rate" in out["report"]
    assert "noise_sanitize_rate" in out["report"]
    assert "duplicate_rate" in out["report"]
    assert "short_chunk_rate" in out["report"]


def test_quality_gate_enriches_required_metadata():
    settings = get_settings()
    prepared = [
        {"content": "제39조 주말 공휴일 지출은 제한 대상이다.", "metadata": {}},
    ]
    out = _run_chunk_quality_gate(
        prepared,
        rag_document_id="26",
        base_meta={"tenant_id": 1, "title": "재무규정집"},
        doc_type="REGULATION",
        settings_obj=settings,
    )
    assert out["ok"] is True
    c0 = out["chunks"][0]["metadata"]
    assert c0["doc_id"] == "26"
    assert c0["tenant_id"] == 1
    assert c0["regulation_article"] == "제39조"
    assert c0["location"]


def test_quality_gate_strict_fails_when_no_valid_chunk():
    settings = get_settings()
    prepared = [
        {"content": "", "metadata": {}},
        {"content": "[문서 > 제1장 총칙] 제1장 총칙", "metadata": {}},
    ]
    out = _run_chunk_quality_gate(
        prepared,
        rag_document_id="99",
        base_meta={"tenant_id": 1, "title": "규정"},
        doc_type="REGULATION",
        settings_obj=settings,
    )
    assert out["ok"] is False
    assert "NO_VALID_CHUNKS_AFTER_QUALITY_GATE" in out["report"]["errors"]


def test_extract_document_standard_meta_from_text():
    text = "문서버전: v2.3\n시행예정일: 2026-03-01\n"
    out = _extract_document_standard_meta(text, {})
    assert out["version"] == "v2.3"
    assert out["effective_from"] == "2026-03-01"


def test_expand_hierarchical_with_subchunks_adds_parent_child_link():
    src = [
        (
            "[규정집 > 제39조 (주말·공휴일 제약)] 제39조 (주말·공휴일 제약)\n① 주말 지출 제한\n② 공휴일 지출 제한\n③ 반복 지출 위험 상향",
            {"regulation_article": "제39조", "location": "규정집 > 제39조"},
        )
    ]
    out = _expand_hierarchical_with_subchunks(
        src,
        doc_title="규정집",
        sub_size=40,
        sub_overlap=5,
        min_chars=20,
    )
    assert len(out) >= 1
    _, meta = out[0]
    assert meta.get("parent_chunk_id")
    assert meta.get("parent_article") == "제39조"
