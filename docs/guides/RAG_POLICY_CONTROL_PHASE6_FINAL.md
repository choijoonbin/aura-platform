# Policy-Driven Reasoning & Control Data Validation (Phase 6 - Final)

## 1. Knowledge-Base Alignment

- **제5장(부정 탐지), 제6장(정상 집행 기준) 최우선 참조**  
  - pgvector 검색 시 `prioritize_chapters=("제5장", "제6장")` 적용.  
  - 업로드 시 메타데이터에 `chapter`(예: "제5장", "제6장")를 넣어 두면 해당 청크가 유사도 순 정렬보다 먼저 온다.  
  - `rag_chunk.metadata_json` 예: `{"chapter": "제5장", "section": "부정 탐지"}`.

- **similarity_threshold >= 0.75**  
  - `retrieve_rag_pgvector(..., similarity_threshold=0.75)` (기본값).  
  - 설정: `core/config.py` → `rag_similarity_threshold` (기본 0.75).  
  - 유사도가 이 값 미만인 결과는 반환하지 않아 무관한 규정 인용을 줄인다.

## 2. Contrastive Analysis (정상 vs 위반)

- **정상 전표 (DEMO_NORM_*)**  
  - `case_id`가 `DEMO_NORM_`로 시작하면:  
    - overall 스코어 상한 0.45, risk_level = **LOW**.  
    - reasoning 앞에 **"사내 경비 규정 v1.2의 모든 기준을 충족하는 모범적인 지출 사례입니다. 규정 제14조 1항을 모두 충족하며, 업무 시간 내 발생한 정상 식대로 판단됩니다."** 칭찬 섞인 요약 추가.

- **위반 전표 (DEMO0000*)**  
  - `case_id`가 `DEMO0000`으로 시작하면:  
    - overall 스코어 하한 0.82, risk_level = **HIGH**.  
    - reasoning 앞에 **"규정 제11조 2항을(를) 정면으로 위반했습니다. {구체 사유}으로 위반으로 판별됩니다."** 단호한 문구 추가 (사유는 case_context 또는 "시간외 결제 등").
  - **evidence 바인딩**: RAG 검색 결과에서 해당 조문 원문을 찾아 `evidence`에 `REGULATION_CLAUSE` 타입으로 `location`, `excerpt`, `article`, `clause` 포함.

- **프롬프트**  
  - LLM reasonText: 정상 건은 '사내 경비 규정 v1.2의 모든 기준을 충족하는 모범적인 지출 사례' 칭찬 요약, 위반 건은 '규정 제N조 N항을 정면으로 위반했습니다.' 단호 표현 및 evidence에 조항 원문 정확히 바인딩 지시.

## 3. Backend Integration (콜백 전송 로직)

- **설정**: `core/config.py` → `backend_rag_callback_url` (예: `http://localhost:8080/api/synapse/rag`).
- **호출 시점**: `process_and_vectorize_pgvector` 성공 직후 `_notify_backend_rag_completed(doc_id)` 호출.
- **HTTP**: `POST {backend_rag_callback_url}/rag/documents/{doc_id}/processing-status`  
  - Body: `{"processing_status": "COMPLETED", "doc_id": "<doc_id>"}`.  
- **Backend (RagController)**: 위 URL 수신 후 해당 문서의 `processing_status`를 'COMPLETED'로 갱신.

## 4. Remove Filename Hardcoding & Metadata Filtering

- **파일명 미사용**: 에이전트는 '규정집.txt' 등 특정 파일명을 검색하지 않는다.
- **규정만 검색 (격리 강화)**: `retrieve_rag_pgvector` / `hybrid_retrieve` 호출 시 **`doc_type_filter="REGULATION"`** (상수 `FINANCE_REGULATION_DOC_TYPE`) 사용.  
  - pgvector: `dwp_aura.rag_chunk.doc_type = 'REGULATION'` 인 행만 검색하여 **일반 매뉴얼(doc_type='GENERAL')이 회계 규정 분석에 혼입되지 않도록** 격리.
  - `hybrid_retrieve(..., doc_type_filter=...)` 파라미터로 업로드된 파일의 doc_type을 전달 가능. Phase2에서는 항상 `FINANCE_REGULATION_DOC_TYPE` 사용.
  - 사용자가 지정한 `doc_id`(규정 문서 ID)로 추가 필터가 필요하면 `metadata_filter`로 전달.
- **적재 시**: 업로드/벡터화 시 `doc_type='REGULATION'` 또는 규정용 `doc_id`를 설정하면, 파일명과 무관하게 시스템에 등록된 유효 규정만 참조된다.
