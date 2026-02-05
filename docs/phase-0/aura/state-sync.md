# Aura 상태 동기화 규칙 (Phase 0)

> **목적**: HITL 승인/거절 이벤트 수신, resume 처리, 재시도 정책  
> **근거**: `core/memory/hitl_manager.py`, `api/routes/finance_agent.py`, `domains/finance/agents/finance_agent.py`  
> **원칙**: propose → approve/reject → resume 기본 흐름 고정

---

## 1. HITL 기본 흐름

```
[Agent] propose_action 호출
    → interrupt(payload) [LangGraph]
    → HitlManager.save_approval_request()
    → SSE hitl 이벤트 발행
    → HitlManager.wait_for_approval_signal() [Redis 구독]
    ← Redis PUBLISH (Synapse/BE)
    → resume_value = {"approved": true|false}
    → agent.stream(resume_value=Command(resume=resume_value))
    → [승인 시] execute_action 등 계속 / [거절 시] ToolMessage("사용자가 거절했습니다")
```

---

## 2. 승인/거절 이벤트 수신 방식

### 2.1 Redis Pub/Sub

| 항목 | 내용 |
|------|------|
| **채널** | `hitl:channel:{session_id}` |
| **구독** | Aura `HitlManager.wait_for_approval_signal(session_id, timeout)` |
| **발행** | Synapse 백엔드 (사용자 승인/거절 시) |

**코드 근거**: `core/memory/hitl_manager.py:102-161`

### 2.2 신호 형식

**승인**:
```json
{
  "type": "approval",
  "requestId": "req_abc123",
  "status": "approved",
  "approved": true,
  "timestamp": 1706152860
}
```

**거절**:
```json
{
  "type": "rejection",
  "requestId": "req_abc123",
  "status": "rejected",
  "approved": false,
  "reason": "사용자 거절",
  "timestamp": 1706152860
}
```

**코드 근거**: `api/routes/finance_agent.py:196-212` — `signal.get("type") == "rejection"` → `resume_value = {"approved": False}`

---

## 3. Resume 처리 방식

### 3.1 LangGraph Command

```python
from langgraph.types import Command

if resume_value is not None:
    input_data = Command(resume=resume_value)
else:
    input_data = { "messages": [...], ... }
```

**코드 근거**: `domains/finance/agents/finance_agent.py:273-286`

### 3.2 resume_value 형식

| 값 | 동작 |
|----|------|
| `{"approved": true}` | 승인된 도구 실행, 나머지 그래프 계속 |
| `{"approved": false}` | ToolMessage("사용자가 액션 실행을 거절했습니다") 반환, 그래프 계속 |

**코드 근거**: `domains/finance/agents/finance_agent.py:225-281`

### 3.3 Checkpoint

- **thread_id**: `config["configurable"]["thread_id"]` 로 checkpoint 복원
- **저장**: LangGraph Checkpointer (SqliteSaver 또는 MemorySaver)
- **코드 근거**: `core/memory/checkpointer_factory.py`, `domains/finance/agents/finance_agent.py:71-76`

---

## 4. Redis 저장 키

| 키 | TTL | 내용 |
|----|-----|------|
| `hitl:request:{request_id}` | 30분 | requestId, sessionId, actionType, context, userId, tenantId |
| `hitl:session:{session_id}` | 60분 | sessionId, requestId, userId, tenantId |

**코드 근거**: `core/memory/hitl_manager.py:80-99`

---

## 5. 재시도 정책

### 5.1 HITL 타임아웃

| 항목 | 값 |
|------|-----|
| **기본 타임아웃** | `settings.hitl_timeout_seconds` (기본 300초) |
| **타임아웃 시** | `wait_for_approval_signal()` → None 반환 |
| **처리** | failed 이벤트 → error 이벤트 → end 이벤트 → [DONE] |

**코드 근거**: `api/routes/finance_agent.py:161-220`

### 5.2 Synapse 도구 재시도

- 5xx, timeout: exponential backoff, `synapse_max_retries` 회
- **코드 근거**: `tools/synapse_finance_tool.py:55-116`

---

## 6. 추가 evidence 질문 후 종료 (Phase A)

Phase A DoD: "approve/reject 이벤트 수신 후 resume 또는 **추가 evidence 질문 후 종료**"

- 거절 시: `resume_value = {"approved": False}` → Agent가 "추가 evidence가 필요합니다" 등으로 최종 응답 생성 → reflect → end
- 구현: Finance Agent `_reflect_node` 또는 LLM 응답에서 처리
