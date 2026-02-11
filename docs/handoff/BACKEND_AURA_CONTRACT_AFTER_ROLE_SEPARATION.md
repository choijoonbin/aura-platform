# 기능 제거 후 백엔드–Aura 협업 규격 및 확인사항

> **목적**: 역할 분리(DB 쓰기 제거) 이후, 백엔드와 Aura가 서로 규격을 맞추기 위한 전달사항 및 확인 체크리스트  
> **전달 일자**: 2026-02-11

---

## 1. 양쪽이 맞춰야 하는 규격 (Contract)

### 1.1 제거된 기능 (Aura 측)

| 구분 | 이전 | 현재 (제거 후) |
|------|------|----------------|
| **case_action_history** | Aura가 INSERT | **Aura는 쓰지 않음** → 백엔드가 자체 테이블에 기록 |
| **fi_doc_header** | Aura가 status_code UPDATE | **Aura는 쓰지 않음** → 백엔드가 전표 상태 동기화 |
| **DB 트랜잭션** | Aura가 위 두 테이블 처리 | Aura는 DB 트랜잭션 없음 (피드백 로그 + Redis만) |

→ **백엔드**: 승인/거절 처리 시 **반드시** 자체 DB에 조치 이력·전표 상태를 기록해야 합니다. Aura는 이 데이터를 저장하지 않습니다.

---

### 1.2 API 규격 (POST /api/aura/action/record)

**요청(Request)**  
- 변경 없음. 기존과 동일한 Body (`case_id`, `request_id`, `executor_id`, `approved`, `comment`, `doc_key`).

**응답(Response) 규격 변경** — **백엔드 호출부에서 확인 필요**

| 필드 | 이전 | 현재 (제거 후) |
|------|------|----------------|
| `data.history_id` | 반환됨 (INSERT된 id) | **제거됨** (반환하지 않음) |
| `data.fi_doc_updated` | 반환됨 (UPDATE row count) | **제거됨** (반환하지 않음) |
| `data.ok` | true | **유지** (true) |
| `data.logged` | 없음 | **추가** (true = HITL 피드백 로그 기록됨) |

**현재 응답 예시**:
```json
{
  "status": "SUCCESS",
  "message": "Action recorded",
  "data": { "ok": true, "logged": true },
  "success": true,
  "timestamp": "..."
}
```

→ **백엔드**: `/action/record` 호출 후 `history_id`, `fi_doc_updated`를 참조하는 코드가 있다면 제거하거나, **자체 DB에 기록한 결과**를 사용하도록 변경해야 합니다.

---

### 1.3 Redis Pub/Sub — 통일 알림 포맷

**모든 워크벤치 알림**은 아래 구조로 통일됩니다 (백엔드 수신 용이).

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `type` | string | O | `"NOTIFICATION"` 고정 |
| `category` | string | O | `CASE_ACTION` \| `RAG_STATUS` \| `AI_DETECT` |
| `message` | string | O | 사용자/시스템용 메시지 |
| `timestamp` | string | O | ISO 8601 (UTC) |
| (기타) | — | X | category별 추가 필드 |

**채널별 발행**

| 채널 | category | 발행 시점 | 추가 필드 예 |
|------|----------|-----------|----------------|
| `workbench:case:action` | CASE_ACTION | 승인/거절/타임아웃(보류) 시 | case_id, request_id, executor_id, action_type, approved, status_code |
| `workbench:rag:status` | RAG_STATUS | RAG 벡터화 완료 시 | rag_document_id, chunks_added |
| `workbench:alert` | AI_DETECT | Phase2에서 고위험(severity=HIGH) 케이스 생성 시 | case_id, score, severity |

**CASE_ACTION 발행 예시** (승인/거절/보류 모두 동일 포맷):
```json
{
  "type": "NOTIFICATION",
  "category": "CASE_ACTION",
  "message": "조치 승인됨",
  "timestamp": "2026-02-11T12:00:00.000000+00:00",
  "case_id": "DEMO00001",
  "request_id": "req-xxx",
  "executor_id": "user-123",
  "action_type": "APPROVE",
  "approved": true,
  "status_code": "APPROVED"
}
```

→ **백엔드**: 파싱 시 `type === "NOTIFICATION"`, `category`로 구분하여 처리하면 됩니다.  
→ **Aura**: 현재 Aura는 해당 채널을 **구독하지 않고 발행만** 합니다. 향후 구독 시, 같은 채널에 **백엔드도 발행**하므로 `history_id`, `fi_doc_updated`(및 백엔드 전용 필드)는 **optional**로 처리합니다.

---

### 1.4 Phase2 분석 요청 시 doc_id / item_id (선택 규격)

**목적**: 백엔드에서 특정 문서·항목에 대한 규정 준수 여부만 보고 싶을 때.

| 전달 위치 | 필드 | 타입 | 설명 |
|-----------|------|------|------|
| `body_evidence.doc_id` | doc_id | string | 문서 식별자 (또는 `body_evidence.document.docKey`) |
| `body_evidence.item_id` | item_id | string | 항목 식별자 |

Aura Phase2는 위가 있으면 프롬프트에 **"지정한 문서·항목(doc_id=..., item_id=...)에 대한 상세 내역을 우선 참고하여 규정 준수 여부를 판단"** 하도록 반영합니다.

→ **백엔드**: 상세 내역 기반 규정 준수 판단이 필요하면 분석 요청 시 `body_evidence`에 `doc_id`(또는 `document.docKey`), `item_id`를 넘기면 됩니다. 없으면 기존처럼 전체 evidence 기준으로 판단합니다.

---

## 2. 확인사항 체크리스트 (양쪽 협업용)

### 2.1 백엔드 확인사항

| # | 확인 항목 | 비고 |
|---|-----------|------|
| 1 | 승인/거절 처리 시 **자체 DB**에 조치 이력(case_action_history 등)을 저장하는가? | Aura는 더 이상 저장하지 않음 |
| 2 | 전표 상태(fi_doc_header 등)를 **자체 DB**에서 갱신하는가? | Aura는 status_code를 갱신하지 않음 |
| 3 | `POST /api/aura/action/record` 응답에서 `data.history_id`, `data.fi_doc_updated`를 사용하는 코드가 있는가? | 있다면 제거 또는 자체 DB 결과로 대체 |
| 4 | Redis `workbench:case:action` 구독 시 `history_id`, `fi_doc_updated` 필드를 파싱·사용하는가? | 있다면 제거 또는 optional 처리 |
| 5 | (선택) Phase2 분석 요청 시 `doc_id`/`item_id`를 넘길 계획이 있는가? | 있으면 `body_evidence.doc_id`, `body_evidence.item_id` 또는 `document.docKey` 규격 사용 |

### 2.2 Aura 확인사항

| # | 확인 항목 | 비고 |
|---|-----------|------|
| 1 | `record_case_action()`에서 case_action_history / fi_doc_header 접근이 제거되었는가? | 서비스 코드 기준 제거 완료 |
| 2 | API 응답이 `data: { ok, logged }` 만 반환하는가? | history_id, fi_doc_updated 미반환 |
| 3 | Redis 페이로드에 `history_id`, `fi_doc_updated`를 넣지 않는가? | 발행 payload에서 제거 완료 |
| 4 | Phase2에서 `body_evidence.doc_id`, `document.docKey`, `body_evidence.item_id`를 읽어 프롬프트에 반영하는가? | doc_id/item_id 있으면 규정 준수 판단에 반영 |

### 2.3 공통 확인사항

| # | 확인 항목 | 비고 |
|---|-----------|------|
| 1 | 조치 이력·전표 상태의 **단일 소스 오브 트루스**가 백엔드 DB로 합의되었는가? | Aura는 쓰지 않음 |
| 2 | Redis 채널명(`workbench:case:action`) 및 메시지 형식(UTF-8 JSON)이 양쪽에 동일한가? | Aura 설정: `case_action_redis_channel` |
| 3 | Aura `/action/record` 호출 실패 시 백엔드는 어떻게 처리하는가? (재시도·무시·알림 등) | 협의 권장 |

---

## 3. 요약 전달문 (백엔드 전달용)

- **Aura는 더 이상 case_action_history, fi_doc_header에 쓰지 않습니다.** 조치 이력·전표 상태는 **백엔드에서만** 저장·갱신해 주세요.
- **API 응답**: `history_id`, `fi_doc_updated`는 더 이상 내려주지 않습니다. `data.logged` 로 피드백 기록 여부만 확인할 수 있습니다.
- **Redis 메시지**: `history_id`, `fi_doc_updated` 필드는 더 이상 넣지 않습니다. 구독 측에서 이 필드에 의존하지 않도록 수정이 필요할 수 있습니다.
- **Phase2**: 규정 준수 판단을 특정 문서·항목에 집중하려면 `body_evidence`에 `doc_id`(또는 `document.docKey`), `item_id`를 넘겨 주시면 됩니다.

---

## 4. 백엔드 확정 규격 (Backend 전달 사항)

### 4.1 To Aura (Backend → Aura)

| Endpoint (Aura 기준) | Method | Req Body 요약 | Res Body 요약 |
|----------------------|--------|----------------|----------------|
| `/aura/cases/{caseId}/analysis-runs` | POST | caseId, runId, mode, requestedBy, **evidence**(JsonNode: evidence, ragRefs, document{header,items,docKey}, openItems, partyIds, lineage, policies), options | status, caseId, runId, streamUrl, message |
| (동일) | — | **body_evidence**: `{ "doc_id": "BELNR_VALUE", "item_id": "BUZEI_VALUE" }` — Phase2 시 명시 전송. Backend: `BodyEvidenceDto` → `@JsonProperty("doc_id")`/`("item_id")`, belnr→doc_id·buzei→item_id. | — |

→ Aura는 `body_evidence.doc_id`(문자열 BELNR), `body_evidence.item_id`(문자열 BUZEI)를 파싱하여 RAG 랭킹·프롬프트에 반영합니다. String/Number 모두 정규화하여 처리합니다.  
→ **복사용 요청 JSON·검증 요약**: `docs/handoff/LEVEL4_FINAL_API_SPEC_BACKEND.md` Part A 참고.

### 4.2 From Aura (Redis workbench:*)

| 채널 패턴 | 발행 측 | 수신 후 처리 |
|-----------|---------|--------------|
| workbench:* | Aura / Backend | JSON 수신 → **NotificationDto** 매핑 (title, content, type, occurredAt). **category / message / timestamp** 있으면 그대로 **type / content / occurredAt**에 매핑 → DB 저장 + `/topic/notifications` 브로드캐스트. |

→ Aura 발행 페이로드는 `category`, `message`, `timestamp`를 포함하므로 백엔드 NotificationDto 매핑에 그대로 사용됩니다. 상세 샘플: `REDIS_PUBLISH_MESSAGE_SPEC_FINAL.md`.

---

## 5. 관련 문서

- **백엔드 팀 전달용 요약**: `TO_BACKEND.md` — 백엔드에서 확인·구현할 사항 한글 요약·체크리스트·문서 링크.
- **Level 4 최종 API 규격서 (Backend 검증)**: `LEVEL4_FINAL_API_SPEC_BACKEND.md` — Aura 수신 요청 샘플 JSON·body_evidence 검증 요약·FE용 wrbtr/actionAt 규격.
- 상세 API·Redis 스펙: `OTHER_SYSTEMS_ACTION_INTEGRITY_AND_REFETCH.md`
- Redis 발행 최종 샘플: `REDIS_PUBLISH_MESSAGE_SPEC_FINAL.md`
- Aura 내부 가이드: `docs/guides/ACTION_INTEGRITY_APPROVAL_LOOP.md`
