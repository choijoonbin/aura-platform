# RAG 청크 콜백 활성화 — 백엔드 전달 사항

Aura에서 벡터화 완료 후 청크를 백엔드로 자동 전송(Callback)하도록 설정을 반영했습니다. 백엔드 연동 확인용으로 참고하세요.

---

## 1. Aura 측 적용 내용

| 항목 | 내용 |
|------|------|
| **환경 변수** | `.env`에 `BACKEND_RAG_CHUNKS_SAVE_URL` 설정. **Gateway 경유**: `http://<host>:8080/api/synapse/rag/chunks` / **SynapseX 직통**: `http://<host>:8085/synapse/rag/chunks`. 로컬이면 `<host>=localhost`. |
| **동작** | `BACKEND_RAG_CHUNKS_SAVE_URL`이 설정되면 **save_url_set=True** 로 인식되고, 벡터화 종료 후 **배치마다** 해당 URL로 POST 호출. |
| **POST Body** | `{ "rag_document_id", "chunks", "batch_index", "total_batches" }` (back.txt §3 Request Body와 동일) |

- **배치 규칙**: 20~50개 단위로 청크를 나누어, 배치 1건 처리 완료 시마다 1회 POST. `batch_index`는 0부터 순차.
- **벡터화 API 응답**: 콜백 사용 시 Aura는 클라이언트에게 **요약만** 반환 (`rag_document_id`, `total_chunks`, `batches_sent`, `batch_size`). 청크 본문은 위 URL로만 전송.

---

## 2. 백엔드 확인 사항

1. **엔드포인트**  
   `POST http://[Gateway]:8080/api/synapse/rag/chunks` 가 back.txt 명세대로 구현되어 있는지 확인.

2. **수신 후 처리**  
   - Request body에서 `rag_document_id`, `chunks`, `batch_index`, `total_batches` 수신.  
   - **batch_index == 0** 인 경우: 해당 `rag_document_id`의 기존 rag_chunk **전부 삭제** 후, 해당 배치 chunks INSERT.  
   - **batch_index >= 1** 인 경우: 삭제 없이 해당 배치 chunks만 **추가 INSERT**.  
   - 응답: 성공 시 **200 OK** (back.txt §2 참고).

3. **연동 확인 방법**  
   - Aura에서 규정집 등 문서 벡터화 실행 후, Aura 로그에  
     `RAG vectorize response (save_url used): ... batches_sent=...`  
     가 출력되면 해당 배치 수만큼 백엔드 URL로 POST가 호출된 상태입니다.  
   - 백엔드에서 `rag_chunk` 테이블에 행이 증가하는지로 수신·저장 여부 확인 가능.

---

## 3. URL 설정 확인

Aura가 호출하는 백엔드 URL(`BACKEND_RAG_CHUNKS_SAVE_URL`)이 실제 연동 방식에 맞는지 확인하세요.

| 연동 방식 | URL 형식 | 예 (로컬) |
|-----------|----------|-----------|
| **Gateway 사용** | `http://<host>:8080/api/synapse/rag/chunks` | `http://localhost:8080/api/synapse/rag/chunks` |
| **SynapseX 직통** | `http://<host>:8085/synapse/rag/chunks` | `http://localhost:8085/synapse/rag/chunks` |

- `<host>`가 localhost가 **아니면**, Aura가 떠 있는 서버에서 해당 호스트의 **8080**(Gateway) 또는 **8085**(SynapseX) 포트로 접근 가능해야 합니다 (방화벽/네트워크 확인).
- **경로**: Gateway일 때 **반드시** `/api/synapse/rag/chunks`, SynapseX 직통일 때는 `/synapse/rag/chunks` (앞에 `/api` 없음). — back.txt §1 호스트/포트 확인

---

## 4. 백엔드 답변 반영 (back.txt 기준)

- **rag_document_id**: 백엔드가 **string 또는 number** 모두 수용 (예: `"11"`, `11`, `11.0`). Aura는 path의 doc_id를 문자열로 보냄 → 그대로 수용됨.
- **400/502 발생 시**: 백엔드 권장 — Aura가 호출하는 **호스트·포트**가 백엔드가 실제로 떠 있는 곳과 같은지, Gateway 사용 시 8080·SynapseX 직통 시 8085 및 경로가 맞는지 확인.

---

## 5. 배포 시

- Aura의 `BACKEND_RAG_CHUNKS_SAVE_URL`을 **실제 Gateway 또는 SynapseX 주소**로 변경 (예: `https://gateway.example.com/api/synapse/rag/chunks`).
- 백엔드 Gateway가 해당 경로를 백엔드 서비스로 라우팅하는지 확인.

---

**참고**: 상세 API 명세·필드 설명·cURL 예시는 back.txt(백엔드 제공 문서) §1~§6를 따릅니다.
