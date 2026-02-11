# RAG Knowledge Base 메타데이터 규격 (Case 2 시나리오 매칭)

에이전트가 **Case 2(정책 위반)** 를 탐지할 때 규정 본문을 **정확히 인용**하도록 `dwp_aura.rag_document`(또는 동등 저장소) 문서 메타데이터 규격을 정의합니다.

---

## 1. 시연용 더미 데이터

- **파일**: `data/rag_document_seed.json`
- **내용**: 사내 경비 지출 규정 v1.0 (제3조, 제5조, 제7조, 제9조) 텍스트 및 메타데이터.
- **적재**: 백엔드/Synapse에서 위 JSON을 `dwp_aura.rag_document` 테이블 또는 검색 API가 반환하는 문서 형식으로 적재하면 됨.

---

## 2. 문서 메타데이터 필드 (규정 인용용)

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| **id** | string | ○ | 문서 고유 ID |
| **docKey** | string | ○ | 검색/참조 키 (예: REG-EXPENSE-v1-제5조) |
| **title** | string | △ | 규정 제목 (예: "제5조(식대)") |
| **content** | string | ○ | 규정 본문 전체 |
| **excerpt** | string | △ | 발췌문(400자 내외, 로그/UI용) |
| **regulationArticle** | string | ○ | 조 번호 (예: "제5조") |
| **regulationClause** | string | △ | 항 번호 (예: "2항") |
| **location** | string | ○ | 인용 시 표기 (예: "규정 제5조 2항") |

**인용 문장 생성 규칙**

- `location`이 있으면 reasoning에 **"규정 제5조 2항에 의거, …"** 형태로 사용.
- `location`이 없으면 `regulationArticle` + `regulationClause`로 `"규정 {article} {clause}"` 조합.

---

## 3. Scenario Matching (Case 2: 정책 위반)

- **Case 2** 예: 토요일 오후 11시 식대 → 제5조 2항(주말 식대 금지), 제7조(심야 식대 제한) 위반 후보.
- **검색**: Synapse `search_documents`(또는 RAG 검색)가 `rag_document`에서 케이스 키워드/필터로 문서를 반환할 때, 위 메타데이터가 포함되도록 저장·인덱싱.
- **에이전트**: 검색 결과의 `location`, `title`, `excerpt`를 사용해
  - **reasoning**: "규정 제5조 2항에 의거, 토요일 오후 11시에 발생한 식대는 업무 연관성이 낮아 위험군으로 분류함."
  - **evidence.ragContributions**: `location`, `title`, `excerpt` 포함하여 대시보드에 표시.

---

## 4. Aura 측 처리

- `tools/synapse_finance_tool._build_rag_contributions`: 검색 결과에서 `section`, `clause`, `location`, `title`을 읽어 `ragContributions`에 넣음.
- `core/analysis`: 문서 목록에서 `regulationArticle`, `regulationClause`, `location`, `content`/`excerpt`를 추출해 LLM reasonText 프롬프트에 "참조 규정" 블록으로 주입 → 인용형 문장 생성.

백엔드가 `rag_document` 적재 시 위 필드를 채우면, 에이전트는 별도 수정 없이 규정 인용 reasoning을 생성할 수 있습니다.
