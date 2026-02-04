# Agent Stream 명세 (Prompt C)

> Dashboard "Agent Execution Stream"을 실제 에이전트/워크플로우 상태 이벤트로 채우기

---

## ✅ Synapse 구현 확인 완료 (2026-02-04)

| 요구사항 | Synapse 구현 |
|----------|-------------|
| POST /api/synapse/agent/events | ✅ 구현됨 |
| Request body: `{ "events": [ {...}, ... ] }` | ✅ 지원 |
| Response: 200 OK | ✅ |
| agent_activity_log 적재 | ✅ 저장 |
| GET /api/synapse/dashboard/agent-stream?range=6h | ✅ 구현됨 |
| GET /api/synapse/dashboard/agent-activity | ✅ 별칭 (동일 API) |

**agent_event → Synapse 매핑**: tenantId(Long, 비숫자 스킵), timestamp→occurred_at, stage/stage, message→metadata_json.message, caseKey/caseId→resourceType=CASE, actionId→resourceType=ACTION, payload→metadata_json 병합.

---

## 1. 이벤트 모델 (C1)

**agent_event**:

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| tenantId | string | ✅ | 테넌트 ID (숫자 문자열 권장) |
| timestamp | datetime | ✅ | 발생 시각 (ISO 8601) |
| stage | string | ✅ | SCAN/DETECT/EXECUTE/SIMULATE/ANALYZE/MATCH |
| message | string | ✅ | 운영자 이해 가능 문장 |
| caseKey | string | | 케이스 표시 키 (예: CS-2026-0001) |
| caseId | string | | 케이스 ID |
| severity | string | | INFO/WARN/ERROR |
| traceId | string | | 요청 추적 ID |
| actionId | string | | 액션 ID (EXECUTE stage) |
| payload | object | | 추가 상세 |

---

## 2. 전송 방식 (C2)

**Aura → Synapse REST push** (택1 확정)

```
POST /api/synapse/agent/events
Content-Type: application/json

{
  "events": [
    {
      "tenantId": "1",
      "timestamp": "2026-02-01T12:00:00Z",
      "stage": "SCAN",
      "message": "케이스 목표 및 컨텍스트 분석을 시작합니다.",
      "caseKey": "CS-2026-0001",
      "caseId": "case-001",
      "severity": "INFO",
      "traceId": "trace-abc123"
    }
  ]
}
```

- **배치**: `events` 배열에 여러 건 전송 가능
- **Fire-and-forget**: Aura는 비동기로 push, 실패 시 로그만 남김

---

## 3. Dashboard API 연동 (C3)

- `GET /api/synapse/dashboard/agent-stream?range=6h` — REST push 이벤트 조회
- `GET /api/synapse/dashboard/agent-activity` — 동일 API (별칭)
- agent_activity_log 우선 조회, 없으면 audit_event_log fallback

---

## 4. Aura 구현 위치

| 구성요소 | 경로 |
|----------|------|
| 스키마 | `core/agent_stream/schemas.py` |
| Writer | `core/agent_stream/writer.py` |
| Audit 연동 | `core/audit/writer.py` - ingest_fire_and_forget 시 자동 emit |
| 샘플 시드 | `scripts/seed_agent_stream_events.py` |

**Audit → Agent Stream 변환**: Audit 이벤트 발행 시 자동으로 AgentEvent로 변환하여 push.

---

## 5. stage 매핑 (Audit event_type → Agent stage)

| Audit event_type | stage |
|------------------|-------|
| SCAN_STARTED, SCAN_COMPLETED | SCAN |
| DETECTION_FOUND | DETECT |
| RAG_QUERIED, REASONING_COMPOSED | ANALYZE |
| SIMULATION_RUN | SIMULATE |
| ACTION_PROPOSED, ACTION_APPROVED, ACTION_EXECUTED, ACTION_FAILED, ACTION_ROLLED_BACK | EXECUTE |
| SAP_WRITE_SUCCESS, SAP_WRITE_FAILED, CASE_* | EXECUTE |

---

## 6. 설정

```bash
# .env
AGENT_STREAM_EVENTS_ENABLED=true
# Gateway 경유 (운영): 포트 8080
AGENT_STREAM_PUSH_URL=http://localhost:8080/api/synapse/agent/events
# Backend 직접 (테스트용): 포트 8085
# AGENT_STREAM_PUSH_URL=http://localhost:8085/synapse/agent/events
```

- 미지정 시 `synapse_base_url` + `/api/synapse/agent/events` 사용

---

## 7. 샘플 이벤트 시각 확인

```bash
# 20건 샘플 생성 및 push (Synapse 실행 중일 때)
python scripts/seed_agent_stream_events.py

# dry-run (push 없이 로컬 출력만)
python scripts/seed_agent_stream_events.py --dry-run

# 25건 생성
python scripts/seed_agent_stream_events.py --count 25
```

---

## 8. Synapse 백엔드 (확인 완료)

**POST /api/synapse/agent/events** ✅ 구현 완료

- Request body: `{ "events": [ {...}, ... ] }`
- Response: 200 OK
- agent_activity_log 적재
- GET /api/synapse/dashboard/agent-stream?range=6h, agent-activity
