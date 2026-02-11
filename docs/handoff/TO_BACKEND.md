# Aura → 백엔드 전달 사항 (Backend Team)

> **대상**: 백엔드 개발팀  
> **목적**: Aura와의 연동 시 백엔드에서 반드시 확인·구현할 사항 요약  
> **일자**: 2026-02-11

---

## 1. 백엔드에서 해야 할 일 (필수)

| # | 항목 | 설명 |
|---|------|------|
| 1 | **조치 이력·전표 상태 DB** | Aura는 **case_action_history**, **fi_doc_header**에 더 이상 쓰지 않습니다. 승인/거절 처리 시 **백엔드가 자체 DB**에 조치 이력·전표 상태를 반드시 기록·갱신해 주세요. |
| 2 | **/action/record 응답 사용처** | `POST /api/aura/action/record` 호출 후 **data.history_id**, **data.fi_doc_updated**는 Aura가 반환하지 않습니다. (백엔드는 해당 API를 **호출하지 않고** SynapseX DB에서만 조치 확정. 다른 호출자가 있을 경우 응답은 `data: { ok, logged }` 만 반환.) |
| 3 | **Redis 구독 시 필드** | `workbench:case:action` 등 workbench:* 채널 구독 시, Aura 발행분에는 **history_id**, **fi_doc_updated**가 없습니다. 이 필드에 의존하지 않도록 제거 또는 optional 처리해 주세요. |

---

## 2. 백엔드 → Aura (요청 규격)

### 2.1 Phase2 분석 요청

- **Endpoint**: `POST /aura/cases/{caseId}/analysis-runs` (Aura 기준 경로; 게이트웨이 prefix는 백엔드 라우팅에 따름)
- **Body**: caseId, runId, mode, requestedBy, **evidence**(JsonNode), options 등
- **body_evidence (Phase2 시 명시)**  
  특정 전표·라인만 규정 준수 판단하고 싶을 때 요청 body에 아래 블록을 포함해 주세요.

  ```json
  "body_evidence": {
    "doc_id": "1900000001",
    "item_id": "001"
  }
  ```

  - **doc_id**: 전표 번호(BELNR) — 문자열로 전달 (Backend: `BodyEvidenceDto.docId` → `@JsonProperty("doc_id")`).
  - **item_id**: 전표 라인(BUZEI) — 문자열로 전달 (`BodyEvidenceDto.itemId` → `@JsonProperty("item_id")`).

- **복사용 요청 JSON 전체**: `LEVEL4_FINAL_API_SPEC_BACKEND.md` **Part A.2** 참고.

---

## 3. Aura → 백엔드 (Redis 수신 규격)

### 3.1 구독 채널 (workbench:*)

Aura가 발행하는 채널명은 아래와 같습니다. **문자열 그대로** 구독해 주세요.

| 용도 | 채널명 | category | 발행 시점 |
|------|--------|----------|-----------|
| 고위험 탐지 | `workbench:alert` | AI_DETECT | Phase2에서 severity=HIGH 케이스 생성 시 |
| RAG 학습 완료 | `workbench:rag:status` | RAG_STATUS | RAG 벡터화 완료 시 |
| 조치 결과 통보 | `workbench:case:action` | CASE_ACTION | 승인/거절/타임아웃(보류) 시 |

### 3.2 메시지 형식 및 NotificationDto 매핑

- **공통 필드**: `type`(항상 `"NOTIFICATION"`), `category`, `message`, `timestamp`(ISO 8601 UTC), 기타 category별 필드.
- **백엔드 수신 후**: JSON 수신 시 **category → type**, **message → content**, **timestamp → occurredAt** 으로 NotificationDto에 매핑 후 DB 저장 및 `/topic/notifications` 브로드캐스트하면 됩니다.

**Redis 발행 메시지 최종 샘플(JSON 예시)**: `REDIS_PUBLISH_MESSAGE_SPEC_FINAL.md` 참고.

---

## 4. 체크리스트 (백엔드 확인용)

- [x] 승인/거절 시 조치 이력·전표 상태를 **자체 DB**에 기록·갱신하는가?
- [x] `/api/aura/action/record` 응답에서 `history_id`, `fi_doc_updated` 사용 코드를 제거했는가? (또는 자체 DB 결과로 대체)
- [x] Redis workbench:* 구독 시 `history_id`, `fi_doc_updated` 의존을 제거했는가? (optional 처리)
- [x] Phase2 분석 요청 시 특정 문서·라인 지정이 필요하면 `body_evidence.doc_id`, `body_evidence.item_id`를 보내는가?
- [x] workbench:* 수신 시 `category`/`message`/`timestamp`를 NotificationDto type/content/occurredAt에 매핑하는가?

### 4.1 Backend 확인 결과 (Backend 답변 반영)

| # | 항목 | Backend 답변 |
|---|------|--------------|
| 1 | 조치 이력·전표 상태 DB | **예.** `ActionCommandService`: `agent_case_action_history` INSERT, `fi_doc_header` FINALIZED, `recon_result` PASS. |
| 2 | /action/record 응답 사용처 | **해당 없음.** 백엔드는 `POST /api/aura/action/record`를 **호출하지 않음**. 조치 확정은 SynapseX DB에서만 수행. |
| 3 | Redis history_id, fi_doc_updated | **예.** `NotificationRedisSubscriber`는 **category**, **message**, **timestamp**만 사용. history_id, fi_doc_updated 파싱/참조 없음. |
| 4 | body_evidence 전송 | **예.** `CaseAnalysisService.buildBodyEvidence()` → `AuraAnalyzeRequest.bodyEvidence` 전송. |
| 5 | NotificationDto 매핑 | **예.** 페이로드에 있으면 우선 사용, 없으면 채널별 fallback. |

---

## 5. 상세 규격 문서 (참고)

| 문서 | 내용 |
|------|------|
| **LEVEL4_FINAL_API_SPEC_BACKEND.md** | Backend 검증 요청/응답 JSON (Aura 수신 샘플, body_evidence 검증, FE용 wrbtr/actionAt) |
| **REDIS_PUBLISH_MESSAGE_SPEC_FINAL.md** | Redis 한 문서 통합: 채널·스키마·JSON 샘플·Backend 구독(workbench:* PSUBSCRIBE)·NotificationRedisSubscriber 매핑·정합성 요약 |
| **BACKEND_AURA_CONTRACT_AFTER_ROLE_SEPARATION.md** | 역할 분리 후 API/Redis 계약·체크리스트·요약 전달문 |
| **OTHER_SYSTEMS_ACTION_INTEGRITY_AND_REFETCH.md** | 조치 완료 후 Refetch·Redis 구독 연동 상세 |

문의나 규격 이슈는 위 문서를 기준으로 협의해 주시면 됩니다.

---

## 6. RAG 로컬 경로 수집 (Aura 쪽에 전달할 것)

백엔드와 RAG 로컬 파일 수집을 맞출 때, 아래를 **Aura 측에서 반영·백엔드에 전달**하면 됩니다.

### 6.1 저장 경로

- **백엔드가 로컬 파일을 두는 경로**: `storage.local.path` 기본값 **`/data/dwp-storage/documents`** (환경변수 **`RAG_STORAGE_LOCAL_PATH`** 로 변경 가능).
- **Aura 측 설정**: Aura의 **`RAG_ALLOWED_DOCUMENT_BASE_PATH`** 를 이 경로(또는 그 상위, 예: `/data/dwp-storage`)로 맞춰야 경로 검증이 통과합니다.
- **전달 문구**: *“백엔드 저장 경로는 `/data/dwp-storage/documents`(또는 설정값)이니, Aura의 allowed_base(`RAG_ALLOWED_DOCUMENT_BASE_PATH`)를 여기 포함하도록 설정하겠다.”*

### 6.2 호출 API 정리

- **현재 백엔드**: 로컬 파일 업로드 후 **`POST /aura/rag/documents/{docId}/vectorize`** 에 `document_path`를 넣어 호출합니다.
- **Aura 제공 API**: **`POST /aura/rag/ingest-from-path`** (body: `document_path` 필수, `rag_document_id`, `metadata`)를 추가한 상태입니다.
- **전달 문구**: *“로컬 경로 수집은 **vectorize**를 쓸지, **ingest-from-path**를 쓸지 정해 주시면, 그에 맞춰 백엔드 호출을 바꾸겠다.”*  
  → 백엔드에서 사용할 엔드포인트를 정해 주면, Aura는 해당 규격을 유지하고 백엔드는 그에 맞춰 호출을 정리하면 됩니다.
