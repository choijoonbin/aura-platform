# Phase 2 통합 테스트 가이드

## 🧪 Backend & Frontend 통합 테스트

Phase 2에서 구현한 기능들을 dwp_backend 및 dwp_frontend와 통합 테스트하기 위한 가이드입니다.

---

## 1. JWT 인증 테스트 (Backend 연동)

### 사전 준비

**dwp_backend와 SECRET_KEY 동기화**

```bash
# aura-platform/.env
SECRET_KEY=<dwp_backend와 동일한 키>
```

### 테스트 시나리오

#### 1.1 dwp_backend에서 JWT 발급

```python
# dwp_backend에서 실행
from datetime import datetime, timedelta
from jose import jwt

SECRET_KEY = "your_shared_secret_key"
ALGORITHM = "HS256"

# 토큰 생성
payload = {
    "sub": "user123",
    "tenant_id": "tenant1",
    "email": "user@example.com",
    "role": "user",
    "exp": datetime.utcnow() + timedelta(minutes=30),
}

token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
print(f"Token: {token}")
```

#### 1.2 aura-platform API 호출

```bash
# 토큰으로 인증된 요청
curl -X GET http://localhost:8000/health \
  -H "Authorization: Bearer <token>" \
  -H "X-Tenant-ID: tenant1"

# 예상 응답
{
  "status": "healthy",
  "environment": "development"
}

# 응답 헤더에 X-Request-ID 포함되어야 함
```

#### 1.3 인증 실패 테스트

```bash
# 토큰 없이 요청 (401 Unauthorized)
curl -X GET http://localhost:8000/health

# 잘못된 토큰 (401 Unauthorized)
curl -X GET http://localhost:8000/health \
  -H "Authorization: Bearer invalid_token"

# Tenant ID 불일치 (403 Forbidden)
curl -X GET http://localhost:8000/health \
  -H "Authorization: Bearer <token>" \
  -H "X-Tenant-ID: different_tenant"
```

---

## 2. Streaming 응답 테스트 (Frontend 연동)

### 테스트 엔드포인트 생성

**`api/routes/test_streaming.py` 생성 (테스트용)**

```python
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from api.dependencies import CurrentUser
from core.llm import get_llm_client

router = APIRouter(prefix="/test", tags=["test"])

@router.get("/stream")
async def test_stream(user: CurrentUser):
    """스트리밍 테스트 엔드포인트"""
    async def generate():
        client = get_llm_client()
        async for chunk in client.astream("Tell me a short story"):
            yield f"data: {chunk}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")
```

### Frontend 연동 코드 (React)

```typescript
// dwp_frontend에서 실행
const testStreaming = async () => {
  const token = localStorage.getItem('accessToken');
  
  const response = await fetch('http://localhost:8000/test/stream', {
    headers: {
      'Authorization': `Bearer ${token}`,
      'X-Tenant-ID': 'tenant1',
    },
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    
    const chunk = decoder.decode(value);
    const lines = chunk.split('\n\n');
    
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const text = line.slice(6);
        console.log('Received:', text);
        // UI 업데이트
      }
    }
  }
};
```

---

## 3. Redis Checkpoint 테스트

### 테스트 스크립트

**`scripts/test_checkpoint.py` 생성**

```python
import asyncio
from core.memory import get_checkpointer

async def test_checkpoint():
    checkpointer = await get_checkpointer()
    
    # 1. Checkpoint 저장
    thread_id = "test_thread_001"
    state = {
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ],
        "context": {"user_id": "user123"},
    }
    
    checkpoint_id = await checkpointer.save_checkpoint(thread_id, state)
    print(f"✓ Checkpoint saved: {checkpoint_id}")
    
    # 2. Checkpoint 로드
    loaded_state = await checkpointer.load_checkpoint(thread_id)
    assert loaded_state == state
    print(f"✓ Checkpoint loaded successfully")
    
    # 3. Checkpoint 목록
    checkpoints = await checkpointer.list_checkpoints(thread_id)
    print(f"✓ Found {len(checkpoints)} checkpoint(s)")
    
    # 4. Checkpoint 삭제
    await checkpointer.delete_checkpoint(thread_id, checkpoint_id)
    print(f"✓ Checkpoint deleted")
    
    print("\n✅ All checkpoint tests passed!")

if __name__ == "__main__":
    asyncio.run(test_checkpoint())
```

**실행**

```bash
cd /Users/joonbinchoi/Work/dwp/aura-platform
source venv/bin/activate
python scripts/test_checkpoint.py
```

---

## 4. 대화 메모리 테스트

### 테스트 스크립트

**`scripts/test_conversation.py` 생성**

```python
import asyncio
from core.memory import (
    add_user_message,
    add_assistant_message,
    get_recent_context,
    get_conversation_history,
)

async def test_conversation():
    thread_id = "test_conversation_001"
    tenant_id = "tenant1"
    
    # 1. 사용자 메시지 추가
    await add_user_message(
        thread_id,
        "What is LangGraph?",
        tenant_id,
    )
    print("✓ User message added")
    
    # 2. 어시스턴트 메시지 추가
    await add_assistant_message(
        thread_id,
        "LangGraph is a library for building stateful agents.",
        tenant_id,
    )
    print("✓ Assistant message added")
    
    # 3. 대화 조회
    history = await get_conversation_history()
    messages = await history.get_messages(thread_id, tenant_id)
    print(f"✓ Retrieved {len(messages)} message(s)")
    
    # 4. LLM 컨텍스트 생성
    context = await get_recent_context(thread_id, tenant_id)
    print(f"✓ Context:\n{context}\n")
    
    # 5. 히스토리 삭제
    await history.clear_history(thread_id, tenant_id)
    print("✓ History cleared")
    
    print("\n✅ All conversation tests passed!")

if __name__ == "__main__":
    asyncio.run(test_conversation())
```

---

## 5. 권한 시스템 테스트

### Python 스크립트

```python
from core.security.auth import User
from core.security.permissions import (
    Permission,
    has_permission,
    can_execute_agent,
    is_admin,
)

# 테스트 사용자
admin_user = User(user_id="admin1", role="admin")
regular_user = User(user_id="user1", role="user")
guest_user = User(user_id="guest1", role="guest")

# 권한 테스트
print("Admin permissions:")
print(f"  Can execute agent: {can_execute_agent(admin_user)}")  # True
print(f"  Is admin: {is_admin(admin_user)}")  # True

print("\nRegular user permissions:")
print(f"  Can execute agent: {can_execute_agent(regular_user)}")  # True
print(f"  Is admin: {is_admin(regular_user)}")  # False

print("\nGuest permissions:")
print(f"  Can execute agent: {can_execute_agent(guest_user)}")  # False
print(f"  Is admin: {is_admin(guest_user)}")  # False
```

---

## 6. 통합 테스트 체크리스트

### Backend 연동 확인

- [ ] dwp_backend와 SECRET_KEY 동기화 완료
- [ ] dwp_backend에서 발급한 JWT로 aura-platform API 호출 성공
- [ ] X-Tenant-ID 헤더 검증 동작
- [ ] 인증 실패 시 401/403 에러 정상 반환
- [ ] 미들웨어 로깅 정상 작동

### Frontend 연동 확인

- [ ] React에서 Bearer Token 헤더 전송 성공
- [ ] SSE 스트리밍 응답 수신 성공
- [ ] 실시간 텍스트 업데이트 UI 구현
- [ ] 에러 처리 (401, 403) UI 반영

### Redis 연동 확인

- [ ] Redis 서버 연결 성공
- [ ] Checkpoint 저장/로드 정상 동작
- [ ] 대화 히스토리 저장/조회 정상 동작
- [ ] TTL 설정 확인 (24시간/7일)

### 권한 시스템 확인

- [ ] 역할별 권한 정상 동작
- [ ] 권한 없는 요청 403 에러 반환
- [ ] 의존성 주입을 통한 권한 확인 동작

---

## 7. 문제 해결

### Redis 연결 실패

```bash
# Redis 서버 실행 확인
redis-cli ping
# 응답: PONG

# Redis URL 확인
echo $REDIS_URL
# 또는 .env 파일 확인
```

### JWT 검증 실패

```bash
# SECRET_KEY 확인
# aura-platform/.env와 dwp_backend/.env 비교

# 토큰 디코딩 (디버깅)
python -c "from jose import jwt; print(jwt.decode('TOKEN', 'SECRET', algorithms=['HS256']))"
```

### CORS 에러

```bash
# .env 파일에서 allowed_origins 확인
ALLOWED_ORIGINS=["http://localhost:3000", "http://localhost:8001"]
```

---

## 8. 다음 단계

Phase 2 통합 테스트가 모두 통과하면:

1. ✅ **Phase 3로 진행**: Dev Domain 구현 시작
2. 🔄 **CI/CD 통합**: 자동화된 테스트 파이프라인 구축
3. 📊 **모니터링**: Redis 메모리 사용량, API 응답 시간 추적

---

**테스트 완료 시 이 문서에 체크리스트 업데이트를 부탁드립니다!** ✅
