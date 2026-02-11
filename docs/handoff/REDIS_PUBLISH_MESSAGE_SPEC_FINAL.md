# Redis 발행 메시지 최종 샘플 (Aura → Backend)

> **목적**: Aura Redis 발행 규격과 백엔드 수신·매핑 규격을 한 문서에 정리 (채널, 스키마, 샘플, 정합성)  
> **일자**: 2026-02-11  
> **공유**: Aura 팀 발행 규격 + Backend 구독·매핑 정합성

---

## 1. 채널명 최종 대조

Aura가 발행하는 채널명과 백엔드가 구독하는 패턴을 아래와 같이 맞춰 두었습니다.

| 용도 | 채널명 (문자열 그대로) | Aura 설정 키 | Aura 발행 위치 |
|------|------------------------|-------------|----------------|
| 고위험 탐지 (AI_DETECT) | `workbench:alert` | `workbench_alert_channel` | `core/analysis/phase2_pipeline.py` |
| RAG 학습 완료 (RAG_STATUS) | `workbench:rag:status` | `workbench_rag_status_channel` | `core/analysis/rag.py` |
| 조치 결과 통보 (CASE_ACTION) | `workbench:case:action` | `case_action_redis_channel` | `core/action_integrity/service.py` |

- **Aura**: `core/notifications.py`에 `REDIS_CHANNEL_WORKBENCH_ALERT`, `REDIS_CHANNEL_WORKBENCH_RAG_STATUS`, `REDIS_CHANNEL_WORKBENCH_CASE_ACTION` 정의, 설정 미지정 시 fallback 사용. `core/config.py` 기본값 동일.
- **Backend 구독**: `NotificationRedisConfig`에서 패턴 **`workbench:*`**(PSUBSCRIBE) 사용 → 위 세 채널 모두 수신.

---

## 2. 공통 메시지 스키마 및 Backend 매핑

### 2.1 Aura 발행 스키마

모든 워크벤치 알림은 아래 공통 구조를 따릅니다.

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `type` | string | ✅ | 항상 `"NOTIFICATION"` |
| `category` | string | ✅ | `"AI_DETECT"` \| `"RAG_STATUS"` \| `"CASE_ACTION"` (대소문자 일치) |
| `message` | string | ✅ | 사용자/시스템용 메시지 |
| `timestamp` | string | ✅ | ISO 8601 UTC (예: `2026-02-11T14:30:00.123456+00:00`) |
| 기타 | — | 선택 | 이벤트별 추가 필드(평면 구조로 루트에 포함) |

- **인코딩**: UTF-8. Aura는 `json.dumps(..., ensure_ascii=False)` 후 `payload.encode("utf-8")`로 발행합니다.

### 2.2 Backend 수신 시 매핑 (NotificationDto)

백엔드 **NotificationRedisSubscriber**에서 JSON 수신 시 아래처럼 매핑합니다. Aura는 `category`, `message`, `timestamp`를 항상 포함해 발행합니다.

| Aura 페이로드 필드 | NotificationDto 필드 |
|--------------------|------------------------|
| `category` | `type` |
| `message` | `content` |
| `timestamp` | `occurredAt` |

- **동작**: 페이로드에 `category`, `message`, `timestamp`가 있으면 **그대로** type/content/occurredAt에 매핑. **없을 때만** 채널별 fallback(제목·내용 생성) 적용.
- **RAG 채널**: content fallback 시 `rag_document_id` 또는 `doc_id` 사용 가능.
- **후속**: DB 저장 후 `/topic/notifications` 브로드캐스트.

---

## 3. Redis 발행 메시지 최종 샘플

### 3.1 `workbench:alert` — AI_DETECT (고위험 탐지)

**발행 시점**: Phase2 분석에서 `severity == "HIGH"`인 케이스가 생성될 때.

```json
{
  "type": "NOTIFICATION",
  "category": "AI_DETECT",
  "message": "신규 이상 징후 탐지",
  "timestamp": "2026-02-11T14:40:00.123456+00:00",
  "case_id": "CASE-HIGH-001",
  "score": 0.85,
  "severity": "HIGH"
}
```

---

### 3.2 `workbench:rag:status` — RAG_STATUS (학습 완료)

**발행 시점**: RAG 벡터화(`process_and_vectorize_pgvector`) 성공 직후.

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

---

### 3.3 `workbench:case:action` — CASE_ACTION (조치 결과 통보)

**발행 시점**: HITL 승인/거절/타임아웃(보류) 시 `record_case_action()` 호출 후.

**승인 예시**

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

**거절 예시**

```json
{
  "type": "NOTIFICATION",
  "category": "CASE_ACTION",
  "message": "조치 거절됨",
  "timestamp": "2026-02-11T14:31:00.000000+00:00",
  "case_id": "DEMO00002",
  "request_id": "req-def456",
  "executor_id": "user-789",
  "action_type": "REJECT",
  "approved": false,
  "status_code": "REJECTED"
}
```

---

## 4. 대조·정합성 요약 (한눈에)

| 항목 | Aura | Backend | 상태 |
|------|------|---------|------|
| 구독/발행 채널 | `workbench:alert`, `workbench:rag:status`, `workbench:case:action` 발행 | `workbench:*` PSUBSCRIBE로 세 채널 수신 | ✅ 일치 |
| `category` | AI_DETECT, RAG_STATUS, CASE_ACTION (상수 사용) | → NotificationDto `type` | ✅ 대소문자 일치 |
| `message` | 항상 포함 | → NotificationDto `content` | ✅ |
| `timestamp` | ISO 8601 UTC 포함 | → NotificationDto `occurredAt` (파싱 후 사용) | ✅ |
| RAG 보조 필드 | `rag_document_id`, `chunks_added` 등 | content fallback 시 `rag_document_id` 또는 `doc_id` 사용 | ✅ |
| 인코딩 | UTF-8 발행 (`ensure_ascii=False`) | UTF-8 수신 처리 | ✅ |

위 규격으로 Aura가 발행하고, Backend는 `NotificationRedisSubscriber`에서 category/message/timestamp를 type/content/occurredAt에 매핑해 사용하면 됩니다.
