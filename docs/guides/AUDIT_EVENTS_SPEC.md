# Audit Event 명세 (C-1, C-2, C-3)

> Agent Execution Stream이 audit_event_log에서 의미 있는 로그를 가져올 수 있도록  
> Aura(에이전트)가 주요 단계에서 표준 이벤트를 발행합니다.  
> 대시보드 drill-down 및 Top Risk Driver 집계를 위한 필드가 보강되었습니다.

---

## 1. event_category 확장 (C-1)

| event_category | 설명 | event_type 예시 |
|----------------|------|-----------------|
| AGENT | 에이전트 스캔/분석 | SCAN_STARTED, SCAN_COMPLETED, DETECTION_FOUND, RAG_QUERIED, REASONING_COMPOSED |
| ACTION | 액션 제안/승인/실행/시뮬레이션 | ACTION_PROPOSED, ACTION_APPROVED, ACTION_EXECUTED, ACTION_FAILED, SIMULATION_RUN |
| INTEGRATION | 외부 시스템 연동 | INGEST_RECEIVED, INGEST_PARSED, INGEST_FAILED, SAP_WRITE_SUCCESS, SAP_WRITE_FAILED |
| CASE | 케이스 생명주기 | CASE_CREATED, CASE_STATUS_CHANGED, CASE_ASSIGNED |

---

## 2. 의무 이벤트 목록

| 단계 | event_type | event_category | evidence_json 필드 |
|------|------------|----------------|-------------------|
| **SCAN** | SCAN_STARTED | AGENT | - |
| **SCAN** | SCAN_COMPLETED | AGENT | processedCount, durationMs |
| **DETECT** | DETECTION_FOUND | AGENT | caseId, riskTypeKey, score, caseKey |
| **ANALYZE(RAG)** | RAG_QUERIED | AGENT | docIds, topK, latencyMs |
| **ANALYZE(RAG)** | REASONING_COMPOSED | AGENT | caseId |
| **SIMULATE** | SIMULATION_RUN | ACTION | actionId, result=PASS/FAIL, diffJson, caseId, caseKey |
| **EXECUTE** | ACTION_PROPOSED | ACTION | actionId, requiresApproval, caseId, caseKey |
| **EXECUTE** | ACTION_APPROVED | ACTION | actionId |
| **EXECUTE** | ACTION_EXECUTED | ACTION | actionId, sapRef, outcome, caseId, caseKey |
| **EXECUTE** | ACTION_FAILED | ACTION | actionId, error |
| **INTEGRATION** | SAP_WRITE_SUCCESS | INTEGRATION | sapRef |
| **INTEGRATION** | SAP_WRITE_FAILED | INTEGRATION | sapRef, error |
| **CASE** | CASE_CREATED | CASE | caseId, caseKey |
| **CASE** | CASE_STATUS_CHANGED | CASE | caseId, fromStatus, toStatus, caseKey |
| **CASE** | CASE_ASSIGNED | CASE | caseId, assigneeId, caseKey |

---

## 3. C-2: Agent Stream correlation 키 (evidence_json)

대시보드 Agent Execution Stream 및 drill-down audit 연결을 위해 **evidence_json**에 다음 키를 보장합니다:

| 키 | 설명 | 출처 |
|----|------|------|
| traceId | 요청 추적 ID | X-Trace-ID / request context |
| gatewayRequestId | Gateway 요청 ID | X-Request-ID, X-Gateway-Request-ID |
| caseId | 케이스 ID | resource_id (CASE), context, tool 인자 |
| caseKey | 케이스 표시 키 (예: CS-2026-0001) | context.caseKey, API 응답 |
| actionId | 액션 ID | resource_id (AGENT_ACTION), tool 인자 |

- **message**: 운영자가 이해 가능한 문장 (스트림 표시용)
- **detail**: evidence_json 내 상세 데이터

---

## 4. C-3: 대시보드 집계용 tags

| 태그 | 적용 이벤트 | 설명 |
|------|-------------|------|
| driverType | DETECTION_FOUND | Top Risk Driver 분류 (riskTypeKey) |
| severity | DETECTION_FOUND | HIGH(≥0.7), MEDIUM(≥0.4), LOW |

**Action Required / 승인대기 시점 이벤트**:
- `ACTION_PROPOSED`: propose_action 호출 시 (승인 필요 시)
- `CASE_STATUS_CHANGED`: 케이스 상태가 승인대기로 변경될 때 (Synapse 등)

---

## 5. 최소 필드 요구사항

| 필드 | 필수 | 설명 |
|------|------|------|
| tenant_id | ✅ | X-Tenant-ID |
| actor_type | ✅ | AGENT |
| actor_agent_id | ✅ | 에이전트 ID (예: finance_agent) |
| event_category | ✅ | AGENT, ACTION, INTEGRATION, CASE |
| event_type | ✅ | 위 표 참조 |
| resource_type | | CASE, AGENT_ACTION, INTEGRATION (통합관제센터 규격) |
| resource_id | | caseId, actionId |
| outcome | ✅ | SUCCESS, FAILED, PENDING, DENIED, NOOP (audit_event_log 규격) |
| severity | ✅ | INFO, WARN, ERROR, CRITICAL |
| evidence_json | ✅ | 단계별 payload + correlation 키 |
| tags | | driverType, severity (Top Risk Driver) |
| trace_id | | X-Trace-ID |
| created_at | ✅ | ISO 8601 (발행 시 timestamp→created_at 변환) |
| channel | | AGENT (에이전트 발행 시) |

---

## 6. 전달 방식

### 2안 (권장) ✅ 현재 구현
Aura → **Redis Pub/Sub** (`audit:events:ingest` 채널) → Synapse가 구독하여 AuditWriter로 audit_event_log 저장

- 서비스 간 내부 통신, HTTP Gateway 경유 없음
- Fire-and-forget, 비동기 발행

### 1안 (단순, fallback)
Aura → `POST /api/synapse/audit/events/ingest` (HTTP API)

- `audit_delivery_mode=http` 설정 시 사용

---

## 7. Aura-Platform 구현 위치

| 이벤트 | 발행 위치 |
|--------|-----------|
| SCAN_STARTED | `domains/finance/agents/hooks.py` - on_node_start("analyze") |
| SCAN_COMPLETED | `domains/finance/agents/hooks.py` - on_node_end("tools") |
| DETECTION_FOUND | `tools/synapse_finance_tool.py` - get_case (riskTypeKey/score 있을 때) |
| RAG_QUERIED | `tools/synapse_finance_tool.py` - search_documents |
| REASONING_COMPOSED | `domains/finance/agents/hooks.py` - on_node_end("reflect") |
| SIMULATION_RUN | `tools/synapse_finance_tool.py` - simulate_action |
| ACTION_PROPOSED | `tools/synapse_finance_tool.py` - propose_action |
| ACTION_EXECUTED | `tools/synapse_finance_tool.py` - execute_action |
| SAP_WRITE_SUCCESS/FAILED | `tools/synapse_finance_tool.py` - execute_action (응답 파싱) |

---

## 8. 설정

```bash
# .env
AUDIT_EVENTS_ENABLED=true
AUDIT_INGEST_URL=http://localhost:8081/api/synapse/audit/events/ingest  # 선택, 미지정 시 synapse_base_url + path
```

---

## 9. Synapse 백엔드 요구사항 (2안)

**Redis Pub/Sub 구독자 구현 필요**

- **채널**: `audit:events:ingest` (기본값, `AUDIT_REDIS_CHANNEL`로 변경 가능)
- **메시지 형식**: JSON 문자열 (AuditEvent 스키마)
- **동작**: 구독 → 메시지 수신 → AuditWriter로 audit_event_log 저장

**예시 (Java/Spring)**:
```java
// RedisMessageListenerContainer 또는 Lettuce subscribe
redisTemplate.listenToChannel("audit:events:ingest", (message) -> {
    AuditEvent event = objectMapper.readValue(message.getBody(), AuditEvent.class);
    auditWriter.write(event);
});
```

**1안 사용 시**: `POST /api/synapse/audit/events/ingest` 엔드포인트 구현

---

## 10. CHANGELOG

- 2026-02-01: C-1 명세 기반 Audit 이벤트 발행 구현
  - core/audit/: schemas, writer (2안 Redis Pub/Sub 기본)
  - tools/synapse_finance_tool: RAG_QUERIED, DETECTION_FOUND, SIMULATION_RUN, ACTION_PROPOSED, ACTION_EXECUTED, SAP_WRITE_*
  - domains/finance/agents/hooks: SCAN_STARTED, SCAN_COMPLETED, REASONING_COMPOSED
- 2026-02-01: 백엔드 통합관제센터 규격 반영 (docs/updates/BACKEND_AURA_UPDATE_20260129.md)
  - resource_type: CASE, AGENT_ACTION, INTEGRATION
  - evidence_json.message: 스트림 표시용 메시지
  - ACTION_APPROVED, ACTION_ROLLED_BACK, INGEST_RECEIVED, INGEST_FAILED, DECISION_MADE 추가
- 2026-02-03: 작업.txt (Audit Events 명세) 반영
  - event_type: prefix 제거하여 발행 (SCAN_STARTED, DETECTION_FOUND 등)
  - outcome: FAILED, created_at, channel: AGENT
- 2026-02-01: C-1/C-2/C-3 보강 완료
  - C-1: event_category CASE 추가, SIMULATION_RUN→ACTION 카테고리, case_created/case_status_changed/case_assigned 헬퍼
  - C-2: evidence_json correlation 키(traceId, gatewayRequestId, caseId, caseKey, actionId) 보장, context에 case_id/case_key 추가
  - C-3: DETECTION_FOUND tags(driverType, severity), ACTION_PROPOSED 승인대기 시점 기록

---

## 11. Synapse 팀 전달 사항

**2안 적용 완료.** Synapse에서 다음 구현이 필요합니다.

1. **Redis Pub/Sub 구독**
   - 채널: `audit:events:ingest` (환경변수 `AUDIT_REDIS_CHANNEL`로 변경 가능)
   - Aura와 동일 Redis 인스턴스 사용 (`redis_url`)

2. **메시지 처리**
   - 수신 메시지: JSON 문자열 (AuditEvent 스키마)
   - 기존 AuditWriter 또는 audit_event_log 저장 로직에 전달

3. **필드 매핑** (작업.txt 6.3 메시지 형식)
   - event_type: prefix 제거 (AGENT/SCAN_STARTED → SCAN_STARTED)
   - outcome: FAIL → FAILED
   - created_at: timestamp ISO 8601
   - channel: AGENT
   - tenant_id: audit_event_log는 BIGINT. Aura는 문자열(예: tenant1) 발행 → Synapse에서 변환 필요 시 협의
