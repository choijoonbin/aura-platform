# Aura-Platform ↔ DWP Backend 연동 상태

> **작성일**: 2026-01-16  
> **버전**: v1.0  
> **상태**: 구현 완료

---

## ✅ 구현 완료 사항

### 1. SSE 스트리밍 엔드포인트

**엔드포인트**: `GET /aura/test/stream`

**구현 내용**:
- ✅ 백엔드 요구 형식 준수: `event: {type}\ndata: {json}`
- ✅ 5가지 이벤트 타입 지원:
  - `thought` - 사고 과정
  - `plan_step` - 실행 계획 단계
  - `tool_execution` - 도구 실행
  - `hitl` - 승인 요청 (새로 추가)
  - `content` - 최종 결과
- ✅ Gateway 라우팅 지원: `/api/aura/test/stream` → `/aura/test/stream`

**파일**: `api/routes/aura_backend.py`

---

### 2. JWT 인증

**구현 내용**:
- ✅ HS256 알고리즘 검증
- ✅ Unix timestamp (초 단위 정수) 사용 (`exp`, `iat`)
- ✅ `Authorization: Bearer {token}` 헤더 처리
- ✅ `X-Tenant-ID` 헤더 검증
- ✅ `X-DWP-Source`, `X-DWP-Caller-Type` 헤더 지원

**파일**: `core/security/auth.py`, `api/middleware.py`

---

### 3. HITL 통신

**구현 내용**:
- ✅ `hitl` 이벤트 타입 추가
- ✅ Redis Pub/Sub 구독 (`hitl:channel:{sessionId}`)
- ✅ 승인 요청 저장 (`hitl:request:{requestId}`)
- ✅ 세션 정보 저장 (`hitl:session:{sessionId}`)
- ✅ 승인/거절 신호 수신 및 처리
- ✅ 타임아웃 처리 (기본 300초)

**파일**: 
- `core/memory/hitl_manager.py` - HITL Manager 구현
- `api/schemas/hitl_events.py` - HITL 이벤트 스키마
- `api/routes/aura_backend.py` - HITL 통신 로직

---

### 4. HITL API 엔드포인트

**구현된 엔드포인트**:
- ✅ `GET /aura/hitl/requests/{request_id}` - 승인 요청 조회
- ✅ `GET /aura/hitl/signals/{session_id}` - 승인 신호 조회

**파일**: `api/routes/aura_backend.py`

---

## 📋 백엔드 요구사항 대응 현황

| 요구사항 | 상태 | 구현 위치 |
|---------|------|----------|
| SSE 스트리밍 (`/aura/test/stream`) | ✅ 완료 | `api/routes/aura_backend.py` |
| SSE 이벤트 형식 (`event: {type}\ndata: {...}`) | ✅ 완료 | `format_sse_event()` 함수 |
| 5가지 이벤트 타입 | ✅ 완료 | thought, plan_step, tool_execution, hitl, content |
| JWT 인증 (HS256, Unix timestamp) | ✅ 완료 | `core/security/auth.py` |
| X-Tenant-ID 헤더 검증 | ✅ 완료 | `api/middleware.py` |
| HITL Redis Pub/Sub 구독 | ✅ 완료 | `core/memory/hitl_manager.py` |
| HITL 승인 요청 저장 | ✅ 완료 | `HITLManager.save_approval_request()` |
| HITL 신호 대기 | ✅ 완료 | `HITLManager.wait_for_approval_signal()` |
| HITL API 엔드포인트 | ✅ 완료 | `/aura/hitl/requests/{id}`, `/aura/hitl/signals/{id}` |

---

## 🔧 수정 사항

### 1. SSE 이벤트 형식 변경

**변경 전**:
```
data: {"type": "thought", "content": "..."}
```

**변경 후** (백엔드 요구사항):
```
event: thought
data: {"type": "thought", "data": {"content": "..."}}
```

**구현**: `api/routes/aura_backend.py`의 `format_sse_event()` 함수

---

### 2. HITL 이벤트 타입 추가

**새로 추가된 이벤트**:
```json
{
  "type": "hitl",
  "data": {
    "requestId": "req-12345",
    "actionType": "send_email",
    "message": "이메일을 발송하시겠습니까?",
    "context": {
      "to": "user@example.com",
      "subject": "안내 메일"
    },
    "requiresApproval": true
  }
}
```

**구현**: `api/schemas/hitl_events.py`

---

### 3. Redis Pub/Sub 구독 구현

**구현 내용**:
- `HITLManager.wait_for_approval_signal()` 메서드
- 채널: `hitl:channel:{sessionId}`
- 타임아웃: 300초 (5분)
- 신호 형식: JSON

**예시**:
```python
signal = await hitl_manager.wait_for_approval_signal(session_id, timeout=300)
if signal["type"] == "approval":
    # 승인 처리
    continue_execution()
elif signal["type"] == "rejection":
    # 거절 처리
    handle_rejection()
```

---

## 📡 API 엔드포인트

### 1. SSE 스트리밍

**경로**: `GET /aura/test/stream?message={message}`

**Gateway 경로**: `GET /api/aura/test/stream?message={message}`

**헤더**:
```
Authorization: Bearer {JWT_TOKEN}
X-Tenant-ID: {tenant_id}
X-DWP-Source: FRONTEND (선택)
X-DWP-Caller-Type: AGENT (선택)
```

**응답**: SSE 스트림 (`text/event-stream`)

---

### 2. 승인 요청 조회

**경로**: `GET /aura/hitl/requests/{request_id}`

**Gateway 경로**: `GET /api/aura/hitl/requests/{request_id}`

**응답 형식** (백엔드 ApiResponse):
```json
{
  "status": "SUCCESS",
  "message": "Approval request retrieved",
  "data": "{\"requestId\":\"req-12345\",\"sessionId\":\"session-abc\",...}",
  "success": true,
  "timestamp": "2026-01-16T12:00:00"
}
```

---

### 3. 승인 신호 조회

**경로**: `GET /aura/hitl/signals/{session_id}`

**Gateway 경로**: `GET /api/aura/hitl/signals/{session_id}`

**응답 형식** (백엔드 ApiResponse):
```json
{
  "status": "SUCCESS",
  "message": "Signal retrieved",
  "data": "{\"type\":\"approval\",\"requestId\":\"req-12345\",\"status\":\"approved\"}",
  "success": true,
  "timestamp": "2026-01-16T12:00:00"
}
```

---

## 🔄 HITL 프로세스

### 1. 승인 요청 생성

```
에이전트 실행 중
  ↓
중요 도구 실행 필요 (git_merge, github_create_pr 등)
  ↓
HITL 이벤트 발행 (hitl 이벤트)
  ↓
승인 요청 Redis 저장 (hitl:request:{requestId})
  ↓
세션 정보 저장 (hitl:session:{sessionId})
  ↓
실행 중지
```

### 2. 승인 신호 대기

```
Redis Pub/Sub 구독 시작 (hitl:channel:{sessionId})
  ↓
타임아웃 설정 (300초)
  ↓
신호 수신 대기
  ↓
승인/거절 신호 수신
  ↓
실행 재개 또는 중단
```

### 3. 승인 처리

```
Frontend → Gateway → Main Service
  ↓
POST /api/aura/hitl/approve/{requestId}
  ↓
Main Service → Redis Pub/Sub 발행
  ↓
Aura-Platform 신호 수신
  ↓
실행 재개
```

---

## 🧪 테스트 방법

### 1. SSE 스트리밍 테스트

```bash
# JWT 토큰 생성 (dwp-backend에서)
TOKEN=$(cd /path/to/dwp-backend/dwp-auth-server && python3 test_jwt_for_aura.py --token-only)

# SSE 스트리밍 요청
curl -N -H "Accept: text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1" \
  -H "X-DWP-Source: FRONTEND" \
  "http://localhost:8080/api/aura/test/stream?message=Analyze%20this%20PR"
```

### 2. HITL 승인 테스트

```bash
# 승인 요청 조회
curl http://localhost:8080/api/aura/hitl/requests/{requestId} \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1"

# 승인 신호 조회
curl http://localhost:8080/api/aura/hitl/signals/{sessionId} \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1"
```

---

## 📝 백엔드에 전달할 내용

### 1. 현재 구현 상태

✅ **완료된 항목**:
- SSE 스트리밍 엔드포인트 (`/aura/test/stream`)
- JWT 인증 (HS256, Unix timestamp)
- HITL Redis Pub/Sub 구독
- HITL 승인 요청 저장/조회
- HITL 신호 대기/조회

### 2. 추가 구현 필요 (백엔드 측)

⚠️ **백엔드에서 구현 필요**:
- `POST /api/aura/hitl/approve/{requestId}` - 승인 처리
- `POST /api/aura/hitl/reject/{requestId}` - 거절 처리
- Redis Pub/Sub 발행 (`hitl:channel:{sessionId}`)

### 3. 주의사항

1. **포트 충돌**: ✅ 해결 완료
   - Aura-Platform: 포트 9000으로 변경 완료
   - Auth Server: 포트 8001 (또는 다른 포트) 사용

2. **Redis 연결**: dwp-backend의 Docker Compose Redis 사용 가능
   - 호스트: `localhost:6379`
   - 별도 설치 불필요

3. **SSE 타임아웃**: Gateway 타임아웃 300초 설정 확인 필요

---

## 🔗 관련 문서

- [AURA_PLATFORM_INTEGRATION_GUIDE.md](../dwp-backend/docs/AURA_PLATFORM_INTEGRATION_GUIDE.md) - 백엔드 연동 가이드
- [AURA_PLATFORM_QUICK_REFERENCE.md](../dwp-backend/docs/AURA_PLATFORM_QUICK_REFERENCE.md) - 빠른 참조
- [JWT_COMPATIBILITY.md](JWT_COMPATIBILITY.md) - JWT 호환성 가이드

---

**✅ 백엔드 연동 준비 완료!**
