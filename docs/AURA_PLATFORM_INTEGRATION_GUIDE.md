# Aura-Platform 백엔드 연동 가이드

> **대상**: Aura-Platform (Python/FastAPI) 개발팀  
> **목적**: DWP Backend와의 통합을 위한 필수 정보 제공  
> **버전**: v1.0  
> **작성일**: 2024-01

---

## 📋 목차

1. [개요](#개요)
2. [네트워크 및 라우팅](#네트워크-및-라우팅)
3. [인증 및 보안](#인증-및-보안)
4. [SSE 스트리밍 요구사항](#sse-스트리밍-요구사항)
5. [HITL (Human-In-The-Loop) 통신](#hitl-human-in-the-loop-통신)
6. [데이터 형식 및 스키마](#데이터-형식-및-스키마)
7. [에러 처리](#에러-처리)
8. [Redis Pub/Sub 통신](#redis-pubsub-통신)
9. [통합 체크리스트](#통합-체크리스트)

---

## 개요

DWP Backend는 Spring Boot 3.x 기반의 MSA 아키텍처로 구성되어 있으며, Aura-Platform은 AI 에이전트 서비스로 통합됩니다.

### 아키텍처 다이어그램

```
Frontend (Aura UI)
    │
    │ HTTP/SSE
    ▼
Gateway (포트 8080)
    │
    ├─ /api/aura/** → Aura-Platform (포트 8000)
    │
    └─ /api/main/** → Main Service (포트 8081)
                        │
                        └─ HITL Manager (Redis)
```

### 핵심 통신 경로

1. **SSE 스트리밍**: `Frontend → Gateway → Aura-Platform`
2. **HITL 승인**: `Frontend → Gateway → Main Service → Redis → Aura-Platform`
3. **이벤트 발행**: `Mail/Approval Service → Redis Pub/Sub → Aura-Platform`

---

## 네트워크 및 라우팅

### Gateway 라우팅 규칙

**Aura-Platform 라우팅:**
- **경로**: `/api/aura/**`
- **대상**: `http://localhost:8000` (로컬 개발) / `http://aura-platform:8000` (운영)
- **변환**: `StripPrefix=1` 필터 적용
  - 예: `/api/aura/test/stream` → `http://localhost:8000/aura/test/stream`

**HITL API 라우팅:**
- **경로**: `/api/aura/hitl/**`
- **대상**: `dwp-main-service` (포트 8081)
- **변환**: `StripPrefix=1` 필터 적용
  - 예: `/api/aura/hitl/approve/{requestId}` → `http://localhost:8081/aura/hitl/approve/{requestId}`

### 포트 정보

| 서비스 | 포트 | 용도 |
|--------|------|------|
| Gateway | 8080 | 모든 외부 요청 진입점 |
| Aura-Platform | 8000 | AI 에이전트 서비스 |
| Main Service | 8081 | HITL 관리, AgentTask 관리 |
| Auth Server | 8000 | JWT 인증 (포트 충돌 주의) |
| Redis | 6379 | 세션 관리, Pub/Sub |

**⚠️ 주의**: Auth Server와 Aura-Platform이 동일한 포트(8000)를 사용하므로, 동시 실행 시 포트 분리 필요

---

## 인증 및 보안

### JWT 토큰 검증

**알고리즘**: HS256  
**Secret Key**: 환경 변수 `JWT_SECRET`에서 로드 (Python-Java 공유)

**JWT Payload 구조:**
```json
{
  "sub": "backend_user_001",        // 사용자 ID
  "tenant_id": "tenant1",            // 테넌트 ID (필수)
  "email": "user@dwp.com",           // 사용자 이메일
  "role": "user",                    // 사용자 역할
  "exp": 1706156400,                 // 만료 시간 (Unix timestamp, 초 단위)
  "iat": 1706152860                  // 발행 시간 (Unix timestamp, 초 단위)
}
```

**⚠️ 중요**: `exp`와 `iat`는 **Unix timestamp (초 단위 정수)**로 설정해야 합니다.

**Python 예시 (jose 라이브러리):**
```python
from datetime import datetime, timedelta, timezone
from jose import jwt

SECRET_KEY = os.getenv("JWT_SECRET", "your_shared_secret_key_must_be_at_least_256_bits_long_for_HS256")
ALGORITHM = "HS256"

now = datetime.now(timezone.utc)
expiration = now + timedelta(hours=1)

payload = {
    "sub": "backend_user_001",
    "tenant_id": "tenant1",
    "email": "user@dwp.com",
    "role": "user",
    "exp": int(expiration.timestamp()),  # ✅ Unix timestamp로 변환
    "iat": int(now.timestamp()),         # ✅ Unix timestamp로 변환
}

token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
```

### 필수 HTTP 헤더

모든 요청에 다음 헤더를 포함해야 합니다:

| 헤더명 | 설명 | 예시 값 | 필수 여부 |
|--------|------|---------|----------|
| `Authorization` | JWT 토큰 | `Bearer eyJhbGc...` | ✅ 필수 |
| `X-Tenant-ID` | 테넌트 식별자 | `tenant1` | ✅ 필수 |
| `X-DWP-Source` | 요청 출처 | `AURA`, `FRONTEND`, `INTERNAL`, `BATCH` | 선택 |
| `X-DWP-Caller-Type` | 호출자 타입 | `AGENT` (에이전트 호출 시) | 선택 |
| `X-User-ID` | 사용자 식별자 | `user123` | HITL 작업 시 필수 |

**Gateway 헤더 전파:**
- Gateway는 모든 헤더를 자동으로 다운스트림 서비스로 전파합니다.
- `HeaderPropagationFilter`가 전파 여부를 로깅합니다.

---

## SSE 스트리밍 요구사항

### 엔드포인트

**SSE 스트리밍 엔드포인트:**
- **경로**: `/api/aura/test/stream` (Gateway를 통한 접근)
- **실제 경로**: `/aura/test/stream` (Aura-Platform 내부)
- **메서드**: `GET`
- **Content-Type**: `text/event-stream`

### 응답 헤더

**필수 헤더:**
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

### 이벤트 형식

프론트엔드 Aura AI UI v1.0 명세에 맞춰 다음 이벤트 타입을 전송해야 합니다:

#### 1. `thought` 이벤트
```json
{
  "type": "thought",
  "data": {
    "content": "사용자의 요청을 분석하고 있습니다...",
    "timestamp": 1706152860
  }
}
```

#### 2. `plan_step` 이벤트
```json
{
  "type": "plan_step",
  "data": {
    "id": "step-1",
    "title": "데이터 분석",
    "description": "이메일 데이터를 분석합니다",
    "status": "in_progress",
    "confidence": 0.85
  }
}
```

#### 3. `tool_execution` 이벤트
```json
{
  "type": "tool_execution",
  "data": {
    "tool": "send_email",
    "parameters": {
      "to": "user@example.com",
      "subject": "안내 메일"
    },
    "status": "executing",
    "result": null
  }
}
```

#### 4. `hitl` 이벤트 (승인 요청)
```json
{
  "type": "hitl",
  "data": {
    "requestId": "req-12345",
    "actionType": "send_email",
    "message": "이메일을 발송하시겠습니까?",
    "context": {
      "to": "user@example.com",
      "subject": "안내 메일",
      "body": "..."
    },
    "requiresApproval": true
  }
}
```

**⚠️ 중요**: `hitl` 이벤트 전송 후, **실행을 멈추고 Redis에서 승인 신호를 대기**해야 합니다.

#### 5. `content` 이벤트
```json
{
  "type": "content",
  "data": {
    "content": "작업이 완료되었습니다.",
    "format": "markdown"
  }
}
```

### SSE 이벤트 전송 형식

**Server-Sent Events 표준 형식:**
```
event: thought
data: {"type":"thought","data":{"content":"분석 중...","timestamp":1706152860}}

event: plan_step
data: {"type":"plan_step","data":{"id":"step-1","title":"데이터 분석","status":"in_progress"}}

event: hitl
data: {"type":"hitl","data":{"requestId":"req-12345","actionType":"send_email","requiresApproval":true}}
```

### 타임아웃 설정

- **Gateway Response Timeout**: 300초 (5분)
- **Gateway Connect Timeout**: 10초
- **커넥션 풀**: max-connections: 500

**권장사항**: Aura-Platform도 충분한 타임아웃을 설정하여 장기 실행 작업을 지원하세요.

---

## HITL (Human-In-The-Loop) 통신

### HITL 프로세스

1. **승인 요청 생성** (Aura-Platform → Main Service)
   - `HitlManager.saveApprovalRequest()` 호출
   - Redis에 승인 요청 저장 (`hitl:request:{requestId}`)
   - 세션 정보 저장 (`hitl:session:{sessionId}`)

2. **승인 요청 조회** (Frontend → Main Service)
   - `GET /api/aura/hitl/requests/{requestId}`

3. **승인/거절 처리** (Frontend → Main Service)
   - `POST /api/aura/hitl/approve/{requestId}`
   - `POST /api/aura/hitl/reject/{requestId}`

4. **신호 수신** (Aura-Platform ← Redis Pub/Sub)
   - 채널: `hitl:channel:{sessionId}`
   - 신호 형식: JSON (아래 참조)

### Redis 키 패턴

| 키 패턴 | 설명 | TTL |
|---------|------|-----|
| `hitl:request:{requestId}` | 승인 요청 데이터 | 30분 |
| `hitl:session:{sessionId}` | 세션 정보 | 60분 |
| `hitl:signal:{sessionId}` | 승인/거절 신호 | 5분 |

### 승인 신호 형식

**승인 신호:**
```json
{
  "type": "approval",
  "requestId": "req-12345",
  "status": "approved",
  "timestamp": 1706152860
}
```

**거절 신호:**
```json
{
  "type": "rejection",
  "requestId": "req-12345",
  "status": "rejected",
  "reason": "사용자 거절",
  "timestamp": 1706152860
}
```

### Redis Pub/Sub 채널

**채널명**: `hitl:channel:{sessionId}`

**구독 예시 (Python):**
```python
import redis
import json

redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
pubsub = redis_client.pubsub()
pubsub.subscribe(f'hitl:channel:{session_id}')

for message in pubsub.listen():
    if message['type'] == 'message':
        signal = json.loads(message['data'])
        if signal['type'] == 'approval':
            # 승인 처리
            continue_execution()
        elif signal['type'] == 'rejection':
            # 거절 처리
            handle_rejection(signal['reason'])
```

### HITL API 엔드포인트

#### 1. 승인 요청 조회
```http
GET /api/aura/hitl/requests/{requestId}
Headers:
  Authorization: Bearer {JWT_TOKEN}
  X-Tenant-ID: {tenant_id}
```

**응답:**
```json
{
  "status": "SUCCESS",
  "message": "Approval request retrieved",
  "data": "{\"requestId\":\"req-12345\",\"sessionId\":\"session-abc\",\"actionType\":\"send_email\",\"status\":\"pending\",...}",
  "success": true,
  "timestamp": "2024-01-16T12:00:00"
}
```

#### 2. 승인 처리
```http
POST /api/aura/hitl/approve/{requestId}
Headers:
  Authorization: Bearer {JWT_TOKEN}
  X-Tenant-ID: {tenant_id}
  X-User-ID: {user_id}
Content-Type: application/json

Body:
{
  "userId": "user123"
}
```

**응답:**
```json
{
  "status": "SUCCESS",
  "message": "Request approved successfully",
  "data": {
    "requestId": "req-12345",
    "sessionId": "session-abc",
    "status": "approved"
  },
  "success": true,
  "timestamp": "2024-01-16T12:00:00"
}
```

#### 3. 거절 처리
```http
POST /api/aura/hitl/reject/{requestId}
Headers:
  Authorization: Bearer {JWT_TOKEN}
  X-Tenant-ID: {tenant_id}
  X-User-ID: {user_id}
Content-Type: application/json

Body:
{
  "userId": "user123",
  "reason": "사용자 거절"  // 선택
}
```

**응답:**
```json
{
  "status": "SUCCESS",
  "message": "Request rejected",
  "data": {
    "requestId": "req-12345",
    "sessionId": "session-abc",
    "status": "rejected",
    "reason": "사용자 거절"
  },
  "success": true,
  "timestamp": "2024-01-16T12:00:00"
}
```

#### 4. 신호 조회 (에이전트용)
```http
GET /api/aura/hitl/signals/{sessionId}
Headers:
  Authorization: Bearer {JWT_TOKEN}
  X-Tenant-ID: {tenant_id}
```

**응답:**
```json
{
  "status": "SUCCESS",
  "message": "Signal retrieved",
  "data": "{\"type\":\"approval\",\"requestId\":\"req-12345\",\"status\":\"approved\",\"timestamp\":1706152860}",
  "success": true,
  "timestamp": "2024-01-16T12:00:00"
}
```

---

## 데이터 형식 및 스키마

### ApiResponse<T> 형식

모든 API 응답은 다음 형식을 따릅니다:

```json
{
  "status": "SUCCESS" | "ERROR",
  "message": "요청이 성공적으로 처리되었습니다.",
  "data": { /* 실제 데이터 */ },
  "errorCode": "E1000",  // 에러 시에만 존재
  "success": true | false,
  "timestamp": "2024-01-16T12:00:00",
  "agentMetadata": {  // 선택 (에이전트 전용)
    "traceId": "trace-123",
    "steps": [ /* AgentStep 배열 */ ],
    "confidence": 0.85,
    "additionalData": { /* 추가 메타데이터 */ }
  }
}
```

### AgentStep 스키마

AI 에이전트의 실행 계획 단계를 나타냅니다:

```json
{
  "id": "step-1",
  "title": "데이터 분석",
  "description": "이메일 데이터를 분석합니다",
  "status": "pending" | "in_progress" | "completed" | "failed",
  "confidence": 0.85,  // 0.0 ~ 1.0
  "result": { /* 실행 결과 */ },  // 선택
  "startedAt": 1706152860,  // Unix timestamp (초)
  "completedAt": 1706153000  // Unix timestamp (초)
}
```

### AgentTask 스키마

AI 장기 실행 작업의 상태를 나타냅니다:

```json
{
  "taskId": "task-12345",
  "userId": "user123",
  "tenantId": "tenant1",
  "taskType": "data_analysis",
  "status": "REQUESTED" | "IN_PROGRESS" | "COMPLETED" | "FAILED",
  "progress": 50,  // 0 ~ 100
  "description": "작업 설명",
  "planSteps": "[{\"id\":\"step-1\",\"title\":\"분석\",\"status\":\"completed\"},...]",  // JSON 문자열
  "resultData": "{ /* 결과 데이터 */ }",  // JSON 문자열
  "errorMessage": "에러 메시지",  // 실패 시
  "createdAt": "2024-01-16T12:00:00",
  "updatedAt": "2024-01-16T12:05:00"
}
```

---

## 에러 처리

### 에러 응답 형식

```json
{
  "status": "ERROR",
  "message": "인증이 필요합니다.",
  "errorCode": "E2000",
  "success": false,
  "timestamp": "2024-01-16T12:00:00"
}
```

### 주요 에러 코드

| 에러 코드 | HTTP 상태 | 설명 |
|-----------|-----------|------|
| `E2000` | 401 | 인증이 필요합니다 |
| `E2001` | 403 | 권한이 없습니다 |
| `E2002` | 401 | 토큰이 만료되었습니다 |
| `E2003` | 401 | 유효하지 않은 토큰입니다 |
| `E1004` | 404 | 요청한 리소스를 찾을 수 없습니다 |
| `E1000` | 500 | 내부 서버 오류가 발생했습니다 |

---

## Redis Pub/Sub 통신

### 이벤트 채널

| 채널명 | 설명 | 발행자 | 구독자 |
|--------|------|--------|--------|
| `dwp:events:all` | 모든 이벤트 | 모든 서비스 | Aura-Platform |
| `dwp:events:mail` | 메일 서비스 이벤트 | Mail Service | Aura-Platform |
| `dwp:events:approval` | 승인 서비스 이벤트 | Approval Service | Aura-Platform |
| `hitl:channel:{sessionId}` | HITL 신호 | Main Service | Aura-Platform |

### 이벤트 메시지 형식

**DomainEvent 기본 구조:**
```json
{
  "eventId": "event-12345",
  "timestamp": "2024-01-16T12:00:00",
  "userId": "user123",
  "tenantId": "tenant1",
  "eventType": "MailSentEvent",
  /* 이벤트별 추가 필드 */
}
```

**예시: 메일 발송 이벤트**
```json
{
  "eventId": "event-12345",
  "timestamp": "2024-01-16T12:00:00",
  "userId": "user123",
  "tenantId": "tenant1",
  "eventType": "MailSentEvent",
  "mailId": "mail-001",
  "recipient": "user@example.com",
  "subject": "안내 메일"
}
```

### Redis 연결 정보

**로컬 개발:**
- Host: `localhost`
- Port: `6379`
- Password: 없음 (기본)

**운영 환경:**
- Host: 환경 변수 `REDIS_HOST`
- Port: 환경 변수 `REDIS_PORT` (기본: 6379)
- Password: 환경 변수 `REDIS_PASSWORD`

---

## 통합 체크리스트

### 필수 구현 사항

- [ ] **SSE 스트리밍 엔드포인트**
  - [ ] `/aura/test/stream` 엔드포인트 구현
  - [ ] `Content-Type: text/event-stream` 헤더 설정
  - [ ] `Cache-Control: no-cache` 헤더 설정
  - [ ] `thought`, `plan_step`, `tool_execution`, `hitl`, `content` 이벤트 전송

- [ ] **JWT 인증**
  - [ ] JWT 토큰 검증 로직 구현 (HS256)
  - [ ] `Authorization` 헤더에서 토큰 추출
  - [ ] `X-Tenant-ID` 헤더 확인
  - [ ] 토큰 만료 처리

- [ ] **HITL 통신**
  - [ ] `hitl` 이벤트 전송 시 실행 중지
  - [ ] Redis Pub/Sub 구독 (`hitl:channel:{sessionId}`)
  - [ ] 승인/거절 신호 수신 및 처리
  - [ ] 신호 수신 후 실행 재개 또는 중단

- [ ] **헤더 처리**
  - [ ] `X-Tenant-ID` 헤더 읽기
  - [ ] `X-DWP-Source` 헤더 읽기 (로깅용)
  - [ ] `X-DWP-Caller-Type` 헤더 읽기 (로깅용)

- [ ] **에러 처리**
  - [ ] 표준 에러 응답 형식 준수
  - [ ] 적절한 HTTP 상태 코드 반환

### 권장 구현 사항

- [ ] **AgentTask 연동**
  - [ ] 작업 시작 시 `AgentTask` 생성 (Main Service API 호출)
  - [ ] 진척도 업데이트 (Main Service API 호출)
  - [ ] `planSteps` 업데이트 (Main Service API 호출)
  - [ ] 작업 완료/실패 시 상태 업데이트

- [ ] **이벤트 구독**
  - [ ] `dwp:events:all` 채널 구독
  - [ ] 벡터 DB 업데이트 트리거

- [ ] **로깅**
  - [ ] 요청 추적 ID 로깅
  - [ ] 에러 상세 로깅

---

## 테스트 가이드

### 1. SSE 스트리밍 테스트

```bash
# JWT 토큰 생성
TOKEN=$(cd dwp-auth-server && python3 test_jwt_for_aura.py --token-only)

# SSE 스트리밍 요청
curl -N -H "Accept: text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1" \
  http://localhost:8080/api/aura/test/stream
```

### 2. HITL 승인 테스트

```bash
# 승인 요청 조회
curl http://localhost:8080/api/aura/hitl/requests/{requestId} \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1"

# 승인 처리
curl -X POST http://localhost:8080/api/aura/hitl/approve/{requestId} \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1" \
  -H "X-User-ID: user123" \
  -H "Content-Type: application/json" \
  -d '{"userId": "user123"}'
```

### 3. Redis Pub/Sub 테스트

```python
import redis
import json

redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
pubsub = redis_client.pubsub()
pubsub.subscribe('hitl:channel:test-session')

print("Waiting for HITL signal...")
for message in pubsub.listen():
    if message['type'] == 'message':
        signal = json.loads(message['data'])
        print(f"Received signal: {signal}")
        break
```

---

## 환경 변수

### 필수 환경 변수

```bash
# JWT 시크릿 키 (Python-Java 공유)
JWT_SECRET=your_shared_secret_key_must_be_at_least_256_bits_long_for_HS256

# Redis 연결
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=  # 선택
```

### 선택 환경 변수

```bash
# Aura-Platform URI (Gateway에서 사용)
AURA_PLATFORM_URI=http://localhost:8000
```

---

## 참고 문서

- [DWP Backend README](../README.md) - 전체 프로젝트 개요
- [Aura AI UI 통합 가이드](./AURA_UI_INTEGRATION.md) - 상세 통합 가이드
- [JWT 호환성 가이드](./JWT_COMPATIBILITY_GUIDE.md) - Python-Java JWT 통합
- [AI 에이전트 인프라](./AI_AGENT_INFRASTRUCTURE.md) - 인프라 아키텍처

---

## 문의 및 지원

통합 과정에서 문제가 발생하거나 추가 정보가 필요한 경우, DWP Backend 개발팀에 문의하세요.

**연락처**: DWP Backend 개발팀

---

**문서 버전**: v1.0  
**최종 업데이트**: 2024-01-16
