# 추가 작업 필요 항목 - 담당 및 전달 프롬프트

> `docs/20260203/FRONTEND_V1_IMPLEMENTATION.md`의 "추가 작업 필요" 항목별 담당팀 및 작업 요청 프롬프트

---

## ✅ 프론트엔드 HITL UI 연동 완료 (회신 반영)

**dwp-frontend** 팀에서 `HITL_APPROVAL_UI_INTEGRATION.md` 전달 후 구현 완료 회신 수신 완료.

**참고 문서**: `dwp-frontend/docs/reference/HITL_APPROVAL_UI_INTEGRATION.md`

**구현 위치** (dwp-frontend):
- `libs/shared-utils/src/agent/hitl-api.ts` - approveHitlRequest, rejectHitlRequest
- `libs/shared-utils/src/agent/use-synapse-agent-stream.ts` - hitl 이벤트 파싱
- `apps/dwp/src/components/aura/aura-mini-overlay.tsx` - Mini Overlay HITL UI
- `apps/dwp/src/pages/aiworkspace/hooks/use-ai-workspace.ts` - Full Workspace HITL
- `apps/remotes/synapsex/.../case-hitl-drawer.tsx`, `use-case-hitl.ts` - Case Detail HITL

---

## ✅ 백엔드 HITL API 완료 (회신 반영)

**dwp-backend** 팀에서 HITL 승인/거절 API 구현 완료 회신.

**참고 문서**: `dwp-backend/docs/integration/AURA_PLATFORM_UPDATE.md`

**구현 내용**:
- `POST /api/aura/hitl/approve/{requestId}` - 승인 처리
- `POST /api/aura/hitl/reject/{requestId}` - 거절 처리
- Redis Pub/Sub 신호 발행 (`hitl:channel:{sessionId}`)
- 신호 저장 (`hitl:signal:{sessionId}`) - TTL: 5분
- 신호 조회 API: `GET /api/aura/hitl/signals/{sessionId}` (폴링 fallback)

**HITL 신호 형식** (백엔드 → Aura-Platform):
- 승인: `{ "type": "approval", "requestId": "...", "status": "approved", "timestamp": 1706152860 }`
- 거절: `{ "type": "rejection", "requestId": "...", "status": "rejected", "reason": "...", "timestamp": 1706152860 }`

---

## 📋 담당 매트릭스

| 항목 | 담당 | 상태 | 비고 |
|------|------|------|------|
| 승인 API 완성 | **백엔드** (dwp_backend/Synapse) | ✅ 완료 | dwp-backend `docs/integration/AURA_PLATFORM_UPDATE.md` |
| HITL 승인 UI 연동 | **프론트엔드** | ✅ 완료 | dwp-frontend `docs/reference/HITL_APPROVAL_UI_INTEGRATION.md` |
| 테스트 스크립트 | **Aura-Platform** 또는 QA | 대기 | E2E/통합 테스트 |
| 문서화 완성 | **Aura-Platform** | 대기 | API 문서, 연동 가이드 |

---

## 🔧 1. 백엔드 담당: 승인 API 완성

### 전달 받을 내용 (Aura-Platform → Backend)
- HITL Redis Pub/Sub 채널: `hitl:channel:{sessionId}`
- 승인/거절 신호 JSON 스키마
- `hitl:request:{requestId}` 조회 (Redis)
- 상세 스펙: `docs/handoff/BACKEND_HANDOFF.md`

### 백엔드 팀 전달 프롬프트

```
## 작업: HITL 승인/거절 API 구현

Aura-Platform에서 SSE 스트리밍 중 `hitl` 이벤트를 발행하면, 프론트엔드가 사용자에게 승인/거절 UI를 보여줍니다. 
사용자가 승인/거절을 선택하면 **백엔드 API**를 호출하고, 백엔드는 Redis Pub/Sub으로 Aura-Platform에 신호를 전달해야 합니다.

### 구현할 API

1. **POST /api/aura/hitl/approve/{requestId}**
   - Request: `{ "userId": "user123" }` (또는 JWT에서 추출)
   - Response: `{ "status": "SUCCESS", "data": { "requestId", "sessionId", "status": "approved" } }`
   - 동작: Redis `hitl:request:{requestId}` 조회 → sessionId 추출 → Redis Pub/Sub 발행

2. **POST /api/aura/hitl/reject/{requestId}**
   - Request: `{ "userId": "user123", "reason": "사용자 거절" }` (reason 선택)
   - Response: `{ "status": "SUCCESS", "data": { "requestId", "sessionId", "status": "rejected", "reason" } }`
   - 동작: 동일하게 Redis 조회 후 Pub/Sub 발행

### Redis Pub/Sub 발행 스펙

- **채널**: `hitl:channel:{sessionId}` (hitl:request에서 sessionId 조회)
- **승인 신호**:
  ```json
  { "type": "approval", "requestId": "req-xxx", "approved": true, "timestamp": 1706152860 }
  ```
- **거절 신호**:
  ```json
  { "type": "rejection", "requestId": "req-xxx", "reason": "사용자 거절", "timestamp": 1706152860 }
  ```

### 참고 문서
- `docs/handoff/BACKEND_HANDOFF.md` (라인 96~251): 상세 스펙, Java 예시 코드
- Finance Agent: `POST /agents/finance/approve` (params: request_id, approved) - 동일 패턴
```

---

## 🎨 2. 프론트엔드 담당: HITL 승인 UI 연동

### 전달 받을 내용 (Aura-Platform → Frontend)
- SSE `hitl` 이벤트 데이터 형식
- 백엔드 승인/거절 API 경로 (백엔드 구현 후)
- `requestId`, `sessionId` 사용 방법

### 프론트엔드 팀 전달 프롬프트

```
## 작업: HITL 승인 UI → 백엔드 API 연동

SSE 스트리밍 중 `event: hitl` 이벤트를 수신하면, 사용자에게 승인/거절 다이얼로그를 표시하고, 
사용자 선택 시 백엔드 API를 호출해야 합니다.

### 수신할 hitl 이벤트 형식 (data 필드)

```json
{
  "type": "hitl",
  "requestId": "req_abc123",
  "actionType": "propose_action",
  "message": "propose_action 실행을 승인하시겠습니까?",
  "context": { "caseId": "...", "actionType": "..." },
  "trace_id": "...",
  "tenant_id": "...",
  "case_id": "..."
}
```

### 구현할 동작

1. **hitl 이벤트 수신 시**
   - 승인/거절 모달/다이얼로그 표시
   - `message`, `context`를 사용해 사용자에게 설명
   - `requestId` 저장 (API 호출 시 필요)

2. **승인 버튼 클릭 시**
   - `POST /api/aura/hitl/approve/{requestId}` 호출
   - (또는 백엔드가 제공하는 최종 경로, 예: `/api/agents/finance/approve?request_id=xxx&approved=true`)
   - 성공 시: 모달 닫기, SSE 스트림은 자동으로 재개됨 (Aura-Platform이 Redis 신호 수신)

3. **거절 버튼 클릭 시**
   - `POST /api/aura/hitl/reject/{requestId}` 호출
   - Body: `{ "reason": "사용자가 거절했습니다" }` (선택)
   - 성공 시: 모달 닫기, 스트림 종료

### API 경로 확인
- 백엔드 팀에 최종 API 경로 확인 필요
- Finance Agent: `POST /agents/finance/approve` (query: request_id, approved: boolean)
- Enhanced Agent: `/api/aura/hitl/approve/{requestId}`, `/api/aura/hitl/reject/{requestId}` (BACKEND_HANDOFF 기준)
```

---

## 🧪 3. 테스트 스크립트 작성 (Aura-Platform 또는 QA)

### 전달 받을 내용
- API 스펙 (SSE, approve)
- Redis Pub/Sub 테스트 방법

### 테스트 담당 팀 전달 프롬프트

```
## 작업: HITL E2E 테스트 스크립트 작성

다음 시나리오를 자동화 테스트로 검증하는 스크립트를 작성해주세요.

### 시나리오 1: SSE 스트리밍 수신
- POST /agents/finance/stream (또는 /agents/v2/chat/stream) 호출
- SSE 이벤트 순서 검증: start → thought → plan_step → tool_execution → (hitl) → content → end
- 각 이벤트의 data 필드에 trace_id, tenant_id 포함 여부 확인

### 시나리오 2: HITL 승인 플로우 (propose_action 등)
1. 스트림 시작
2. hitl 이벤트 수신 대기 (타임아웃 60초)
3. hitl 수신 시 requestId 추출
4. Redis Pub/Sub으로 승인 신호 발행: `PUBLISH hitl:channel:{sessionId} '{"type":"approval","requestId":"xxx","approved":true}'`
5. 스트림이 정상 종료되는지 확인

### 시나리오 3: HITL 거절 플로우
- 위와 동일하나, type: "rejection" 발행
- 스트림이 error/end로 종료되는지 확인

### 참고
- sessionId: hitl 이벤트 또는 스트림 초기 응답에서 확인
- Redis 테스트: `redis-cli PUBLISH hitl:channel:{sessionId} '{"type":"approval","requestId":"req_xxx","approved":true}'`
```

---

## 📝 4. 문서화 완성 (Aura-Platform)

### Aura-Platform 담당 프롬프트

```
## 작업: 프론트엔드 명세 v1.0 연동 문서화 완성

다음 문서를 보완해주세요.

1. **API 레퍼런스**
   - POST /agents/v2/chat/stream: Request/Response 스키마, 모든 SSE 이벤트 타입 설명
   - POST /agents/finance/stream: Finance 도메인 전용 스펙
   - HITL 이벤트 상세 (hitl 필드 구조, requestId/sessionId 용도)

2. **연동 플로우 다이어그램**
   - Frontend → Backend → Redis → Aura-Platform HITL 플로우
   - SSE 이벤트 순서 타임라인

3. **에러 처리 가이드**
   - 타임아웃, 연결 끊김, Last-Event-ID 재연결
   - error/failed 이벤트 형식

4. **기존 문서 업데이트**
   - docs/README.md: 20260203 문서 링크
   - CHANGELOG.md: 완료 항목 반영
```

---

## 📌 요약: 누가 무엇을 받아서 하는가

| 담당 | 받는 입력 | 하는 작업 |
|------|-----------|-----------|
| **백엔드** | BACKEND_HANDOFF.md, Redis 채널/신호 스펙 | approve/reject API 구현, Redis Pub/Sub 발행 |
| **프론트엔드** | hitl 이벤트 스키마, 백엔드 API 경로 | 승인/거절 UI, API 호출 연동 |
| **테스트/QA** | API 스펙, Redis 테스트 방법 | E2E/HITL 테스트 스크립트 |
| **Aura-Platform** | - | 문서화 완성, 테스트 스크립트 (선택) |
