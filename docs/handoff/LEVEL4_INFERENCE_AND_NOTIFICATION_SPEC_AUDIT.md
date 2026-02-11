# Level 4 Inference & Notification Spec Audit (Aura AI)

> **목적**: 백엔드와의 약속된 규격 준수 및 분석 에이전트 동작 점검  
> **일자**: 2026-02-11

---

## 1. [Analysis Precision] 상세 내역 기반 추론

### 1.1 Evidence Binding — doc_id/item_id 기반 규정 랭킹

**요구**: 백엔드에서 넘어온 `doc_id`, `item_id`를 기반으로 pgvector 검색 시, 해당 항목과 관련된 규정을 **최상단에 배치(Ranking)** 하는가?

**구현**: **준수**

- **소스**: `core/analysis/phase2_pipeline.py`
- **동작**: `body_evidence`에서 `doc_id`를 추출한 뒤, `doc_list`(search_documents + hybrid_retrieve 결과)를 **doc_id와 일치하는 `rag_document_id`/`sourceKey`를 가진 항목이 먼저 오도록** 정렬합니다. 동일 doc_id 매칭 시에는 score 내림차순 유지.
- **코드 요약** (2026-02-11 재검증): `doc_id_ref`는 `body_evidence.doc_id` 또는 `body_evidence.document.docKey`에서 파싱; 비교 시 양쪽 `strip()` 적용으로 공백 차이 무시.
```python
doc_id_norm = doc_id_ref.strip()
def _doc_rank_key(d):
    rid = str(d.get("rag_document_id") or d.get("sourceKey") or d.get("docKey") or "").strip()
    match = 0 if rid == doc_id_norm else 1
    return (match, -(float(d.get("score", 0)) or 0))
doc_list.sort(key=_doc_rank_key)
```
- **검증**: RAG 검색 결과 doc_list에 대해 doc_id 일치 문서가 1순위로 정렬됨.

---

### 1.2 Reasoning — 구체적 근거 프롬프트 엔지니어링

**요구**: "상세 항목(Item)의 OOO 필드가 규정 제X조와 상충됨"이라는 구체적 근거가 포함되도록 프롬프트가 반영되었는가?

**구현**: **준수**

- **소스**: `core/analysis/phase2_pipeline.py` (LLM reasonText 생성부)

**사용 중인 LLM 분석 지침 일부** (위반 전표 시):

```
위 참조 규정을 반드시 인용하여 작성하되,
**정상 전표**인 경우: '사내 경비 규정 v1.2의 모든 기준을 충족하는 모범적인 지출 사례'임을 칭찬 섞인 요약으로 표현.
**위반 전표**인 경우: '규정 제N조 N항을 정면으로 위반했습니다.'라고 단호하게 쓰고,
구체적 근거로 '상세 항목(Item)의 [필드명]이 규정 제X조 X항과 상충됨' 형태를 포함할 것.
위반 사유(시간외 결제·주말 식대 등)를 한 문장에 포함하고, evidence에는 해당 조항 원문을 정확히 바인딩할 수 있도록 조문 번호를 명시.
```

- **doc_id/item_id 지정 시 추가 지침**:
```
백엔드에서 지정한 문서·항목(doc_id=..., item_id=...)에 대한 상세 내역을 우선 참고하여 규정 준수 여부를 판단하고, 해당 내역 기반으로 이유를 작성하시오.
```

---

## 2. [Protocol] Redis 발행 규격 준수

### 2.1 Message Schema — 공통 알림 스키마

**요구**: `type`, `category`, `message`, `timestamp`, `extra_data` 등 백엔드 공통 알림 스키마 100% 준수.

**구현**: **준수** (필수 필드 일치, 추가 필드는 평면 구조)

- **소스**: `core/notifications.py` — `build_notification_payload(category, message, **extra)`
- **category 상수화 (2026-02-11)**: 백엔드 `NotificationService` 규격과 대소문자까지 일치하도록 `NOTIFICATION_CATEGORY_AI_DETECT`, `NOTIFICATION_CATEGORY_RAG_STATUS`, `NOTIFICATION_CATEGORY_CASE_ACTION` 상수를 사용. 모든 발행 지점에서 상수 참조로 오타/대소문자 오류 방지.
- **구성**: `type`, `category`, `message`, `timestamp` 는 고정 필드이며, **추가 필드는 루트에 평면(flat)으로** 포함됩니다. 백엔드가 `extra_data` 단일 객체를 요구하면, 해당 객체로 감싸는 옵션을 추가할 수 있습니다.

**Redis 발행 메시지 샘플**

**CASE_ACTION** (`workbench:case:action`):

```json
{
  "type": "NOTIFICATION",
  "category": "CASE_ACTION",
  "message": "조치 승인됨",
  "timestamp": "2026-02-11T14:30:00.123456+00:00",
  "case_id": "DEMO00001",
  "request_id": "req-abc123",
  "executor_id": "user-456",
  "action_type": "APPROVE",
  "approved": true,
  "status_code": "APPROVED"
}
```

**RAG_STATUS** (`workbench:rag:status`):

```json
{
  "type": "NOTIFICATION",
  "category": "RAG_STATUS",
  "message": "학습 완료",
  "timestamp": "2026-02-11T14:35:00.000000+00:00",
  "rag_document_id": "reg-v1.2",
  "chunks_added": 12
}
```

**AI_DETECT** (`workbench:alert`):

```json
{
  "type": "NOTIFICATION",
  "category": "AI_DETECT",
  "message": "신규 이상 징후 탐지",
  "timestamp": "2026-02-11T14:40:00.000000+00:00",
  "case_id": "CASE-HIGH-001",
  "score": 0.85,
  "severity": "HIGH"
}
```

---

### 2.2 Topic Accuracy — 채널 구분

**요구**: 이벤트 종류에 따라 `workbench:alert`, `workbench:rag:status`, `workbench:case:action` 채널을 정확히 구분하여 발행하는가?

**구현**: **준수**

| 이벤트 | 채널 | 설정 키 | 발행 위치 |
|--------|------|---------|-----------|
| 고위험 탐지 | `workbench:alert` | `workbench_alert_channel` | `core/analysis/phase2_pipeline.py` (severity==HIGH 시) |
| RAG 학습 완료 | `workbench:rag:status` | `workbench_rag_status_channel` | `core/analysis/rag.py` (process_and_vectorize_pgvector 성공 후) |
| 조치 결과 통보 | `workbench:case:action` | `case_action_redis_channel` | `core/action_integrity/service.py` (record_case_action) |

- **설정**: `core/config.py` — 각 채널 기본값이 위 표와 동일.

---

## 3. [HITL Feedback] 피드백 루프

**요구**: 백엔드로부터 온 조치 결과(승인/거절 사유)를 수신했을 때, 향후 재학습을 위한 `hitl_feedback.jsonl` 에 규격화된 포맷으로 누적 저장하는가?

**구현**: **준수**

- **소스**: `core/action_integrity/service.py` — `_log_hitl_feedback()`, `record_case_action()` 호출
- **설정**: `core/config.py` — `hitl_feedback_log_path` (예: `data/hitl_feedback.jsonl`) 설정 시 해당 경로에 JSONL append.
- **호출 시점**: 승인/거절/타임아웃(보류) 모두 `record_case_action()` 경유로 HITL 로그 기록.
- **인코딩 (2026-02-11 최종 점검)**: 백엔드 API로 전달되는 `comment`는 UTF-8 안전 문자열로 정규화 후 `json.dumps(..., ensure_ascii=False)` 및 `open(..., encoding="utf-8")`로 기록. 한글 등 비ASCII 문자가 깨지지 않음.

**HITL Feedback JSONL 규격화 포맷 (한 줄 샘플)**:

```json
{"event": "hitl_feedback", "case_id": "DEMO00001", "request_id": "req-abc", "executor_id": "user-456", "action_type": "REJECT", "approved": false, "comment": "증빙 부족", "doc_key": null, "at": "2026-02-11T14:45:00.000000+00:00"}
```

- **필드**: `event`, `case_id`, `request_id`, `executor_id`, `action_type`, `approved`, `comment`, `doc_key`, `at` (ISO 8601 UTC).

---

## 4. 규격 준수 요약

| # | 항목 | 준수 | 비고 |
|---|------|------|------|
| 1.1 | Evidence Binding (doc_id 기반 규정 최상단 배치) | ✅ | `phase2_pipeline.py` doc_list 정렬 |
| 1.2 | Reasoning (상세 항목·규정 상충 근거 프롬프트) | ✅ | 위반 시 "상세 항목(Item)의 [필드명]이 규정 제X조 X항과 상충됨" 지침 포함 |
| 2.1 | Redis Message Schema (type, category, message, timestamp) | ✅ | 추가 필드는 루트 평면 구조 (extra_data 래퍼는 필요 시 적용 가능) |
| 2.2 | Topic Accuracy (alert / rag:status / case:action 구분) | ✅ | 채널별 발행 위치·설정 일치 |
| 3 | HITL Feedback (조치 결과 → hitl_feedback.jsonl 규격 누적) | ✅ | `hitl_feedback_log_path` 설정 시 JSONL append |

**전체**: 분석 정밀도·Redis 프로토콜·HITL 피드백 루프 모두 규격에 맞게 반영됨.

- **Redis 발행 최종 샘플**: 백엔드 규격에 맞춘 채널명·페이로드 최종 대조 및 JSON 샘플은 `docs/handoff/REDIS_PUBLISH_MESSAGE_SPEC_FINAL.md` 참고.
- **백엔드 확정 규격 (To Aura / From Aura)**: Backend → Aura 요청 규격(POST body, body_evidence.doc_id/item_id) 및 Redis workbench:* 수신 후 NotificationDto 매핑(category→type, message→content, timestamp→occurredAt)은 `docs/handoff/BACKEND_AURA_CONTRACT_AFTER_ROLE_SEPARATION.md` §4 참고.
- **Level 4 최종 API 규격서 (Backend 검증 최종본)**: 복사용 요청/응답 JSON·body_evidence(doc_id·item_id) 검증·wrbtr number·actionAt ISO8601 — `docs/handoff/LEVEL4_FINAL_API_SPEC_BACKEND.md`.
