# RAG 청크 연동 체크리스트 (Aura ↔ Backend)

백엔드 Batch Insert 및 DTO 작업 시, Aura 전달 형식과 맞춰 확인할 항목입니다.  
**백엔드가 먼저 전달한 연동 맞춤 문서(예: back.txt)와 함께 확인용으로 사용**하시면 됩니다.

---

## 0. 백엔드 연동 문서(back.txt)와의 정합

| 항목 | 백엔드 문서 기대 | Aura 현재 전송 | 조치 |
|------|------------------|----------------|------|
| **콜백/저장 URL** | `POST {gateway}/api/synapse/rag/status` 에 chunks 포함 | Aura는 `BACKEND_RAG_CHUNKS_SAVE_URL`로 배치마다 POST. **동일 URL로 설정**하면 연동 가능 (예: 해당 status URL을 save_url로 설정) | URL을 백엔드 제공 status URL로 맞추면 됨 |
| **요청 body 최상위** | docId, status, message, chunks | rag_document_id, chunks, batch_index, total_batches | 백엔드가 **chunks만** 쓰는 경우 현재 형식으로 수신 가능한지 확인. 필요 시 Aura에서 docId/status 포함해 전송하도록 조정 가능 |
| **청크 본문 필드명** | **chunk_content** (또는 chunkContent) | **content** | **협의 필요**: 백엔드 DTO에 `@JsonAlias("content")` 추가하거나, Aura에서 저장 API 호출 시 필드명을 **chunk_content**로 보내도록 변경 |
| **메타데이터** | metadata_json (object), page_no 추출 | metadata (object), metadata.page_number | 백엔드가 page_number → page_no 추출 구현됨 ✓ |
| **embedding** | 1536차원 float[] | 1536차원 number[] | 동일 ✓ |

위 항목만 맞추면 백엔드 문서와 Aura 체크리스트가 서로 보완 관계로 사용됩니다.

---

## 1. 필드 매핑 (Aura → Backend DB)

Aura가 보내는 청크 항목과 백엔드 `rag_chunk` INSERT 컬럼 매핑입니다.

| Aura 전달 키 | 타입 | Backend DB 컬럼 | 비고 |
|--------------|------|-----------------|------|
| `chunk_index` | number | `chunk_index` | 그대로 사용. 순서 보장에 사용 ✓ |
| `content` | string | `chunk_text` | **키 이름 상이** → DTO에서 `content` 수신 후 `chunk_text`로 매핑 |
| `embedding` | number[] (1536) | `embedding` (vector) | float[] → PGvector 변환은 백엔드에서 수행 |
| `metadata` | object | `metadata_json` | 전체 객체를 JSON 문자열로 저장. `page_no` 추출 시 아래 참고 |
| (metadata 내부) `metadata.page_number` | number | `page_no` | 별도 컬럼이 있으면 여기서 채우기 |
| (요청 body) `rag_document_id` | string | `doc_id` (Long) | 백엔드가 문자열→Long 변환 또는 URL path의 docId 사용 |

- **요약**: 수신 DTO는 Aura가 보내는 **snake_case** 그대로 두는 것이 안전합니다.  
  - `chunkIndex`(camelCase)가 아니라 **`chunk_index`**  
  - `content` (본문), **`chunk_text`는 DB 컬럼명이므로** INSERT 시에만 사용하고, API 수신 필드는 `content`로 받거나 `@JsonProperty("content")`로 매핑 후 서비스에서 `chunk_text`에 넣으면 됩니다.

---

## 2. 수신 body 형식 (Aura가 저장 URL로 POST할 때)

Aura가 `BACKEND_RAG_CHUNKS_SAVE_URL`로 보내는 body는 다음과 같습니다.

```json
{
  "rag_document_id": "문서 UUID 또는 식별자 (string)",
  "chunks": [
    {
      "chunk_index": 0,
      "content": "청크 원문 텍스트",
      "embedding": [ 0.013, -0.018, ... ],
      "metadata": {
        "doc_id": "문서 ID",
        "chunk_index": 0,
        "page_number": 1,
        "file_path": "/absolute/path/to/file.pdf",
        "regulation_article": "제5조",
        "regulation_clause": null,
        "location": "규정 제5조",
        "title": null,
        "doc_type": "REGULATION"
      }
    }
  ],
  "batch_index": 0,
  "total_batches": 5
}
```

- **확인 사항**
  - 수신 DTO가 위 **snake_case** 키를 그대로 받을 수 있는지 (`chunk_index`, `rag_document_id`, `batch_index`, `total_batches`, `content`, `embedding`, `metadata`).
  - 전역 ObjectMapper가 camelCase로 직렬화해도, **요청 body 역직렬화** 시에는 Aura가 snake_case로 보내므로 snake_case 필드명 또는 `@JsonProperty`로 수신해야 합니다.

---

## 3. 배치 단위 정합성

- Aura: 한 번에 **20~50개** 단위로 잘라서 전달(또는 저장 API 반복 호출).
- Backend: INSERT 시 **500건 단위** `batchUpdate` 사용 → **동일 문서에 대해 여러 번 요청이 오면** (예: Aura가 30개씩 5번 POST) 각 요청의 `chunks`를 순서대로 모은 뒤 500건 단위로 나눠 INSERT하면 됩니다.
- **순서**: `chunk_index`를 그대로 사용하고, 리스트 순서를 바꾸지 않으면 됩니다. (백엔드에서 이미 반영 ✓)

---

## 4. embedding (float[] → PGvector)

- Aura: **순수 JSON 배열** `[0.013, -0.018, ...]` (1536차원). DB 문법 없음.
- Backend: `PreparedStatement`에서 float[] 또는 List<Double>을 PGvector 타입으로 바인딩해야 합니다.
  - JDBC/드라이버에 따라 `ps.setObject(..., pgVectorObject)` 또는 문자열 `"[0.1,0.2,...]"` + `?::vector` 등 방식이 있을 수 있음.
- **확인**: 1536차원 고정인지, 백엔드 스키마 `vector(1536)`와 일치하는지 한 번만 확인하면 됩니다.

---

## 5. tenant_id / doc_id (Long)

- Aura는 **`rag_document_id`(string)** 만 전달합니다. `tenant_id`는 전달하지 않습니다.
- **확인**: `tenant_id`는 백엔드에서 **세션/토큰/컨텍스트**로 결정하는지, 저장 API path에 포함되는지.
- **doc_id(Long)**: URL path의 문서 ID를 사용하거나, body의 `rag_document_id`를 파싱해 내부 doc_id(Long)로 매핑하는지 정책만 맞추면 됩니다.

---

## 6. 청크 API 응답의 camelCase

- 백엔드 정책: **API 응답**은 camelCase (`actionAt`, `occurredAt`, `createdAt` 등) ✓
- RAG **저장 API는 “수신”** 이므로, 수신 body는 Aura 규격(snake_case)을 따르고, **응답**이 있다면(예: 저장 결과 요약) 그때만 camelCase를 적용하면 됩니다.  
  즉, “저장 요청 DTO”는 Aura 스펙(snake_case) 기준으로 두고, “다른 API 응답 DTO”의 날짜/시간 필드만 camelCase로 통일하면 됩니다.

---

## 7. 체크리스트 요약

| # | 확인 항목 | 권장 |
|---|-----------|------|
| 1 | 청크 수신 필드: `content` → DB `chunk_text` 매핑 | DTO에 `content` 수신 후 서비스에서 `chunk_text`에 설정 |
| 2 | `metadata.page_number` → `page_no` 컬럼 | metadata 객체에서 꺼내서 `page_no`에 설정 |
| 3 | 수신 JSON 키: snake_case (`chunk_index`, `rag_document_id`, `batch_index`, `total_batches`) | DTO 필드명 또는 @JsonProperty로 snake_case 수신 |
| 4 | `embedding`: number[] → PGvector 바인딩 | 드라이버/헬퍼로 1536차원 float[] → vector 변환 |
| 5 | `tenant_id` / `doc_id`(Long) 공급처 | tenant: 인증/컨텍스트, doc_id: path 또는 `rag_document_id` 파싱 |
| 6 | 여러 배치 수신 시 순서 유지 | `batch_index`/`total_batches` 참고해 순서 유지 후 500건 단위 batchUpdate ✓ |

위 항목만 맞춰 두면 Aura와 백엔드 청크 연동은 정합하게 동작합니다.
