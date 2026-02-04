# Aura-Platform 업데이트 사항

> **대상**: Aura-Platform 개발팀  
> **전달 일자**: 2026-01-16  
> **DWP Backend 버전**: v1.0  
> **원본**: `dwp-backend/docs/integration/AURA_PLATFORM_UPDATE.md`

---

## 📋 변경 사항 요약

DWP Backend에서 완료된 작업 및 Aura-Platform에 전달할 업데이트 사항입니다.

---

## ✅ 완료된 작업

### 1. HITL 승인/거절 API 구현 완료 ✅

**구현 위치**: `dwp-main-service`

**엔드포인트**:
- `POST /api/aura/hitl/approve/{requestId}` - 승인 처리
- `POST /api/aura/hitl/reject/{requestId}` - 거절 처리

**Gateway 경로**: `http://localhost:8080/api/aura/hitl/**`

**구현 내용**:
- ✅ 승인/거절 요청 처리
- ✅ Redis Pub/Sub 신호 발행 (`hitl:channel:{sessionId}`)
- ✅ 신호 저장 (`hitl:signal:{sessionId}`) - TTL: 5분
- ✅ Unix timestamp (초 단위 정수) 사용

---

### 2. 프론트엔드 API 스펙 반영 ✅

**프론트엔드 요구사항** (2026-01-16):
- ✅ SSE 엔드포인트: `POST /api/aura/test/stream` (GET → POST 변경)
- ✅ 요청 본문: `prompt`와 `context` 객체 포함
- ✅ SSE 이벤트 타입 상세 정의
- ✅ 새로운 이벤트 타입: `timeline_step_update`, `plan_step_update`
- ✅ 스트림 종료: `data: [DONE]` 형식

---

### 3. 포트 변경 사항

**변경 전**:
- Auth Server: 포트 8000
- Aura-Platform: 포트 8000 (충돌)

**변경 후**:
- Auth Server: 포트 **8001**
- Aura-Platform: 포트 **9000**

**Gateway 라우팅**:
- `/api/aura/**` → `http://localhost:9000` (Aura-Platform)
- `/api/auth/**` → `http://localhost:8001` (Auth Server)

---

### 4. HITL 신호 형식

**승인 신호**:
```json
{
  "type": "approval",
  "requestId": "req-12345",
  "status": "approved",
  "timestamp": 1706152860
}
```

**거절 신호**:
```json
{
  "type": "rejection",
  "requestId": "req-12345",
  "status": "rejected",
  "reason": "사용자 거절",
  "timestamp": 1706152860
}
```

**중요**: `timestamp`는 Unix timestamp (초 단위 정수)입니다.

---

## 🔧 Aura-Platform에서 확인할 사항

### 1. SSE 엔드포인트 변경 (중요 ⚠️)

**변경 사항**:
- **이전**: `GET /api/aura/test/stream?message={message}`
- **현재**: `POST /api/aura/test/stream`

**요청 형식**:
```http
POST /api/aura/test/stream
Content-Type: application/json
Authorization: Bearer {JWT_TOKEN}
X-Tenant-ID: {TENANT_ID}

{
  "prompt": "사용자 질문",
  "context": {
    "url": "http://localhost:4200/mail",
    "path": "/mail",
    "title": "메일 인박스",
    "activeApp": "mail",
    "itemId": "msg-123",
    "metadata": {
      "headings": ["받은 메일함", "중요 메일"],
      "hasTables": true,
      "tableCount": 1
    }
  }
}
```

**응답 형식**: `text/event-stream`

**스트림 종료**:
```
data: [DONE]\n\n
```

---

### 2. 포트 설정

**Aura-Platform 실행 시 포트 확인**:
```bash
# 포트 9000으로 실행되어야 함
uvicorn main:app --host 0.0.0.0 --port 9000
```

**환경 변수 설정** (선택):
```bash
export PORT=9000
```

---

### 3. Gateway 라우팅 확인

**Gateway를 통한 접근**:
- `http://localhost:8080/api/aura/test/stream` → Aura-Platform (포트 9000)
- `http://localhost:8080/api/aura/hitl/**` → Main Service (포트 8081)

**라우팅 순서**:
1. `/api/aura/hitl/**` → Main Service (HITL API, 우선 매칭)
2. `/api/aura/**` → Aura-Platform (나머지 Aura 경로)

**주의**: HITL API는 Main Service에 있으므로, Gateway에서 `/api/aura/hitl/**` 경로를 Main Service로 라우팅하도록 설정되어 있습니다.

---

### 4. SSE 이벤트 타입 (프론트엔드 요구사항)

**필수 이벤트 타입**:
- `thought` / `thinking` - 사고 과정
- `plan_step` - 작업 계획 단계
- `plan_step_update` - 계획 단계 상태 업데이트 (선택)
- `tool_execution` / `action` - 도구 실행
- `hitl` / `approval_required` - 승인 요청
- `content` / `message` - 최종 결과
- `timeline_step_update` - 타임라인 단계 업데이트 (선택)

---

### 5. Redis Pub/Sub 채널

**구독 채널**: `hitl:channel:{sessionId}`

**신호 형식**: JSON 문자열

**예시**:
```python
import redis
import json

r = redis.Redis(host='localhost', port=6379, db=0)
pubsub = r.pubsub()
pubsub.subscribe(f'hitl:channel:{session_id}')

for message in pubsub.listen():
    if message['type'] == 'message':
        signal = json.loads(message['data'])
        if signal['type'] == 'approval':
            # 승인 처리
            break
        elif signal['type'] == 'rejection':
            # 거절 처리
            break
```

---

### 4. 신호 조회 API

**엔드포인트**: `GET /api/aura/hitl/signals/{sessionId}`

**Gateway 경로**: `http://localhost:8080/api/aura/hitl/signals/{sessionId}`

**응답**:
```json
{
  "status": "SUCCESS",
  "message": "Signal retrieved",
  "data": "{\"type\":\"approval\",\"requestId\":\"req-12345\",\"status\":\"approved\",\"timestamp\":1706152860}",
  "success": true,
  "timestamp": "2026-01-16T12:00:00"
}
```

**사용 방법**: Pub/Sub 구독이 실패한 경우, 폴링 방식으로 신호를 조회할 수 있습니다.

---

## 🧪 테스트 방법

### 1. 포트 확인

```bash
# Aura-Platform이 포트 9000에서 실행 중인지 확인
curl http://localhost:9000/health

# Gateway를 통한 접근 확인 (POST 요청)
curl -X POST http://localhost:8080/api/aura/test/stream \
  -H "Authorization: Bearer {TOKEN}" \
  -H "X-Tenant-ID: tenant1" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "테스트 메시지", "context": {}}'
```

---

### 2. HITL 승인 테스트

```bash
# 1. SSE 스트리밍 시작 (HITL 이벤트 발생 대기)
curl -N -X POST http://localhost:8080/api/aura/test/stream \
  -H "Authorization: Bearer {TOKEN}" \
  -H "X-Tenant-ID: tenant1" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "메일 3개를 삭제해주세요", "context": {}}'

# 2. HITL 이벤트 수신 후 requestId 확인

# 3. 승인 처리
curl -X POST http://localhost:8080/api/aura/hitl/approve/{requestId} \
  -H "Authorization: Bearer {TOKEN}" \
  -H "X-Tenant-ID: tenant1" \
  -H "X-User-ID: user123" \
  -H "Content-Type: application/json" \
  -d '{"userId": "user123"}'

# 4. Redis Pub/Sub에서 신호 확인
redis-cli PUBSUB CHANNELS hitl:channel:*
```

---

## 📊 현재 상태

### 구현 완료율

| 항목 | DWP Backend | Aura-Platform | 상태 |
|------|------------|--------------|------|
| SSE 스트리밍 | ✅ 100% | ✅ 100% | 완료 |
| JWT 인증 | ✅ 100% | ✅ 100% | 완료 |
| HITL 구독 | - | ✅ 100% | 완료 |
| HITL 발행 | ✅ 100% | - | 완료 |
| HITL API | ✅ 100% | ✅ 50% | 완료 |

**전체 진행률**: 100% ✅

---

## 🔗 관련 문서

- **원본**: `dwp-backend/docs/integration/AURA_PLATFORM_UPDATE.md`
- dwp-backend: `docs/FRONTEND_API_SPEC.md`, `docs/integration/FRONTEND_INTEGRATION_GUIDE.md`

---

## ⚠️ 주의사항

### 1. 포트 충돌 해결

- Auth Server와 Aura-Platform이 서로 다른 포트를 사용합니다.
- 포트 충돌 문제가 해결되었습니다.

---

### 2. Gateway 타임아웃

- Gateway SSE 타임아웃: 300초 (5분)
- Aura-Platform HITL 대기 타임아웃: 300초 (5분)
- 동일하게 설정되어 있습니다.

---

### 3. Redis 연결

- Redis는 `localhost:6379`에서 실행되어야 합니다.
- Docker Compose로 실행 중인 경우 자동으로 연결됩니다.

---

## 📞 문의

통합 과정에서 문제가 발생하거나 추가 정보가 필요한 경우, DWP Backend 개발팀에 문의하세요.

**다음 단계**: 통합 테스트 진행 및 프로덕션 배포 준비

---

**문서 버전**: v1.0  
**최종 업데이트**: 2026-01-16
