# SSE / HITL / Audit 점검 보고서

> **목표**: Aura(FastAPI + LangGraph)에서 (1) SSE 표준 헤더 수용/검증, (2) Last-Event-ID resume, (3) HITL approve/reject 후 그래프 재개, (4) audit/event 저장을 점검하고 보완안 제시  
> **작성일**: 2026-02  
> **근거**: 현재 구현 코드/테이블/라우트 기준 (추측 금지)

---

## 작업 범위

| 영역 | 경로 |
|------|------|
| SSE 라우트 | `api/routes/finance_agent.py`, `api/routes/aura_backend.py` |
| 미들웨어/의존성 | `api/middleware.py`, `api/dependencies.py` |
| HITL | `core/memory/hitl_manager.py`, `domains/finance/agents/finance_agent.py` |
| Audit/Event | `core/audit/`, `core/agent_stream/`, `tools/synapse_finance_tool.py` |
| DB | `database/models/`, alembic migrations |

---

## A. 표준 헤더 수용/검증

### A.1 SSE 라우트별 헤더 처리

#### Finance Agent (`POST /agents/finance/stream`)

| 헤더 | 읽기 | 검증 | 코드 근거 |
|------|------|------|-----------|
| **Authorization** | ✅ | ✅ | `CurrentUser` 의존성 → `get_current_user()` → `api/dependencies.py:22-59`. 미들웨어 `AuthMiddleware` (`api/middleware.py:68-76`) 선검증. 누락 시 **401** `{"detail": "Missing authorization header"}` |
| **X-Tenant-ID** | ✅ | ✅ | `TenantId` 의존성 → `get_tenant_id()` → `request.state.tenant_id`. `TenantMiddleware` (`api/middleware.py:127-144`)가 헤더에서 읽어 `request.state.tenant_id` 설정. JWT tenant_id와 불일치 시 **403** `{"detail": "Tenant ID mismatch"}` |
| **X-User-ID** | ❌ | ❌ | **finance_agent.py에서 읽지 않음**. `user.user_id`는 JWT `sub`에서만 추출 |
| **X-Agent-ID** | ❌ | ❌ | **코드베이스에 없음** |
| **Last-Event-ID** | ✅ | - | `Header(None, alias="Last-Event-ID")` (`finance_agent.py:59`) |

**로그**:
- 인증 실패: `api/middleware.py:72` `logger.warning("Missing Authorization header")`
- 토큰 무효: `api/middleware.py:93` `logger.warning("Invalid or expired token")`
- Tenant 불일치: `api/middleware.py:134` `logger.warning("Tenant ID mismatch: JWT=..., Header=...")`

#### Aura Backend (`POST /aura/test/stream`)

| 헤더 | 읽기 | 검증 | 코드 근거 |
|------|------|------|-----------|
| **X-User-ID** | ✅ | ✅ | `x_user_id = Header(None, alias="X-User-ID")` (`aura_backend.py:126`). JWT `sub`와 불일치 시 **error 이벤트 + [DONE]** (`aura_backend.py:156-171`). 401/400 HTTP가 아닌 SSE error 이벤트로 처리 |

### A.2 이벤트 payload 일관성

**Finance Agent** (`_enrich_event_data`, `finance_agent.py:44-50`):

```python
def _enrich_event_data(data, trace_id, case_id, tenant_id):
    data["trace_id"] = trace_id
    data["tenant_id"] = tenant_id
    if case_id:
        data["case_id"] = case_id
```

- **포함**: `trace_id`, `tenant_id`, `case_id`(있을 때)
- **미포함**: `user_id` — **보완 필요**

**적용 위치**: `start`, `hitl`, `failed`, `error`, `end`, `event_queue` 이벤트 (`finance_agent.py:100-105, 154-156, 167-193, 251-260, 262-269`)

### A.3 보완안

| 항목 | 현재 | 권장 |
|------|------|------|
| X-User-ID | finance_agent 미검증 | `Header(None, alias="X-User-ID")` 추가, JWT `sub`와 일치 검증 (aura_backend와 동일) |
| X-Agent-ID | 없음 | 요구사항 확인 후 필요 시 추가 |
| user_id in payload | 없음 | `_enrich_event_data`에 `data["user_id"] = user_id` 추가 |
| 401/400 응답 | Authorization/Tenant는 HTTP 401/403 | X-User-ID 불일치 시: aura_backend처럼 SSE error 또는 HTTP 400 선택 후 일관 적용 |

---

## B. Last-Event-ID resume 동작 검증

### B.1 현재 구현

**저장소**: **없음**. 이벤트/상태를 DB/Redis에 저장하지 않음.

**동작** (`finance_agent.py:91-98`):

```python
event_id_counter = 0
if last_event_id:
    try:
        last_id = int(last_event_id)
        event_id_counter = last_id + 1
        logger.info(f"Finance stream resuming from event ID: {last_event_id}")
    except (ValueError, TypeError):
        pass
```

- `Last-Event-ID` 수신 시 `event_id_counter`만 `last_id + 1`로 설정
- **실제 resume**: 없음. 재연결 시 **새 스트림(새 에이전트 실행)** 시작
- `event_id`만 `Last-Event-ID` 이후 값으로 이어 붙임

### B.2 resume 가능 범위

| 항목 | 현재 | 정의 |
|------|------|------|
| 이벤트 재전송 | ❌ | 이벤트 로그 미저장 → 재전송 불가 |
| 상태 재시작 | ❌ | 매 재연결 = 새 `event_generator()` = 새 agent 실행 |
| event_id 연속성 | ✅ | `event_id_counter = last_id + 1`로 id만 연속 |

**정리**: Last-Event-ID는 **event id 연속성**만 보장. **이벤트 replay/resume는 미구현**.

### B.3 보완안

1. **최소 checkpoint 규칙**
   - LangGraph Checkpointer: `SqliteSaver`/`MemorySaver` 사용 (`core/memory/checkpointer_factory.py`)
   - `thread_id` 기준으로 그래프 상태는 저장되나, **SSE 이벤트 로그는 저장하지 않음**
   - 이벤트 replay를 원하면: Redis/DB에 `(thread_id, event_id, event_json)` 저장 규칙 필요

2. **reconnect 시 중복 처리**
   - 현재: At-least-once, 클라이언트가 `id` 기준 dedupe (`docs/backend-integration/SSE_RECONNECT_POLICY.md`)
   - 재연결 시 스트림이 새로 시작되므로, 동일 `thread_id`로 재요청해도 **이전 이벤트 replay 없음** — 클라이언트는 새 스트림으로 처리

3. **개선 포인트**
   - 이벤트 replay 필요 시: Redis 등에 `stream:{thread_id}:events` 리스트로 이벤트 저장
   - `Last-Event-ID` 수신 시: 저장된 이벤트 중 `id > Last-Event-ID`만 재전송 후, 신규 이벤트 스트리밍

---

## C. HITL E2E 사이클 (Aura 측)

### C.1 HITL 요청 생성/저장

**생성 시점**: `_tools_node`에서 `propose_action` 등 HITL 도구 호출 시 `interrupt(payload)` (`finance_agent.py:226`)

**저장** (`hitl_manager.py:45-99`):

| 저장소 | 키 | TTL | 내용 |
|--------|-----|-----|------|
| Redis | `hitl:request:{request_id}` | 1800초 | requestId, sessionId, actionType, context, status, userId, tenantId |
| Redis | `hitl:session:{session_id}` | 3600초 | sessionId, requestId, userId, tenantId |

**키**: `trace_id`는 Redis 키에 없음. `session_id` = `finance_{user_id}_{timestamp}` (`finance_agent.py:89`). `case_id`는 `context`에 포함 가능.

### C.2 approve/reject 수신

**Aura 직접 엔드포인트** (`finance_agent.py:294-314`):

```python
@router.post("/approve")
async def approve_finance_action(request_id, approved, user, tenant_id):
    return {"request_id": request_id, "approved": approved, "status": "processed",
            "message": "승인 신호는 Synapse 백엔드를 통해 Redis Pub/Sub으로 전달됩니다."}
```

- **역할**: 스텁. Redis에 직접 publish하지 않음.
- **실제 흐름**: 프론트 → Synapse → Redis Pub/Sub → Aura `wait_for_approval_signal` 수신

**수신 처리** (`hitl_manager.py:102-161`):

- 채널: `hitl:channel:{session_id}`
- `wait_for_approval_signal()`가 Pub/Sub 구독 후 메시지 대기
- 수신 예: `{"type": "approval", "requestId": "...", "approved": true}` 또는 `{"type": "rejection", ...}`

### C.3 승인/거절 후 LangGraph 재개

**코드 흐름** (`finance_agent.py:161-214`):

```
1. interrupt 발생 → chunk에 __interrupt__
2. hitl_manager.save_approval_request() → Redis 저장
3. yield format_sse_event("hitl", hitl_data)
4. signal = await hitl_manager.wait_for_approval_signal(session_id)
5. signal이 None(타임아웃) → failed/error/end → [DONE] → return
6. signal["type"] == "rejection" → resume_value = {"approved": False}
7. else → resume_value = {"approved": True}
8. (승인 시) AgentAuditEvent.action_approved() 발행
9. break → while not stream_done 루프 계속
10. agent.stream(..., resume_value=resume_value) 재호출
```

**resume_value**: `{"approved": True}` 또는 `{"approved": False}`

**LangGraph**: `interrupt()`가 반환하는 값이 `resume_value`. `_tools_node`의 `decision = interrupt(payload)`가 이 값을 받아 `approval_results`에 반영 (`finance_agent.py:226-227`).

### C.4 승인 후 "tool 실행 → content → end/[DONE]" 완결 여부

**흐름**:

1. `resume_value` 설정 후 `break` → `stream_done = False` 유지
2. `agent.stream(..., resume_value=resume_value)` 재호출
3. 그래프가 interrupt 지점에서 재개, `decision`으로 승인/거절 반영
4. `_tools_node`: 승인된 tool만 실행, `ToolMessage` 반환
5. `reflect` 노드 → 최종 `AIMessage` 생성
6. `event_queue`에 content 등 적재
7. `while event_queue`에서 이벤트 yield
8. `end` 이벤트 → `[DONE]` (`finance_agent.py:262-269`)

**결론**: 승인 시 **tool 실행 → content → end/[DONE]**까지 이어짐. (`domains/finance/agents/finance_agent.py` 구조상 정상 동작)

### C.5 누락/보완 포인트

| 항목 | 상태 | 비고 |
|------|------|------|
| Aura `/approve` 직접 처리 | ❌ | 스텁. Synapse가 Redis publish 담당 |
| `request_id` ↔ `session_id` 매핑 | ✅ | `hitl:request:{request_id}`에 sessionId 저장. Synapse가 request_id로 조회 후 session_id로 publish |
| 타임아웃 시 [DONE] | ✅ | `finance_agent.py:194` |
| 거절 시 [DONE] | ⚠️ | `resume_value = {"approved": False}` 후 agent 재개 → `ToolMessage` "거절" → reflect → end. 별도 error 이벤트 없이 정상 종료 |

---

## D. Audit/Event 저장 (운영/감사 관점)

### D.1 현재 이벤트 저장 구조

| 이벤트 유형 | 발행처 | 전달 경로 | 저장처 |
|-------------|--------|-----------|--------|
| **audit_event_log** | `core/audit/writer.py` | Redis `audit:events:ingest` 또는 HTTP `POST /api/synapse/audit/events/ingest` | Synapse (audit_event_log) |
| **agent_event (Agent Stream)** | `core/agent_stream/writer.py` | HTTP `POST /api/synapse/agent/events` | Synapse (agent_activity_log) |

**Aura 로컬 DB**: `database/models/` 비어 있음. **audit_event, agent_trace, evidence_pack 테이블 없음**.

**Alembic**: `alembic/` 디렉터리 없음. 마이그레이션 미사용.

### D.2 Audit 이벤트 종류

`core/audit/schemas.py`, `tools/synapse_finance_tool.py`, `domains/finance/agents/hooks.py` 기준:

| 이벤트 | 발행 위치 |
|--------|-----------|
| SCAN_STARTED | hooks.py `on_node_start("analyze")` |
| SCAN_COMPLETED | hooks.py `on_node_end("tools")` |
| DETECTION_FOUND | synapse_finance_tool.py `get_case` |
| RAG_QUERIED | synapse_finance_tool.py `search_documents` |
| REASONING_COMPOSED | hooks.py `on_node_end("reflect")` |
| SIMULATION_RUN | synapse_finance_tool.py `simulate_action` |
| ACTION_PROPOSED | synapse_finance_tool.py `propose_action` |
| ACTION_APPROVED | finance_agent.py HITL 승인 시 |
| ACTION_EXECUTED | synapse_finance_tool.py `execute_action` |
| SAP_WRITE_SUCCESS/FAILED | synapse_finance_tool.py `execute_action` |

### D.3 최소 감사 패키지 규칙 제안

| 필드 | 현재 | 권장 |
|------|------|------|
| caseId | evidence_json, context | ✅ |
| userId | actor는 AGENT, user는 context | evidence_json에 `userId` 추가 |
| 승인자 | ACTION_APPROVED에 없음 | evidence_json에 `approvedBy` (user_id) 추가 |
| 조치 | actionId, event_type | ✅ |
| 근거 참조 | evidence_json (message, docIds 등) | ✅ |
| timestamp | created_at (ISO 8601) | ✅ |

### D.4 BE와 책임 분리

| 역할 | 담당 | 내용 |
|------|------|------|
| **Aura** | 이벤트 발행 | Redis Pub/Sub 또는 HTTP로 이벤트 전송. 로컬 DB 저장 없음 |
| **Synapse** | 이벤트 수집/저장 | `audit_event_log`, `agent_activity_log` 등에 저장 |
| **감사 쿼리** | Synapse/별도 서비스 | 저장된 로그 조회, 리포팅 |

---

## 요약 및 우선 보완 항목

| 구분 | 항목 | 현재 | 우선순위 |
|------|------|------|----------|
| A | X-User-ID 검증 (finance) | 미구현 | 높음 |
| A | user_id in SSE payload | 미포함 | 중간 |
| B | Last-Event-ID 이벤트 replay | 미구현 (id 연속만) | 요구사항에 따라 |
| C | Aura `/approve` 직접 처리 | 스텁 (Synapse 경유) | 설계 유지 시 불필요 |
| D | evidence_json에 userId, approvedBy | 일부 누락 | 중간 |

---

## 코드 근거 요약

| 항목 | 파일 | 라인 |
|------|------|------|
| Authorization 검증 | api/middleware.py | 68-99 |
| X-Tenant-ID | api/middleware.py | 112-147 |
| X-User-ID (aura_backend) | api/routes/aura_backend.py | 126, 156-171 |
| Last-Event-ID (finance) | api/routes/finance_agent.py | 59, 91-98 |
| _enrich_event_data | api/routes/finance_agent.py | 44-50 |
| HITL 저장 | core/memory/hitl_manager.py | 45-99 |
| HITL 대기 | core/memory/hitl_manager.py | 102-161 |
| interrupt/resume | domains/finance/agents/finance_agent.py | 216-227 |
| Audit 발행 | core/audit/writer.py | 119-135 |
| approve 스텁 | api/routes/finance_agent.py | 294-314 |
