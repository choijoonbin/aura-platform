# RAG 벡터화 API 응답 스펙 (백엔드 전달용)

Aura는 **`dwp_aura.rag_chunk`에 INSERT하지 않습니다.** Chunk + Embedding 연산만 수행하고, 결과를 **20~50개 단위 배치**로 전달합니다. 전달 방식은 두 가지입니다.

- **배치 응답**: Aura가 200 응답 body에 `batches`(배치 배열)를 넣어 반환. 백엔드가 배치별로 INSERT.
- **저장 API 반복 호출**: Aura가 `BACKEND_RAG_CHUNKS_SAVE_URL`로 배치마다 POST. 백엔드는 해당 API에서 배치 수신 후 INSERT.

데이터는 **순수 JSON만** 사용합니다. `::vector`, `CAST` 등 DB 문법 없음. `embedding`은 **number[]**(1536차원 float 배열), `content`는 string, `metadata`는 object.

---

## 1. 엔드포인트 (동기 200)

| 메서드 | 경로 | 요청 |
|--------|------|------|
| POST | `/aura/rag/documents/{doc_id}/vectorize` | body: `document_path`, `metadata`. Query: `batch_size`(20~50, 기본 30) |
| POST | `/aura/rag/ingest-from-path` | body: `document_path`, `rag_document_id`, `metadata` |
| POST | `/aura/rag/ingest` | Form: 파일 업로드, `rag_document_id`, `metadata` |

---

## 2. 성공 응답 (200) — 두 가지 형태

### 2.1 Aura가 배치를 응답 body로 반환 (저장 URL 미설정 시)

```json
{
  "rag_document_id": "문서 UUID",
  "batch_size": 30,
  "batches": [
    [
      {
        "chunk_index": 0,
        "content": "청크 원문",
        "embedding": [ 0.013, -0.018, ... ],
        "metadata": { "doc_id": "...", "chunk_index": 0, "page_number": 1, "file_path": "...", "regulation_article": "제5조", "doc_type": "REGULATION", ... }
      }
    ]
  ]
}
```

- `batches`: 배열의 배열. 각 내부 배열이 한 배치(최대 `batch_size`개 청크).
- 청크 항목: `chunk_index`(number), `content`(string), `embedding`(number[]), `metadata`(object). **DB 문법 없음.**

### 2.2 Aura가 백엔드 저장 API에 반복 POST (저장 URL 설정 시)

Aura가 `BACKEND_RAG_CHUNKS_SAVE_URL`에 배치마다 POST합니다. URL 내 `{doc_id}`는 `rag_document_id`로 치환됩니다.

**Aura → 백엔드 POST body (배치 1건):**
```json
{
  "rag_document_id": "문서 UUID",
  "chunks": [ { "chunk_index": 0, "content": "...", "embedding": [ ... ], "metadata": { ... } }, ... ],
  "batch_index": 0,
  "total_batches": 5
}
```

**Aura가 클라이언트에게 주는 200 응답 (요약만):**
```json
{
  "rag_document_id": "문서 UUID",
  "total_chunks": 142,
  "batches_sent": 5,
  "batch_size": 30
}
```

---

## 3. 청크 항목 스키마 (공통)

| 필드 | 타입 | 설명 |
|------|------|------|
| `chunk_index` | number | 0-based 인덱스. |
| `content` | string | 청크 본문. |
| `embedding` | number[] | **1536차원 float 배열**. 순수 JSON, DB 문법 없음. |
| `metadata` | object | `doc_id`, `page_number`, `file_path`, `regulation_article`, `regulation_clause`, `location`, `title`, `doc_type` 등. |

---

## 4. 실패 응답 (4xx/5xx)

Body: `{ "error": "메시지" }`. 저장 URL 사용 시 백엔드 저장 실패는 502.

---

## 5. 설정 (Aura .env)

- `RAG_CHUNK_BATCH_SIZE`: 배치당 청크 수 (20~50, 기본 30).
- `BACKEND_RAG_CHUNKS_SAVE_URL`: 설정 시 Aura가 배치마다 이 URL로 POST. 예: `https://backend/api/rag/documents/{doc_id}/chunks`.
