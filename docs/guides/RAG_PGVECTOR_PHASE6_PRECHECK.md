# RAG pgvector Pipeline (Phase 6) — Pre-Check 답변

## 1. pgvector 연결을 위한 SQLAlchemy URI

- **답**: **예**. `core/config.py`에 이미 `database_url`(PostgreSQL)이 정의되어 있습니다.
- `database_url`: `postgresql://user:password@localhost:5432/aura_platform` (기본값).
- **조치**: pgvector 확장이 적용된 동일 PostgreSQL 인스턴스(`pgvector/pgvector:pg15`)를 사용하면, **별도 URI 없이** 기존 `database_url`로 pgvector 사용 가능. 스키마 `dwp_aura` 및 테이블 `rag_chunk`는 Aura에서 생성/마이그레이션으로 관리.

## 2. OpenAI API Key 및 임베딩

- **답**: **예**. `.env`에 `OPENAI_API_KEY` 또는 Azure(`AZURE_OPENAI_*`) 설정 시, `core/analysis/rag.py`의 `_get_embedding_client()`가 OpenAI/Azure Embedding을 사용하며, `text-embedding-3-small`(1536 dim) 모델로 임베딩 생성이 가능합니다.
- 설정은 `openai_embedding_model`, `azure_openai_embedding_deployment`(선택)로 제어됩니다.

## 3. 회계 규정 vs 일반 문서 검색 가중치

- **답**: **현재 구현에는 구분 없음**. 요구사항에서 “회계 규정”과 “일반 문서”를 구분해 검색 가중치를 다르게 할 **계획**이면, `rag_chunk`에 `doc_type`(예: `REGULATION` | `GENERAL`) 메타데이터를 두고, `retrieve_rag` 시 `doc_type=REGULATION`인 결과에 가중치를 곱하거나 우선 정렬하도록 확장할 수 있습니다. Phase 6 기본 구현에서는 `doc_type` 컬럼을 추가해 두고, 가중치 로직은 선택적으로 적용합니다.

---

이후 pgvector 연동 및 로그 고도화 수정 코드를 적용합니다.
