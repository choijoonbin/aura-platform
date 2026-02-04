# SSE / HITL 실행 체크리스트 + DoD + 검증 시나리오

> **목적**: P0/P1/P2 이슈 닫기를 위한 실행 체크리스트, Definition of Done, 검증 절차 정리  
> **근거**: `docs/guides/SSE_HITL_AUDIT_VERIFICATION_REPORT.md` 및 실제 코드 (추정 금지)  
> **작성일**: 2026-02

---

## (A) 팀별 실행 체크리스트 (Aura 기준 P0/P1/P2)

### P0 — 계약/보안

#### (P0-1) Finance stream에서 X-User-ID 수용/검증 정책 통일 ✅ 적용됨

| 항목 | 현재 상태 (코드 근거) | 보완안 |
|------|------------------------|--------|
| **읽기** | ✅ `x_user_id: str \| None = Header(None, alias="X-User-ID")` | `api/routes/finance_agent.py:60` |
| **검증** | ✅ X-User-ID가 있으면 JWT `sub`와 **반드시 일치** 검증 | `finance_agent.py:88-103` |
| **일치 규칙** | ✅ `x_user_id and x_user_id != user.user_id` → 거부 | event_generator 진입 직후 |
| **불일치 시 응답** | ✅ SSE error + [DONE] (aura_backend 패턴) | `format_sse_event("error", {...})` + `data: [DONE]` + return |
| **참조** | aura_backend: `api/routes/aura_backend.py:126, 156-171` | 동일 패턴 적용 완료 |

**결정안 (P0-1)**  
- **옵션 B (SSE error)** 적용 완료.

---

#### (P0-2) 모든 SSE 이벤트 payload에 tenant/user/case/trace 필드 일관성 점검 ✅ 적용됨

| 필드 | 현재 포함 여부 | 코드 근거 |
|------|----------------|-----------|
| **trace_id** | ✅ | `_enrich_event_data` (`finance_agent.py:46-52`) |
| **tenant_id** | ✅ | `_enrich_event_data` (`finance_agent.py:47`) |
| **case_id** | ✅ (있을 때) | `if case_id: data["case_id"] = case_id` |
| **user_id** | ✅ | `data["user_id"] = user_id` (`finance_agent.py:50`) |

**적용 경로** (`finance_agent.py`): start, hitl, failed/error/end, event_queue, end, error — 모든 `_enrich_event_data` 호출에 `user_id` 전달.

---

### P1 — 신뢰성

#### (P1-1) Last-Event-ID 의미 정의

| 지원 유형 | 현재 구현 | 코드 근거 |
|-----------|-----------|-----------|
| **이벤트 ID 연속성** | ✅ | `finance_agent.py:91-98` — `event_id_counter = last_id + 1` |
| **이벤트 재전송(replay)** | ❌ | 이벤트 로그 미저장. 저장소 없음 |

**정의**: Aura는 **"이벤트 ID 연속성"**만 지원. **"이벤트 재전송(replay)"**는 지원하지 않음.

- 재연결 시: **새 스트림(새 에이전트 실행)**이 시작됨.
- `Last-Event-ID`는 **새 스트림의 event id**를 `last_id + 1`부터 이어 붙이는 데만 사용됨.
- `docs/backend-integration/SSE_RECONNECT_POLICY.md` §3.2: "이벤트 로그를 영속 저장하지 않는다" 명시.

---

#### (P1-2) replay 미지원 시 FE/BE 전달용 계약 문구(제약사항)

**계약 문구 (FE/BE 전달용)**:

> **Aura SSE Last-Event-ID 제약사항**  
> Aura의 `POST /agents/finance/stream` 및 `POST /aura/test/stream`은 `Last-Event-ID` 헤더를 수용하나, **과거 이벤트의 재전송(replay)을 지원하지 않습니다**.  
> - 재연결 시 클라이언트가 `Last-Event-ID`를 보내면, 서버는 **새 스트림**을 시작하며 이벤트 ID만 `Last-Event-ID + 1`부터 이어 붙입니다.  
> - **이미 전송된 이벤트의 재전송은 수행되지 않습니다.** 클라이언트는 재연결 시 **새 스트림**으로 처리하고, 필요 시 `thread_id`를 유지하여 동일 대화로 이어갈 수 있습니다.  
> - At-least-once 전달을 전제로 하며, 중복 제거는 클라이언트가 이벤트 `id` 기준으로 수행합니다.

---

#### (P1-3) replay 필요 시 최소 설계안 (참고)

replay를 요구사항으로 확정할 경우:

| 항목 | 제안 |
|------|------|
| **저장소** | Redis (또는 DB) |
| **키** | `stream:events:{thread_id}` (LIST) 또는 `stream:events:{trace_id}` |
| **저장 단위** | `{event_id, event_type, data, timestamp}` |
| **보존기간** | TTL 1시간~24시간 (설정값) |
| **중복처리** | 클라이언트 `id` 기준 dedupe. 서버는 `id > Last-Event-ID` 이벤트만 재전송 |
| **복구 절차** | 1) Last-Event-ID 수신 2) 저장소에서 `id > Last-Event-ID` 조회 3) 순차 재전송 4) 신규 이벤트 스트리밍 계속 |

**현재**: 미구현. 요구사항 확정 후 설계/구현.

---

### P2 — 운영/감사

#### (P2-1) HITL 요청/승인/거절/조치 결과 DB 저장 범위

| 단계 | Aura 저장 | Synapse 저장 | 코드 근거 |
|------|-----------|--------------|-----------|
| **HITL 요청** | Redis `hitl:request:{request_id}`, `hitl:session:{session_id}` | - | `hitl_manager.py:45-99` |
| **승인/거절** | - | BE가 Redis Pub/Sub 발행. Aura는 수신만 | `finance_agent.py:294-314` (approve 스텁) |
| **조치 결과** | - | audit_event_log (Aura가 Redis로 발행) | `core/audit/writer.py`, `finance_agent.py:203-210` |

**Aura 로컬 DB**: 없음. `database/models/` 비어 있음. Alembic 미사용.

**저장 범위 정리**:

| 테이블/저장소 | 담당 | 저장 내용 |
|---------------|------|-----------|
| Redis `hitl:request:*` | Aura | requestId, sessionId, actionType, context, userId, tenantId (TTL 30분) |
| Redis `hitl:session:*` | Aura | sessionId, requestId, userId, tenantId (TTL 60분) |
| audit_event_log | Synapse | Aura가 Redis `audit:events:ingest`로 발행 → Synapse 저장 |
| agent_activity_log | Synapse | Aura가 HTTP `POST /api/synapse/agent/events`로 발행 |

**HITL 관련 audit 이벤트**: ACTION_PROPOSED, ACTION_APPROVED (`finance_agent.py:203-210`), ACTION_EXECUTED, ACTION_FAILED (`synapse_finance_tool.py`).

---

#### (P2-2) BE Audit와 Aura Audit 책임 분리

| 역할 | 담당 | 책임 |
|------|------|------|
| **Aura** | 이벤트 발행 | Redis `audit:events:ingest` 또는 HTTP `POST /api/synapse/audit/events/ingest`로 이벤트 전송. 로컬 DB 저장 없음. |
| **Synapse** | 이벤트 수집/저장 | Redis 구독 또는 HTTP 수신 → `audit_event_log`, `agent_activity_log` 저장 |
| **중복 방지** | - | Aura는 발행만. Synapse가 단일 수집점. 중복 수신 시 Synapse에서 idempotency 처리 |
| **누락 방지** | - | Aura: 발행 실패 시 로그 (`core/audit/writer.py`). Synapse: 수신/저장 실패 시 재시도 정책 |

---

## (B) Definition of Done (DoD)

### P0-1: X-User-ID 검증 (Finance stream)

| DoD 항목 | 내용 |
|----------|------|
| **현재 구현 증거** | `finance_agent.py`: X-User-ID 파라미터/검증 없음. `api/dependencies.py:22-59`에서 `user.user_id`(JWT sub)만 사용 |
| **정책 적용 후 기대** | X-User-ID가 있고 JWT `sub`와 불일치 시, event_generator 내 첫 yield 전 SSE `event: error` + [DONE] 발행 후 return |
| **오류 코드/메시지** | SSE `event: error`, `data: {"errorType":"ValidationError", "message":"X-User-ID does not match JWT sub claim", "timestamp":...}` |
| **로그 필드** | `logger.warning(f"X-User-ID mismatch: header={x_user_id}, jwt_sub={user.user_id}, tenant_id={tenant_id_val}, trace_id={trace_id}")` |
| **운영 위험·완화** | 위험: X-User-ID 누락 시 검증 스킵 → JWT만 신뢰. 완화: Gateway에서 X-User-ID 필수 전달 정책, Aura는 "있으면 검증" |

---

### P0-2: tenant/user/case/trace payload 일관성

| DoD 항목 | 내용 |
|----------|------|
| **현재 구현 증거** | `finance_agent.py:44-50` `_enrich_event_data`. trace_id, tenant_id, case_id 포함. user_id 미포함 |
| **정책 적용 후 기대** | 모든 SSE data에 `trace_id`, `tenant_id`, `user_id` 포함. `case_id`는 context에 있을 때만 |
| **오류 코드/메시지** | 해당 없음 (enrichment) |
| **로그 필드** | 요청 로깅에 tenantId, userId, traceId, caseId 포함 (`api/middleware.py` RequestLoggingMiddleware 확장 가능) |
| **운영 위험·완화** | 위험: user_id 누락 시 drill-down/감사 추적 어려움. 완화: _enrich_event_data에 user_id 추가로 모든 이벤트에 포함 |

---

### P1-1/P1-2: Last-Event-ID 의미 및 제약 고지

| DoD 항목 | 내용 |
|----------|------|
| **현재 구현 증거** | `finance_agent.py:91-98`, `aura_backend.py:176-184`. event_id_counter만 `last_id + 1`로 갱신. 저장소 없음 |
| **정책 적용 후 기대** | 변경 없음. "id 연속만 지원, replay 미지원" 문서화 및 FE/BE 전달 |
| **오류 코드/메시지** | 해당 없음 |
| **로그 필드** | `logger.info(f"Finance stream resuming from event ID: {last_event_id}")` (91-96) |
| **운영 위험·완화** | 위험: FE/BE가 replay를 기대할 수 있음. 완화: 본 문서 (D) 계약 문구 전달, API 명세에 제약 명시 |

---

### P2-1/P2-2: HITL/Audit 저장 및 책임 분리

| DoD 항목 | 내용 |
|----------|------|
| **현재 구현 증거** | `hitl_manager.py:45-99` Redis 저장, `core/audit/writer.py:119-135` Redis/HTTP 발행, `core/agent_stream/writer.py` |
| **정책 적용 후 기대** | (A) P2-1, P2-2 표에 따른 저장 범위·책임 분리 유지 |
| **오류 코드/메시지** | Aura 발행 실패 시 `logger.warning` (`core/audit/writer.py`). Synapse 수신 실패 시 Synapse 재시도 |
| **로그 필드** | tenantId, userId, traceId, caseId — audit evidence_json, agent_event payload에 포함 |
| **운영 위험·완화** | 위험: Redis 장애 시 HITL signal 유실. 완화: TTL 내 재시도, Synapse가 approve API 호출 시 Redis publish 보장 |

---

## (C) 검증 시나리오 (로컬/통합)

### (S0) Finance stream — X-User-ID 누락/불일치 시 401/400

**전제**: P0-1 정책 확정 후 (400 또는 SSE error 선택)

**절차**:
1. 유효한 JWT로 `POST /agents/finance/stream` 호출 (body: prompt, context 등)
2. **케이스 A**: `X-User-ID` 헤더 없음 → (정책에 따라) 통과 또는 검증 스킵
3. **케이스 B**: `X-User-ID: wrong_user` (JWT `sub`와 불일치) → 400 또는 SSE error 이벤트 + [DONE]

**검증**:
- HTTP 400 선택 시: `resp.status_code == 400`, `"X-User-ID"` 또는 `"jwt"` in `resp.json()["detail"].lower()`
- SSE error 선택 시: 첫 번째 `event: error` 수신, 이후 `data: [DONE]`

**코드 근거**: 정책 적용 후 `finance_agent.py` event_generator 진입 직전 또는 내부.

---

### (S1) HITL 발생 → approve signal 수신 → content/end/[DONE] 완결

**절차**:
1. `POST /agents/finance/stream` — HITL이 발생하는 프롬프트 (예: propose_action 호출 유도)
2. `event: hitl` 수신, `requestId`, `sessionId` 추출
3. Synapse `POST /api/aura/hitl/approve/{requestId}` (또는 동등 API) 호출
4. Synapse가 Redis `hitl:channel:{session_id}`에 `{"type":"approval","approved":true}` 발행
5. Aura가 signal 수신 후 스트림 재개
6. `event: content` 또는 `event: tool_execution` (SUCCESS) 수신
7. `event: end` 수신
8. `data: [DONE]` 수신

**검증**:
- hitl 이후 content/end/[DONE] 순서로 수신
- 타임아웃 없이 완료

**코드 근거**: `finance_agent.py:161-214`, `hitl_manager.py:102-161`, `domains/finance/agents/finance_agent.py:216-283`

---

### (S2) SSE 재연결 — Last-Event-ID 제공 시 "이어받기" 범위

**절차**:
1. `POST /agents/finance/stream` (Last-Event-ID 없음) — 스트림 시작
2. 이벤트 수신 (예: id 1, 2, 3)
3. 연결 강제 종료
4. **동일 body**로 `Last-Event-ID: 3` 헤더 추가하여 재요청
5. 수신 이벤트 관찰

**기대 (현재 구현)**:
- **새 스트림** 시작 (새 start, 새 에이전트 실행)
- 수신 이벤트의 `id`는 **4 이상** (1, 2, 3은 재전송되지 않음)
- 이전 스트림의 이벤트 replay 없음

**검증**:
- 첫 이벤트가 `event: start`, `id: 4` (또는 4 이상)
- `id` 1, 2, 3 재전송 없음

**코드 근거**: `finance_agent.py:91-98`, `event_generator`는 매 요청마다 새로 생성됨

---

### (S3) tool_execution 이벤트에 trace/case 정보 일관 포함

**절차**:
1. `POST /agents/finance/stream` — context에 `caseId` 포함
2. tool 호출 발생 (get_case, propose_action 등)
3. `event: tool_execution` 수신
4. `data` JSON 파싱

**검증**:
- `data.trace_id` 존재
- `data.tenant_id` 존재
- `data.case_id` 존재 (context에 caseId 있을 때)
- (P0-2 적용 후) `data.user_id` 존재

**코드 근거**: `finance_agent.py:252-261` — `event_queue` 이벤트가 `_enrich_event_data`로 보강됨. `domains/finance/agents/hooks.py:80-90` — ToolExecutionEvent는 toolName, toolArgs, status, requiresApproval만 포함, route에서 trace/tenant/case 추가.

---

## (D) FE/BE에 전달할 계약 문구

아래 문구를 FE/BE 팀에 전달하여 계약을 확정한다.

| 구분 | 계약 문구 |
|------|-----------|
| **Replay 미지원** | Aura SSE는 `Last-Event-ID`를 수용하나 **과거 이벤트 재전송(replay)을 지원하지 않습니다.** 재연결 시 새 스트림이 시작되며, 이벤트 ID만 `Last-Event-ID + 1`부터 이어 붙입니다. |
| **X-User-ID 검증** | `X-User-ID` 헤더가 있으면 JWT `sub`와 **반드시 일치**해야 합니다. 불일치 시 SSE `event: error` 후 `[DONE]`으로 스트림이 종료됩니다. |
| **클라이언트 중복 제거** | At-least-once 전달을 전제로 하며, **중복 제거는 클라이언트가 이벤트 `id` 기준으로 수행**합니다. |
| **Payload 필드** | 모든 SSE 이벤트 `data`에는 `trace_id`, `tenant_id`, `user_id`(P0-2 적용 후), `case_id`(context에 있을 때)가 포함됩니다. |

---

## 5. 최종 결론

- **현재 Aura SSE는 replay가 아니라 id 연속만 지원합니다.** `Last-Event-ID`는 새 스트림의 이벤트 ID를 이어 붙이는 데만 사용되며, 이미 전송된 이벤트의 재전송은 수행되지 않습니다.
- FE/BE는 위 (D) 계약 문구를 준수하고, 재연결 시 새 스트림으로 처리하며 클라이언트에서 `id` 기준 dedupe을 수행합니다.

---

## 6. 코드 근거 요약

| 항목 | 파일 | 라인 |
|------|------|------|
| X-User-ID (Finance stream) | api/routes/finance_agent.py | 60, 88-103 |
| X-User-ID (aura_backend) | api/routes/aura_backend.py | 126, 156-171 |
| _enrich_event_data | api/routes/finance_agent.py | 44-55 |
| Last-Event-ID | api/routes/finance_agent.py | 59, 91-98 |
| event_queue enrich | api/routes/finance_agent.py | 252-261 |
| HITL save | core/memory/hitl_manager.py | 45-99 |
| HITL wait | core/memory/hitl_manager.py | 102-161 |
| HITL resume | api/routes/finance_agent.py | 161-214 |
| Audit 발행 | core/audit/writer.py | 119-135 |
| ToolExecutionEvent | api/schemas/events.py | 93-103 |
| hooks tool_execution | domains/finance/agents/hooks.py | 80-90 |
