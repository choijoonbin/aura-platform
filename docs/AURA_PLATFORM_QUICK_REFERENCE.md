# Aura-Platform 빠른 참조 가이드

> **핵심 정보만 빠르게 확인**  
> 상세 내용은 [AURA_PLATFORM_INTEGRATION_GUIDE.md](./AURA_PLATFORM_INTEGRATION_GUIDE.md) 참조

---

## 🔑 핵심 정보

### 엔드포인트

| 경로 | 설명 | 메서드 |
|------|------|--------|
| `/aura/test/stream` | SSE 스트리밍 | GET |
| `/aura/hitl/requests/{requestId}` | 승인 요청 조회 | GET |
| `/aura/hitl/approve/{requestId}` | 승인 처리 | POST |
| `/aura/hitl/reject/{requestId}` | 거절 처리 | POST |
| `/aura/hitl/signals/{sessionId}` | 신호 조회 | GET |

**⚠️ 주의**: Gateway를 통한 접근 시 `/api/aura/**` 경로 사용

### 필수 헤더

```
Authorization: Bearer {JWT_TOKEN}
X-Tenant-ID: {tenant_id}
```

### SSE 이벤트 타입

1. `thought` - 사고 과정
2. `plan_step` - 실행 계획 단계
3. `tool_execution` - 도구 실행
4. `hitl` - 승인 요청 (⚠️ 실행 중지 후 대기)
5. `content` - 최종 결과

### HITL 프로세스

```
1. hitl 이벤트 전송 → 실행 중지
2. Redis Pub/Sub 구독: hitl:channel:{sessionId}
3. 승인/거절 신호 수신
4. 승인 시 실행 재개, 거절 시 중단
```

### Redis 채널

- `hitl:channel:{sessionId}` - HITL 신호 수신
- `dwp:events:all` - 모든 이벤트 구독 (선택)

### JWT 검증

- 알고리즘: HS256
- Secret: 환경 변수 `JWT_SECRET`
- 필수 클레임: `sub`, `tenant_id`, `exp`, `iat`
- ⚠️ `exp`, `iat`는 Unix timestamp (초 단위 정수)

---

## 📝 코드 스니펫

### SSE 스트리밍 (FastAPI)

```python
from fastapi.responses import StreamingResponse
import json

@app.get("/aura/test/stream")
async def stream_response():
    async def event_generator():
        # thought 이벤트
        yield f"event: thought\ndata: {json.dumps({'type': 'thought', 'data': {'content': '분석 중...'}})}\n\n"
        
        # plan_step 이벤트
        yield f"event: plan_step\ndata: {json.dumps({'type': 'plan_step', 'data': {'id': 'step-1', 'status': 'in_progress'}})}\n\n"
        
        # hitl 이벤트 (승인 요청)
        request_id = "req-12345"
        session_id = "session-abc"
        yield f"event: hitl\ndata: {json.dumps({'type': 'hitl', 'data': {'requestId': request_id, 'requiresApproval': True}})}\n\n"
        
        # 승인 대기
        signal = await wait_for_hitl_signal(session_id)
        if signal['type'] == 'approval':
            # 실행 재개
            yield f"event: content\ndata: {json.dumps({'type': 'content', 'data': {'content': '작업 완료'}})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )
```

### HITL 신호 대기 (Redis)

```python
import redis
import json
import asyncio

async def wait_for_hitl_signal(session_id: str, timeout: int = 300):
    redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
    pubsub = redis_client.pubsub()
    pubsub.subscribe(f'hitl:channel:{session_id}')
    
    try:
        for message in pubsub.listen():
            if message['type'] == 'message':
                signal = json.loads(message['data'])
                return signal
    except asyncio.TimeoutError:
        return {'type': 'timeout'}
    finally:
        pubsub.close()
```

### JWT 검증 (FastAPI)

```python
from fastapi import Header, HTTPException
from jose import jwt, JWTError
import os

SECRET_KEY = os.getenv("JWT_SECRET")
ALGORITHM = "HS256"

async def verify_token(authorization: str = Header(...), x_tenant_id: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    
    token = authorization[7:]
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        tenant_id = payload.get("tenant_id")
        
        if tenant_id != x_tenant_id:
            raise HTTPException(status_code=403, detail="Tenant ID mismatch")
        
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
```

---

## 🔍 문제 해결

### 401 Unauthorized
- JWT 토큰이 유효한지 확인
- `exp`, `iat`가 Unix timestamp인지 확인
- Secret Key가 일치하는지 확인

### SSE 연결 끊김
- Gateway 타임아웃 확인 (300초)
- `Cache-Control: no-cache` 헤더 확인
- 커넥션 유지 확인

### HITL 신호 수신 실패
- Redis 연결 확인
- 채널명 확인 (`hitl:channel:{sessionId}`)
- 세션 ID 일치 확인

---

**더 자세한 내용은 [AURA_PLATFORM_INTEGRATION_GUIDE.md](./AURA_PLATFORM_INTEGRATION_GUIDE.md) 참조**
