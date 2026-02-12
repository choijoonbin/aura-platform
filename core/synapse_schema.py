"""
Synapse 스키마 코드 규격 (백엔드 DB와 키값 일치)

에이전트/엔진이 사용하는 모든 구분값을 Synapse DB의 코드 정의와 동일하게 유지합니다.
"""

# ---------------------------------------------------------------------------
# DOC_TYPE (문서 타입) — RAG 청킹 방식 결정, pgvector doc_type 컬럼
# Synapse DB DOC_TYPE 코드값과 동일 문자열 사용
# ---------------------------------------------------------------------------
DOC_TYPE_REGULATION = "REGULATION"
DOC_TYPE_HIERARCHICAL = "HIERARCHICAL"
DOC_TYPE_GENERAL = "GENERAL"

# doc_type 비교 시 사용 (문자열 일치)
def is_hierarchical(doc_type: str | None) -> bool:
    return (doc_type or "").strip() == DOC_TYPE_HIERARCHICAL

def is_regulation(doc_type: str | None) -> bool:
    return (doc_type or "").strip() == DOC_TYPE_REGULATION


# ---------------------------------------------------------------------------
# model_name (LLM 엔진 식별자) — DB model_name 코드 → Aura LLM 배포명 매핑
# 백엔드 관리 코드와 일치하는 코드값만 사용
# ---------------------------------------------------------------------------
# DB model_name 코드 (백엔드 app_codes와 대소문자 일치) → LLM 배포명
MODEL_NAME_TO_ENGINE: dict[str, str] = {
    "gpt-4o-mini": "gpt-4o-mini",
    "gpt-4o": "gpt-4o",
    "gpt-4.1": "gpt-4.1",
    "gpt-4.1-mini": "gpt-4.1-mini",
    "claude-3-5-sonnet": "claude-3-5-sonnet",
    "claude-3-5-haiku": "claude-3-5-haiku",
}


def resolve_model_name(db_model_name: str | None) -> str | None:
    """DB model_name 코드 → LLM 엔진 식별자(배포명). 없으면 None(설정 기본값 사용)."""
    if not (db_model_name or "").strip():
        return None
    key = (db_model_name or "").strip()
    return MODEL_NAME_TO_ENGINE.get(key, key)
