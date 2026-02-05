# Aura 이벤트 스키마 (Phase 0)

> **목적**: Agentic 실행 구조의 표준 이벤트 타입 및 payload 정의  
> **근거**: `api/schemas/events.py`, `api/schemas/hitl_events.py`, `api/routes/finance_agent.py`  
> **원칙**: 이벤트는 타입+payload 구조화, trace_id/case_id/tenant_id/user_id 필수 포함

---

## 1. 공통 필드 (모든 이벤트)

`_enrich_event_data` (`api/routes/finance_agent.py:44-55`)로 모든 SSE 이벤트에 추가:

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| trace_id | string | ✅ | 요청 추적 ID (UUID) |
| tenant_id | string | ✅ | 테넌트 식별자 |
| user_id | string | ✅ | 사용자 ID (JWT sub) |
| case_id | string | | 케이스 ID (context에 있을 때) |
| version | string | | 스키마 버전 (기본 "1.0") |

---

## 2. 이벤트 타입별 Payload

### 2.1 start

스트림 시작.

```json
{
  "type": "start",
  "message": "Finance agent started",
  "timestamp": 1706152860,
  "trace_id": "uuid-xxx",
  "tenant_id": "1",
  "user_id": "user-001",
  "case_id": "case-001",
  "version": "1.0"
}
```

**코드 근거**: `api/routes/finance_agent.py:126-131`

---

### 2.2 thought (analysis)

분석 단계 사고 과정.

```json
{
  "type": "thought",
  "thoughtType": "analysis",
  "content": "케이스 목표 및 컨텍스트 분석을 시작합니다.",
  "sources": [],
  "timestamp": 1706152860,
  "trace_id": "uuid-xxx",
  "tenant_id": "1",
  "user_id": "user-001",
  "case_id": "case-001",
  "version": "1.0"
}
```

**thoughtType**: analysis | planning | reasoning | decision | reflection  
**코드 근거**: `api/schemas/events.py:51-58`, `domains/finance/agents/hooks.py:56-62`

---

### 2.3 plan_step

계획 단계.

```json
{
  "type": "plan_step",
  "stepId": "uuid-step",
  "description": "케이스 조사 및 조치 제안",
  "status": "pending",
  "confidence": 0.8,
  "timestamp": 1706152860,
  "trace_id": "uuid-xxx",
  "tenant_id": "1",
  "user_id": "user-001",
  "case_id": "case-001",
  "version": "1.0"
}
```

**status**: pending | in_progress | completed | failed | skipped  
**코드 근거**: `api/schemas/events.py:60-69`, `domains/finance/agents/hooks.py:105-114`

---

### 2.4 tool_execution

도구 실행.

```json
{
  "type": "tool_execution",
  "toolName": "get_case",
  "toolArgs": {"caseId": "case-001"},
  "status": "success",
  "result": "{\"caseKey\":\"CS-2026-0001\",\"riskTypeKey\":\"DUPLICATE_INVOICE\"}",
  "requiresApproval": false,
  "timestamp": 1706152860,
  "trace_id": "uuid-xxx",
  "tenant_id": "1",
  "user_id": "user-001",
  "case_id": "case-001",
  "version": "1.0"
}
```

**status**: pending | running | success | failed | cancelled  
**코드 근거**: `api/schemas/events.py:93-103`, `domains/finance/agents/hooks.py:80-90, 115-126`

---

### 2.5 hitl (hitl_proposed)

HITL 승인 제안. Phase 0에서는 `hitl` 이벤트 타입 사용, payload에 proposal 포함.

```json
{
  "type": "hitl",
  "data": {
    "requestId": "req_abc123",
    "proposal_id": "req_abc123",
    "actionType": "propose_action",
    "action_type": "write_off",
    "message": "propose_action 실행을 승인하시겠습니까?",
    "context": {
      "caseId": "case-001",
      "actionType": "write_off",
      "payload": {}
    },
    "proposal": { "caseId": "case-001", "actionType": "write_off", "payload": {} },
    "evidence_refs": [
      { "type": "case", "source": "get_case", "ref": "case-001" },
      { "type": "documents", "source": "search_documents", "ref": "doc-1" }
    ],
    "requiresApproval": true
  },
  "trace_id": "uuid-xxx",
  "tenant_id": "1",
  "user_id": "user-001",
  "case_id": "case-001",
  "version": "1.0"
}
```

**필수 필드 (E2E)**: proposal_id, action_type, evidence_refs  
**코드 근거**: `api/schemas/hitl_events.py`, `api/routes/finance_agent.py`, `domains/finance/agents/finance_agent.py`

---

### 2.6 end

스트림 정상 종료.

```json
{
  "type": "end",
  "message": "Finance agent finished",
  "timestamp": 1706153000,
  "trace_id": "uuid-xxx",
  "tenant_id": "1",
  "user_id": "user-001",
  "case_id": "case-001",
  "version": "1.0"
}
```

**코드 근거**: `api/routes/finance_agent.py:288-293`

---

### 2.7 error

에러 발생. 실패/타임아웃 시 반드시 발행 (침묵 금지).

```json
{
  "type": "error",
  "error": "HITL 승인 요청이 300초 내에 응답되지 않아 작업이 중단되었습니다.",
  "errorType": "TimeoutError",
  "message": "사용자 응답 지연으로 작업이 취소되었습니다",
  "timestamp": 1706153300,
  "trace_id": "uuid-xxx",
  "tenant_id": "1",
  "user_id": "user-001",
  "case_id": "case-001",
  "version": "1.0"
}
```

**코드 근거**: `api/schemas/events.py:114-121`, `api/routes/finance_agent.py:272-282`

---

### 2.8 failed

HITL 타임아웃 등 작업 실패.

```json
{
  "type": "failed",
  "message": "사용자 응답 지연으로 작업이 취소되었습니다",
  "error": "HITL approval timeout",
  "errorType": "TimeoutError",
  "requestId": "req_abc123",
  "sessionId": "finance_user-001_1706152860",
  "timestamp": 1706153300,
  "trace_id": "uuid-xxx",
  "tenant_id": "1",
  "user_id": "user-001",
  "case_id": "case-001",
  "version": "1.0"
}
```

**코드 근거**: `api/schemas/events.py:124-132`, `api/routes/finance_agent.py:193-203`

---

## 3. 이벤트 흐름 (Finance Agent)

```
start → thought(analysis) → plan_step → tool_execution* → [hitl] → content → end → [DONE]
                                                              ↑
                                                    propose_action 시에만
```

에러/타임아웃 시: `... → failed → error → end → [DONE]`

---

## 4. SSE 형식

```
event: {event_type}
id: {event_id}
data: {json_payload}

data: [DONE]
```

**코드 근거**: `api/routes/aura_backend.py:format_sse_event`, `api/routes/finance_agent.py`
