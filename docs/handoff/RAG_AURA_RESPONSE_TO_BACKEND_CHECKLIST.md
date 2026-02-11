# 백엔드 확인사항 전달 (Aura 측 회신)

> 백엔드 연동 맞춤 문서(back.txt) §3 「Aura 측 확인 요청」에 대한 Aura 팀 확인 결과입니다.  
> 일자: 2026-02-11

---

## 1. Aura 측 확인 결과 (§3 체크리스트 회신)

| # | 백엔드 확인 요청 | Aura 확인 |
|---|------------------|-----------|
| 1 | 벡터화 완료 시 **POST {BE Gateway}/api/synapse/rag/status** 호출 여부 | ✅ **예.** `BACKEND_RAG_CHUNKS_SAVE_URL`에 해당 URL 설정 시, 배치마다 위 URL로 POST 호출합니다. |
| 2 | Body에 **docId**, **status**(COMPLETED/FAILED 등), 선택 **message** 포함 여부 | ✅ **선택 반영 가능.** 현재는 **rag_document_id**, **chunks**, **batch_index**, **total_batches** 전송. 백엔드가 rag_document_id 수용·docId resolve 구현 완료 시 현재 형식으로 연동됩니다. 필요 시 status/message 추가 전송 가능. |
| 3 | status=COMPLETED 시 **chunks** 배열 포함 여부 | ✅ **예.** chunks 배열을 포함해 전송합니다 (배치 단위로 나누어 반복 POST). |
| 4 | chunks[].**chunk_content** (또는 chunk_content) 포함 여부 | ✅ **예.** 본문 필드명은 **content**로 전송. 백엔드 @JsonAlias("content") 수용 시 그대로 연동됩니다. |
| 5 | chunks[].**embedding** 1536차원 float 배열 전송 여부 | ✅ **예.** 1536차원 number[](float) 배열로 전송합니다. DB 문법 없음. |
| 6 | chunks[].**chunk_index** (또는 chunkIndex) 문서 내 순서 전송 여부 | ✅ **예.** 0-based **chunk_index** 포함, 문서 내 등장 순서대로 배열 구성합니다. |
| 7 | **metadata_json** (또는 metadataJson) 에 page_no, file_path 등 포함 여부 | ✅ **예.** **metadata** 객체로 전송하며, 내부에 **page_number**, **file_path**, doc_id, regulation_article, doc_type 등 포함합니다. |

---

## 2. 전송 형식 요약 (백엔드 수신 기준)

- **URL**: `POST {gateway}/api/synapse/rag/status` (Aura 설정: `BACKEND_RAG_CHUNKS_SAVE_URL`)
- **Body**: `rag_document_id`(string), `chunks`, `batch_index`, `total_batches`
- **청크 1건**: `chunk_index`, `content`, `embedding`(number[] 1536), `metadata`(object, 내부 `page_number` 등)

백엔드 문서(back.txt) §2.2·§2.3 및 「Aura 전달사항 반영」에 이미 반영된 내용과 동일합니다.

---

## 3. 참고 문서 (Aura → 백엔드 전달)

| 문서 | 내용 |
|------|------|
| **RAG_BACKEND_CHUNK_CHECKLIST.md** | 필드 매핑, 수신 body 예시, 배치·embedding·tenant_id/doc_id 확인 항목 |
| **RAG_VECTORIZE_RESPONSE_SPEC.md** | 벡터화 API 응답(배치 구조, 저장 URL 반복 POST 스펙) |

---

**정리**: back.txt 기준으로 백엔드가 rag_document_id·content·metadata·page_number를 반영해 주셨으므로, Aura는 동일 URL에 현재 형식 그대로 전송해 연동합니다. 추가로 필요한 확인 사항 있으면 알려 주시면 됩니다.
