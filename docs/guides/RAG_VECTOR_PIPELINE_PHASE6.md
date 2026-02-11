# RAG Vector Pipeline (Phase 6) — Pre-Check & 설계

## Pre-Check (MUST ANSWER BEFORE CODING)

### 1. 벡터 DB 엔진 식별

- **소스 코드 검색 결과**: 프로젝트 내에 **Pinecone, Chroma, Milvus 등 벡터 DB 사용처가 없음**.  
  `.cursorrules` 및 아키텍처 문서에는 **Pinecone (Hybrid Search)** 가 명시되어 있으나, 현재 구현은 `core/analysis/rag.py`의 in-memory 청킹 + `retrieve_rag`(topK 선택)만 존재하며, Synapse `search_documents` API가 외부 검색을 담당함.
- **결정**:  
  - **1순위(프로덕션)**: **Pinecone** — 아키텍처 정합성, Hybrid Search 지원.  
  - **2순위(로컬/CI)**: **Chroma** — 추가 인프라 없이 파일 기반/메모리 저장 가능.  
  - 구현 시 **벡터 스토어 추상화**를 두어, 설정에 따라 Chroma 또는 Pinecone을 선택하도록 함.  
  - 선택적 의존성: `langchain-chroma`, `chromadb`(로컬), `pinecone-client` + `langchain-pinecone`(운영).

### 2. 파일 업로드 후 벡터화 처리 방식

- **현재**: 파일 업로드 API 및 백그라운드 워커(Celery/BackgroundTasks) **미구현**.
- **결정**: **FastAPI `BackgroundTasks`** 로 벡터화 처리.  
  - 이유: Celery는 Redis/브로커 등 인프라가 필요하므로 Phase 6 범위에서는 `BackgroundTasks`로 충분.  
  - 업로드 API: `POST /api/aura/rag/ingest` — 파일 수신 → 임시 저장 → `BackgroundTasks.add_task(process_and_vectorize, ...)` → 202 Accepted + `job_id`(또는 `task_id`) 반환.  
  - 필요 시 추후 Celery/Redis Queue로 전환 가능하도록 `process_and_vectorize` 시그니처를 유지.

---

## Task 1: Vector Ingestion Pipeline

- **위치**: `core/analysis/rag.py`  
- **함수**: `process_and_vectorize(file_path, rag_document_id, metadata, *, chunk_size, chunk_overlap)`  
  - PDF/Text 파일 읽기 → **LangChain CharacterTextSplitter** 로 청킹 → **OpenAI/Azure Embedding** → 벡터 스토어 저장.  
  - 각 청크 메타데이터에 `rag_document_id`, `regulation_article`, `regulation_clause`, `location` 등 포함 → `dwp_aura.rag_document` 테이블 ID와 벡터 DB 내부 ID 매핑 유지 (메타데이터 필드 `rag_document_id`로 조회 가능).

## Task 2: Hybrid Search

- **에이전트** `get_lineage` / `analyze` 호출 시:  
  - **키워드 검색**: 메타데이터 필터(article, clause, doc_key 등).  
  - **벡터 검색**: 쿼리 임베딩 유사도.  
  - **병합**: 점수/가중치로 merge 후, **인용 정보(Article/Clause/location)** 가 누락되지 않도록 모든 히트에 메타데이터 강제 포함.  
- Synapse `search_documents` 결과와 Aura 벡터 검색 결과를 병합할 수 있도록, 파이프라인/도구 레이어에서 `hybrid_retrieve` 호출 후 evidence에 반영.

---

## API 명세 (구현)

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/aura/rag/ingest` | 파일 업로드(PDF/.txt/.md) + Form: `rag_document_id`, `metadata`(JSON 문자열) → BackgroundTasks 벡터화 → **202 Accepted** + `job_id`, `rag_document_id` |

### POST /api/aura/rag/ingest

- **Request**: `multipart/form-data`
  - `file` (required): PDF 또는 .txt, .md 파일
  - `rag_document_id` (optional): dwp_aura.rag_document 테이블 문서 ID. 미지정 시 `rag-{uuid}` 자동 생성
  - `metadata` (optional): JSON 문자열. 규정 인용용 메타데이터 예: `{"regulation_article":"제5조","regulation_clause":"2항","location":"규정 제5조 2항","title":"사내 경비 지출 규정 v1.0"}`
- **Response**: 202 Accepted
  - `job_id`: 백그라운드 작업 식별자
  - `rag_document_id`: 벡터 스토어에 저장 시 사용된 문서 ID
  - `message`: "Vectorization started in background"

벡터화는 FastAPI `BackgroundTasks`로 실행되며, 완료 후 임시 파일은 자동 삭제됩니다. 상태 조회 API는 선택 구현(현재 미구현).

---

## 구현 요약

- **Config**: `core/config.py` — `openai_embedding_model`, `azure_openai_embedding_deployment`, `vector_store_type`(chroma|pinecone|none), `chroma_persist_dir`, `chroma_collection_name`, `pinecone_*`
- **RAG**: `core/analysis/rag.py` — `process_and_vectorize()`, `hybrid_retrieve()`, `get_vector_store()`, `_get_embedding_client()`
- **Phase2**: `core/analysis/phase2_pipeline.py` — `search_documents` 결과에 `hybrid_retrieve()` 병합, Article/Clause 메타데이터 보존
- **API**: `api/routes/aura_rag.py` — POST `/api/aura/rag/ingest`
- **의존성**: `poetry install --with rag` (pypdf, langchain-text-splitters, chromadb, langchain-chroma)
