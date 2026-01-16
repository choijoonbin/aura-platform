# Aura-Platform → DWP Backend 전달 문서

> **전달 대상**: DWP Backend 개발팀  
> **전달 일자**: 2026-01-16  
> **Aura-Platform 버전**: v0.3.1

---

## 📦 전달 내용 요약

Aura-Platform에서 dwp-backend와의 연동을 위해 구현 완료된 사항과 추가 작업이 필요한 내용을 전달합니다.

---

## ✅ 구현 완료 사항

### 1. SSE 스트리밍 엔드포인트

**엔드포인트**: `GET /aura/test/stream?message={message}`

**Gateway 경로**: `GET /api/aura/test/stream?message={message}`

**구현 내용**:
- ✅ 백엔드 요구 형식 준수: `event: {type}\ndata: {json}`
- ✅ 5가지 이벤트 타입 지원:
  - `thought` - 사고 과정
  - `plan_step` - 실행 계획 단계
  - `tool_execution` - 도구 실행
  - `hitl` - 승인 요청
  - `content` - 최종 결과
- ✅ JWT 인증 통합
- ✅ X-Tenant-ID 헤더 검증
- ✅ X-DWP-Source, X-DWP-Caller-Type 헤더 지원

**파일**: `api/routes/aura_backend.py`

---

### 2. JWT 인증

**구현 내용**:
- ✅ HS256 알고리즘 검증
- ✅ Unix timestamp (초 단위 정수) 사용 (`exp`, `iat`)
- ✅ `Authorization: Bearer {token}` 헤더 처리
- ✅ `X-Tenant-ID` 헤더 검증
- ✅ Python-Java 호환성 확인 완료

**파일**: `core/security/auth.py`, `api/middleware.py`

**테스트**: `scripts/test_jwt_compatibility.py` - 모든 테스트 통과 ✅

---

### 3. HITL 통신

**구현 내용**:
- ✅ `hitl` 이벤트 타입 추가
- ✅ Redis Pub/Sub 구독 (`hitl:channel:{sessionId}`)
- ✅ 승인 요청 저장 (`hitl:request:{requestId}`)
- ✅ 세션 정보 저장 (`hitl:session:{sessionId}`)
- ✅ 승인 신호 대기 및 처리
- ✅ 타임아웃 처리 (기본 300초)

**파일**: 
- `core/memory/hitl_manager.py` - HITL Manager 구현
- `api/schemas/hitl_events.py` - HITL 이벤트 스키마

---

### 4. HITL API 엔드포인트

**구현된 엔드포인트**:
- ✅ `GET /aura/hitl/requests/{request_id}` - 승인 요청 조회
- ✅ `GET /aura/hitl/signals/{session_id}` - 승인 신호 조회

**응답 형식**: 백엔드 `ApiResponse<T>` 형식 준수

**파일**: `api/routes/aura_backend.py`

---

## 🔧 백엔드에서 구현 필요 사항

### 1. HITL 승인/거절 API

**필요한 엔드포인트**:

#### `POST /api/aura/hitl/approve/{requestId}`

**요청**:
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

**응답**:
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
  "timestamp": "2026-01-16T12:00:00"
}
```

**구현 요구사항**:
1. 승인 요청 조회 (`hitl:request:{requestId}`)
2. 승인 신호 생성:
   ```json
   {
     "type": "approval",
     "requestId": "req-12345",
     "status": "approved",
     "timestamp": 1706152860
   }
   ```
3. Redis Pub/Sub 발행 (`hitl:channel:{sessionId}`)
4. 신호 저장 (`hitl:signal:{sessionId}`) - TTL: 5분

---

#### `POST /api/aura/hitl/reject/{requestId}`

**요청**:
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

**응답**:
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
  "timestamp": "2026-01-16T12:00:00"
}
```

**구현 요구사항**:
1. 승인 요청 조회 (`hitl:request:{requestId}`)
2. 거절 신호 생성:
   ```json
   {
     "type": "rejection",
     "requestId": "req-12345",
     "status": "rejected",
     "reason": "사용자 거절",
     "timestamp": 1706152860
   }
   ```
3. Redis Pub/Sub 발행 (`hitl:channel:{sessionId}`)
4. 신호 저장 (`hitl:signal:{sessionId}`) - TTL: 5분

---

### 2. Redis Pub/Sub 발행 코드 예시

**Java (Spring Boot) 예시**:
```java
@Service
public class HITLService {
    
    @Autowired
    private RedisTemplate<String, String> redisTemplate;
    
    public void publishApprovalSignal(String sessionId, String requestId) {
        Map<String, Object> signal = new HashMap<>();
        signal.put("type", "approval");
        signal.put("requestId", requestId);
        signal.put("status", "approved");
        signal.put("timestamp", System.currentTimeMillis() / 1000);
        
        String channel = "hitl:channel:" + sessionId;
        String signalJson = objectMapper.writeValueAsString(signal);
        
        // Redis Pub/Sub 발행
        redisTemplate.convertAndSend(channel, signalJson);
        
        // 신호 저장 (TTL: 5분)
        String signalKey = "hitl:signal:" + sessionId;
        redisTemplate.opsForValue().set(signalKey, signalJson, 5, TimeUnit.MINUTES);
    }
    
    public void publishRejectionSignal(String sessionId, String requestId, String reason) {
        Map<String, Object> signal = new HashMap<>();
        signal.put("type", "rejection");
        signal.put("requestId", requestId);
        signal.put("status", "rejected");
        signal.put("reason", reason);
        signal.put("timestamp", System.currentTimeMillis() / 1000);
        
        String channel = "hitl:channel:" + sessionId;
        String signalJson = objectMapper.writeValueAsString(signal);
        
        // Redis Pub/Sub 발행
        redisTemplate.convertAndSend(channel, signalJson);
        
        // 신호 저장 (TTL: 5분)
        String signalKey = "hitl:signal:" + sessionId;
        redisTemplate.opsForValue().set(signalKey, signalJson, 5, TimeUnit.MINUTES);
    }
}
```

---

## 📋 통합 체크리스트

### Aura-Platform (완료 ✅)

- [x] SSE 스트리밍 엔드포인트 (`/aura/test/stream`)
- [x] SSE 이벤트 형식 (`event: {type}\ndata: {json}`)
- [x] 5가지 이벤트 타입 (thought, plan_step, tool_execution, hitl, content)
- [x] JWT 인증 (HS256, Unix timestamp)
- [x] X-Tenant-ID 헤더 검증
- [x] HITL Redis Pub/Sub 구독
- [x] HITL 승인 요청 저장
- [x] HITL 신호 대기
- [x] HITL API 엔드포인트 (조회)

### DWP Backend (구현 필요 ⚠️)

- [ ] `POST /api/aura/hitl/approve/{requestId}` - 승인 처리
- [ ] `POST /api/aura/hitl/reject/{requestId}` - 거절 처리
- [ ] Redis Pub/Sub 발행 (`hitl:channel:{sessionId}`)
- [ ] 신호 저장 (`hitl:signal:{sessionId}`)

---

## 🔍 테스트 방법

### 1. SSE 스트리밍 테스트

```bash
# JWT 토큰 생성
TOKEN=$(cd /path/to/dwp-backend/dwp-auth-server && python3 test_jwt_for_aura.py --token-only)

# SSE 스트리밍 요청 (Gateway 경유)
curl -N -H "Accept: text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1" \
  -H "X-DWP-Source: FRONTEND" \
  "http://localhost:8080/api/aura/test/stream?message=Test%20message"
```

**예상 출력**:
```
event: start
data: {"type":"start","message":"Agent started","timestamp":1706152860}

event: thought
data: {"type":"thought","data":{"thoughtType":"analysis","content":"사용자 요청 분석 중..."}}

event: plan_step
data: {"type":"plan_step","data":{"stepId":"uuid-1","description":"요청 처리","status":"pending","confidence":0.8}}

event: hitl
data: {"type":"hitl","data":{"requestId":"req-12345","actionType":"git_merge","requiresApproval":true}}

... (승인 대기 중) ...

event: content
data: {"type":"content","data":{"content":"작업 완료","chunk":false}}

event: end
data: {"type":"end","message":"Agent finished","timestamp":1706153000}
```

---

### 2. HITL 승인 테스트

```bash
# 승인 요청 조회
curl http://localhost:8080/api/aura/hitl/requests/req-12345 \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1"

# 승인 처리 (백엔드에서 구현 필요)
curl -X POST http://localhost:8080/api/aura/hitl/approve/req-12345 \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1" \
  -H "X-User-ID: user123" \
  -H "Content-Type: application/json" \
  -d '{"userId": "user123"}'
```

---

## ⚠️ 주의사항

### 1. 포트 충돌

**문제**: Auth Server와 Aura-Platform이 모두 포트 8000 사용

**해결 방안**:
- **옵션 1**: Auth Server를 다른 포트로 변경 (예: 8001)
- **옵션 2**: Aura-Platform을 다른 포트로 변경 (예: 8002)
- **옵션 3**: Gateway 라우팅에서 포트 분리

**권장**: 옵션 1 (Auth Server 포트 변경)

---

### 2. Redis 연결

**현재 상태**: dwp-backend의 Docker Compose Redis 사용 가능

**연결 정보**:
- Host: `localhost`
- Port: `6379`
- Password: 없음 (기본)

**확인 방법**:
```bash
# Redis 컨테이너 확인
cd /path/to/dwp-backend
docker-compose ps | grep redis

# Redis 연결 테스트
docker exec -it dwp-redis redis-cli ping
# 응답: PONG
```

---

### 3. SSE 타임아웃

**Gateway 설정**:
- Response Timeout: 300초 (5분)
- Connect Timeout: 10초

**Aura-Platform 설정**:
- HITL 신호 대기 타임아웃: 300초 (5분)

**권장**: Gateway 타임아웃과 동일하게 설정

---

## 📊 현재 상태

### 구현 완료율

| 항목 | Aura-Platform | DWP Backend | 상태 |
|------|--------------|-------------|------|
| SSE 스트리밍 | ✅ 100% | ✅ 100% | 완료 |
| JWT 인증 | ✅ 100% | ✅ 100% | 완료 |
| HITL 구독 | ✅ 100% | - | 완료 |
| HITL 발행 | - | ⚠️ 0% | **구현 필요** |
| HITL API | ✅ 50% | ⚠️ 0% | **구현 필요** |

**전체 진행률**: 70% (Aura-Platform 완료, Backend HITL 발행 필요)

---

## 🔗 관련 문서

### Aura-Platform 문서
- [BACKEND_INTEGRATION_STATUS.md](BACKEND_INTEGRATION_STATUS.md) - 연동 상태 상세
- [JWT_COMPATIBILITY.md](JWT_COMPATIBILITY.md) - JWT 호환성 가이드
- [FRONTEND_V1_SPEC.md](FRONTEND_V1_SPEC.md) - 프론트엔드 명세 v1.0

### DWP Backend 문서
- [AURA_PLATFORM_INTEGRATION_GUIDE.md](../dwp-backend/docs/AURA_PLATFORM_INTEGRATION_GUIDE.md) - 연동 가이드
- [AURA_PLATFORM_QUICK_REFERENCE.md](../dwp-backend/docs/AURA_PLATFORM_QUICK_REFERENCE.md) - 빠른 참조

---

## 📞 문의

통합 과정에서 문제가 발생하거나 추가 정보가 필요한 경우, Aura-Platform 개발팀에 문의하세요.

**다음 단계**: DWP Backend에서 HITL 승인/거절 API 구현 후 통합 테스트 진행

---

**문서 버전**: v1.0  
**최종 업데이트**: 2026-01-16
