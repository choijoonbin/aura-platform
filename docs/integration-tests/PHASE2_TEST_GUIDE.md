# Phase 2 통합 테스트 완벽 가이드

## 📋 목차

1. [사전 준비](#1-사전-준비)
2. [Redis 연결 테스트](#2-redis-연결-테스트)
3. [독립 실행 테스트](#3-독립-실행-테스트-aura-platform-단독)
4. [Backend 연동 테스트](#4-backend-연동-테스트-dwp_backend)
5. [Frontend 연동 테스트](#5-frontend-연동-테스트-dwp_frontend)
6. [문제 해결](#6-문제-해결)

---

## 1. 사전 준비

### 1.1 Redis 설치 및 실행

**두 가지 방법 중 하나를 선택하세요:**

#### 방법 1: Docker Compose 사용 (권장, dwp_backend와 공유)

dwp_backend 프로젝트에서 Docker Compose로 Redis가 이미 실행 중인 경우, 별도 설치가 필요 없습니다.

```bash
# dwp_backend 프로젝트에서 Docker Compose 확인
cd /path/to/dwp-backend
docker-compose ps

# Redis 컨테이너가 실행 중인지 확인
# 예상 출력:
# NAME                IMAGE               STATUS
# dwp-redis           redis:7             Up

# Redis 연결 테스트
redis-cli -h localhost -p 6379 ping
# 응답: PONG 이면 성공!

# 또는 Docker 컨테이너 내부에서 테스트
docker exec -it dwp-redis redis-cli ping
# 응답: PONG
```

**Docker Compose로 Redis 시작** (dwp_backend 프로젝트에서):
```bash
cd /path/to/dwp-backend

# Redis만 시작 (다른 서비스는 제외)
docker-compose up -d redis

# 또는 전체 인프라 시작
docker-compose up -d

# 실행 상태 확인
docker-compose ps

# 로그 확인
docker-compose logs -f redis
```

#### 방법 2: 로컬에 직접 설치 (Docker 미사용 시)

Docker를 사용하지 않는 경우, 로컬에 Redis를 직접 설치할 수 있습니다.

```bash
# macOS
brew install redis

# Redis 서비스 시작
brew services start redis

# Redis 실행 확인
redis-cli ping
# 응답: PONG 이면 성공!

# Redis 버전 확인
redis-cli --version

# Redis 연결 테스트
redis-cli
127.0.0.1:6379> SET test_key "test_value"
127.0.0.1:6379> GET test_key
# "test_value" 응답 확인
127.0.0.1:6379> DEL test_key
127.0.0.1:6379> exit
```

**⚠️ 중요**: 
- Docker Compose를 사용하는 경우, Redis는 `localhost:6379`에서 실행됩니다.
- Aura-Platform의 `.env` 파일에서 `REDIS_URL=redis://localhost:6379/0`로 설정하면 됩니다.
- dwp_backend와 동일한 Redis 인스턴스를 공유할 수 있습니다.

### 1.2 환경 변수 설정 확인

```bash
cd /Users/joonbinchoi/Work/dwp/aura-platform

# .env 파일 확인
cat .env | grep -E "REDIS_URL|SECRET_KEY|JWT_SECRET|OPENAI_API_KEY"

# 필수 설정 확인
# - REDIS_URL=redis://localhost:6379/0 (Docker Compose 사용 시 동일)
# - SECRET_KEY 또는 JWT_SECRET=<32자 이상의 안전한 키> (dwp_backend와 동일)
# - OPENAI_API_KEY=<실제 OpenAI API 키>
```

**Redis URL 설정**:
- Docker Compose 사용: `REDIS_URL=redis://localhost:6379/0`
- 로컬 설치: `REDIS_URL=redis://localhost:6379/0`
- 원격 Redis: `REDIS_URL=redis://your-redis-host:6379/0`

**JWT 시크릿 키 설정**:
- `SECRET_KEY` 또는 `JWT_SECRET` 중 하나 설정 (dwp_backend와 동일한 값)
- dwp_backend의 `JWT_SECRET` 환경 변수와 동일하게 설정해야 합니다.

---

## 2. Redis 연결 테스트

### 2.1 Redis Store 기본 테스트

**테스트 스크립트 생성**: `scripts/test_redis_basic.py`

```python
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.memory import get_redis_store

async def test_redis_basic():
    print("=" * 60)
    print("🔍 Testing Redis Store Basic Operations")
    print("=" * 60)
    
    store = await get_redis_store()
    
    # 1. Set/Get 테스트
    print("\n1. Testing SET/GET...")
    await store.set("test_key", b"test_value", ttl=60)
    value = await store.get("test_key")
    assert value == b"test_value"
    print("  ✓ SET/GET works")
    
    # 2. JSON 테스트
    print("\n2. Testing JSON operations...")
    test_data = {"name": "Aura", "version": "0.2.0"}
    await store.set_json("test_json", test_data, ttl=60)
    loaded_data = await store.get_json("test_json")
    assert loaded_data == test_data
    print("  ✓ JSON SET/GET works")
    
    # 3. Exists 테스트
    print("\n3. Testing EXISTS...")
    exists = await store.exists("test_key")
    assert exists is True
    print("  ✓ EXISTS works")
    
    # 4. Delete 테스트
    print("\n4. Testing DELETE...")
    await store.delete("test_key")
    value = await store.get("test_key")
    assert value is None
    print("  ✓ DELETE works")
    
    # Cleanup
    await store.delete("test_json")
    
    print("\n" + "=" * 60)
    print("✅ All Redis basic tests passed!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_redis_basic())
```

**실행**:
```bash
cd /Users/joonbinchoi/Work/dwp/aura-platform
source venv/bin/activate
python scripts/test_redis_basic.py
```

### 2.2 Checkpoint 테스트

**테스트 스크립트**: `scripts/test_checkpoint.py`

```python
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.memory import get_checkpointer

async def test_checkpoint():
    print("=" * 60)
    print("🔍 Testing LangGraph Checkpointer")
    print("=" * 60)
    
    checkpointer = await get_checkpointer()
    thread_id = "test_thread_001"
    
    # 1. Checkpoint 저장
    print("\n1. Saving checkpoint...")
    state = {
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi! How can I help?"},
        ],
        "context": {"user_id": "user123", "step": 1},
    }
    
    checkpoint_id = await checkpointer.save_checkpoint(thread_id, state)
    print(f"  ✓ Checkpoint saved: {checkpoint_id}")
    
    # 2. Checkpoint 로드
    print("\n2. Loading checkpoint...")
    loaded_state = await checkpointer.load_checkpoint(thread_id)
    assert loaded_state == state
    print("  ✓ Checkpoint loaded successfully")
    print(f"  - Messages: {len(loaded_state['messages'])}")
    print(f"  - Context: {loaded_state['context']}")
    
    # 3. 여러 Checkpoint 저장
    print("\n3. Saving multiple checkpoints...")
    state2 = {**state, "context": {"user_id": "user123", "step": 2}}
    checkpoint_id_2 = await checkpointer.save_checkpoint(thread_id, state2)
    print(f"  ✓ Checkpoint 2 saved: {checkpoint_id_2}")
    
    # 4. Checkpoint 목록
    print("\n4. Listing checkpoints...")
    checkpoints = await checkpointer.list_checkpoints(thread_id)
    print(f"  ✓ Found {len(checkpoints)} checkpoint(s)")
    for cp in checkpoints:
        print(f"    - {cp['checkpoint_id']} (timestamp: {cp['timestamp']})")
    
    # 5. 특정 Checkpoint 로드
    print("\n5. Loading specific checkpoint...")
    state_1 = await checkpointer.load_checkpoint(thread_id, checkpoint_id)
    assert state_1['context']['step'] == 1
    print(f"  ✓ Loaded checkpoint {checkpoint_id} (step 1)")
    
    # 6. Cleanup
    print("\n6. Cleaning up...")
    await checkpointer.delete_checkpoint(thread_id)
    print("  ✓ All checkpoints deleted")
    
    print("\n" + "=" * 60)
    print("✅ All checkpoint tests passed!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_checkpoint())
```

**실행**:
```bash
python scripts/test_checkpoint.py
```

### 2.3 대화 메모리 테스트

**테스트 스크립트**: `scripts/test_conversation.py`

```python
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.memory import (
    add_user_message,
    add_assistant_message,
    get_recent_context,
    get_conversation_history,
)

async def test_conversation():
    print("=" * 60)
    print("🔍 Testing Conversation Memory")
    print("=" * 60)
    
    thread_id = "test_conv_001"
    tenant_id = "tenant1"
    
    # 1. 사용자 메시지 추가
    print("\n1. Adding user message...")
    await add_user_message(
        thread_id,
        "What is LangGraph?",
        tenant_id,
    )
    print("  ✓ User message added")
    
    # 2. 어시스턴트 메시지 추가
    print("\n2. Adding assistant message...")
    await add_assistant_message(
        thread_id,
        "LangGraph is a library for building stateful, multi-actor applications with LLMs.",
        tenant_id,
    )
    print("  ✓ Assistant message added")
    
    # 3. 추가 대화
    print("\n3. Adding more messages...")
    await add_user_message(thread_id, "Can you give me an example?", tenant_id)
    await add_assistant_message(
        thread_id,
        "Sure! You can create agents that maintain state across interactions.",
        tenant_id,
    )
    print("  ✓ Additional messages added")
    
    # 4. 대화 조회
    print("\n4. Retrieving conversation...")
    history = await get_conversation_history()
    messages = await history.get_messages(thread_id, tenant_id)
    print(f"  ✓ Retrieved {len(messages)} message(s)")
    
    for i, msg in enumerate(messages, 1):
        print(f"    {i}. [{msg.role.value}] {msg.content[:50]}...")
    
    # 5. LLM 컨텍스트 생성
    print("\n5. Generating LLM context...")
    context = await get_recent_context(thread_id, tenant_id, limit=10)
    print("  ✓ Context generated:")
    print("  " + "-" * 56)
    for line in context.split('\n'):
        print(f"  {line}")
    print("  " + "-" * 56)
    
    # 6. 메타데이터 조회
    print("\n6. Getting metadata...")
    metadata = await history.get_thread_metadata(thread_id, tenant_id)
    print(f"  ✓ Thread ID: {metadata['thread_id']}")
    print(f"  ✓ Tenant ID: {metadata['tenant_id']}")
    print(f"  ✓ Message count: {metadata['message_count']}")
    print(f"  ✓ Created at: {metadata['created_at']}")
    
    # 7. Cleanup
    print("\n7. Cleaning up...")
    await history.clear_history(thread_id, tenant_id)
    print("  ✓ History cleared")
    
    print("\n" + "=" * 60)
    print("✅ All conversation tests passed!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_conversation())
```

**실행**:
```bash
python scripts/test_conversation.py
```

---

## 3. 독립 실행 테스트 (Aura-Platform 단독)

### 3.1 서버 시작

```bash
cd /Users/joonbinchoi/Work/dwp/aura-platform
source venv/bin/activate

# 인증 비활성화 모드로 시작 (개발 테스트용)
export REQUIRE_AUTH=false
python main.py
```

**또 다른 터미널에서 테스트**:

### 3.2 기본 엔드포인트 테스트

```bash
# 1. Root endpoint
curl http://localhost:8000/

# 예상 응답:
# {
#   "message": "Welcome to Aura-Platform!",
#   "version": "0.1.0",
#   "status": "operational"
# }

# 2. Health check
curl http://localhost:8000/health

# 예상 응답:
# {
#   "status": "healthy",
#   "environment": "development"
# }

# 3. API 문서
open http://localhost:8000/docs
```

### 3.3 JWT 생성 및 테스트 (독립)

**테스트 스크립트**: `scripts/test_jwt_standalone.py`

```python
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.security import create_token, verify_token, get_user_from_token

def test_jwt_standalone():
    print("=" * 60)
    print("🔍 Testing JWT (Standalone)")
    print("=" * 60)
    
    # 1. 토큰 생성
    print("\n1. Creating token...")
    token = create_token(
        user_id="test_user_001",
        tenant_id="tenant1",
        email="test@example.com",
        role="user",
    )
    print(f"  ✓ Token created")
    print(f"  Token (first 50 chars): {token[:50]}...")
    
    # 2. 토큰 검증
    print("\n2. Verifying token...")
    payload = verify_token(token)
    assert payload is not None
    print(f"  ✓ Token verified")
    print(f"  - User ID: {payload.user_id}")
    print(f"  - Tenant ID: {payload.tenant_id}")
    print(f"  - Role: {payload.role}")
    
    # 3. 사용자 정보 추출
    print("\n3. Extracting user info...")
    user = get_user_from_token(token)
    assert user is not None
    print(f"  ✓ User extracted")
    print(f"  - User ID: {user.user_id}")
    print(f"  - Email: {user.email}")
    print(f"  - Role: {user.role}")
    print(f"  - Authenticated: {user.is_authenticated}")
    
    print("\n" + "=" * 60)
    print("✅ JWT standalone test passed!")
    print("=" * 60)
    print(f"\n💡 Use this token for API testing:\n{token}")

if __name__ == "__main__":
    test_jwt_standalone()
```

**실행**:
```bash
python scripts/test_jwt_standalone.py
```

### 3.4 생성된 토큰으로 API 호출

```bash
# 위에서 생성된 토큰을 복사하여 사용
export TOKEN="<생성된_토큰>"

# 인증된 요청 (서버가 REQUIRE_AUTH=true일 때)
curl http://localhost:8000/health \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1"

# X-Request-ID 헤더 확인
curl -i http://localhost:8000/health \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1"
```

---

## 4. Backend 연동 테스트 (dwp_backend)

### 4.1 SECRET_KEY 동기화

**Aura-Platform `.env` 파일**:
```bash
# /Users/joonbinchoi/Work/dwp/aura-platform/.env
SECRET_KEY=<dwp_backend와 동일한 키>
```

**dwp_backend `.env` 파일 확인**:
```bash
# dwp_backend/.env에서 SECRET_KEY 확인
cd /path/to/dwp_backend
cat .env | grep SECRET_KEY
```

⚠️ **두 SECRET_KEY가 완전히 동일해야 합니다!**

### 4.2 dwp_backend에서 JWT 발급

**dwp_backend에서 실행** (예시):

```python
# dwp_backend/test_jwt_for_aura.py
from datetime import datetime, timedelta, timezone
from jose import jwt

# .env에서 로드한 SECRET_KEY
SECRET_KEY = "your_shared_secret_key"  
ALGORITHM = "HS256"

# 토큰 생성
payload = {
    "sub": "backend_user_001",
    "tenant_id": "tenant1",
    "email": "user@dwp.com",
    "role": "user",
    "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    "iat": datetime.now(timezone.utc),
}

token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
print(f"JWT Token for Aura-Platform:\n{token}")
```

### 4.3 발급된 토큰으로 Aura-Platform API 호출

```bash
# dwp_backend에서 발급받은 토큰
export BACKEND_TOKEN="<dwp_backend에서_발급한_토큰>"

# Aura-Platform API 호출
curl http://localhost:8000/health \
  -H "Authorization: Bearer $BACKEND_TOKEN" \
  -H "X-Tenant-ID: tenant1" \
  -v

# 성공 응답 확인:
# < HTTP/1.1 200 OK
# < X-Request-ID: <uuid>
# {
#   "status": "healthy",
#   "environment": "development"
# }
```

### 4.4 인증 실패 테스트

```bash
# 1. 토큰 없음 (401)
curl http://localhost:8000/health
# 예상: 401 Unauthorized

# 2. 잘못된 토큰 (401)
curl http://localhost:8000/health \
  -H "Authorization: Bearer invalid_token_here"
# 예상: 401 Unauthorized

# 3. Tenant ID 불일치 (403)
curl http://localhost:8000/health \
  -H "Authorization: Bearer $BACKEND_TOKEN" \
  -H "X-Tenant-ID: different_tenant"
# 예상: 403 Forbidden
```

---

## 5. Frontend 연동 테스트 (dwp_frontend)

### 5.1 Streaming 테스트 엔드포인트 추가

**`api/routes/test_routes.py` 생성**:

```python
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from api.dependencies import CurrentUser, OptionalUser
from core.llm import get_llm_client
import asyncio

router = APIRouter(prefix="/test", tags=["test"])

@router.get("/stream")
async def test_stream(user: OptionalUser = None):
    """
    스트리밍 테스트 엔드포인트
    
    React frontend에서 SSE로 실시간 응답을 받을 수 있습니다.
    """
    async def generate():
        client = get_llm_client()
        
        # 시작 메시지
        yield f"data: {{'type': 'start', 'message': 'Starting stream...'}}\n\n"
        await asyncio.sleep(0.5)
        
        # LLM 스트리밍
        prompt = "Tell me a very short story about AI in 3 sentences."
        async for chunk in client.astream(prompt):
            # SSE 형식으로 전송
            yield f"data: {{'type': 'chunk', 'content': '{chunk}'}}\n\n"
            await asyncio.sleep(0.05)  # 시각적 효과
        
        # 종료 메시지
        yield f"data: {{'type': 'end', 'message': 'Stream completed'}}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )

@router.get("/ping")
async def ping():
    """간단한 ping 엔드포인트"""
    return {"message": "pong"}
```

**`main.py`에 라우터 추가**:

```python
from api.routes.test_routes import router as test_router

app.include_router(test_router)
```

### 5.2 React Frontend 테스트 코드

**`dwp_frontend/src/test/AuraStreamingTest.tsx`**:

```typescript
import React, { useState } from 'react';

export const AuraStreamingTest: React.FC = () => {
  const [content, setContent] = useState<string>('');
  const [isStreaming, setIsStreaming] = useState(false);

  const testStreaming = async () => {
    setIsStreaming(true);
    setContent('');

    const token = localStorage.getItem('accessToken'); // dwp_backend에서 받은 토큰
    
    try {
      const response = await fetch('http://localhost:8000/test/stream', {
        headers: {
          'Authorization': `Bearer ${token}`,
          'X-Tenant-ID': 'tenant1',
        },
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) {
        throw new Error('No reader available');
      }

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const jsonStr = line.slice(6);
            try {
              const data = JSON.parse(jsonStr);
              
              if (data.type === 'chunk') {
                setContent(prev => prev + data.content);
              } else if (data.type === 'start') {
                console.log('Stream started:', data.message);
              } else if (data.type === 'end') {
                console.log('Stream ended:', data.message);
              }
            } catch (e) {
              console.error('JSON parse error:', e);
            }
          }
        }
      }
    } catch (error) {
      console.error('Streaming error:', error);
      setContent('Error: ' + error.message);
    } finally {
      setIsStreaming(false);
    }
  };

  return (
    <div style={{ padding: '20px' }}>
      <h2>Aura-Platform Streaming Test</h2>
      
      <button 
        onClick={testStreaming} 
        disabled={isStreaming}
        style={{
          padding: '10px 20px',
          marginBottom: '20px',
          cursor: isStreaming ? 'not-allowed' : 'pointer',
        }}
      >
        {isStreaming ? 'Streaming...' : 'Start Stream Test'}
      </button>

      <div style={{
        border: '1px solid #ccc',
        padding: '15px',
        minHeight: '200px',
        backgroundColor: '#f5f5f5',
        whiteSpace: 'pre-wrap',
      }}>
        {content || 'Click button to start streaming...'}
      </div>
    </div>
  );
};
```

### 5.3 curl로 Streaming 테스트

```bash
# SSE 스트리밍 테스트
curl -N http://localhost:8000/test/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1"

# 출력 예시:
# data: {'type': 'start', 'message': 'Starting stream...'}
#
# data: {'type': 'chunk', 'content': 'Once '}
#
# data: {'type': 'chunk', 'content': 'upon '}
#
# data: {'type': 'chunk', 'content': 'a '}
# ...
```

---

## 6. 문제 해결

### 6.1 Redis 연결 실패

**증상**: `Connection refused` 또는 `redis.exceptions.ConnectionError`

**해결**:

#### Docker Compose 사용 시:
```bash
# 1. Redis 컨테이너 상태 확인
cd /path/to/dwp-backend
docker-compose ps | grep redis

# 2. Redis 컨테이너가 실행 중이 아니면 시작
docker-compose up -d redis

# 3. Redis 컨테이너 로그 확인
docker-compose logs -f redis

# 4. Redis 연결 테스트
docker exec -it dwp-redis redis-cli ping
# 응답: PONG

# 5. Redis URL 확인
cat /Users/joonbinchoi/Work/dwp/aura-platform/.env | grep REDIS_URL
# 예상: REDIS_URL=redis://localhost:6379/0
```

#### 로컬 설치 시:
```bash
# 1. Redis 서버 상태 확인
brew services list | grep redis

# 2. Redis 재시작
brew services restart redis

# 3. Redis 로그 확인
tail -f /usr/local/var/log/redis.log

# 4. Redis URL 확인
echo $REDIS_URL
# 또는
cat .env | grep REDIS_URL
```

#### 공통 확인 사항:
```bash
# Redis 포트 확인
lsof -i :6379

# Redis 연결 테스트 (직접)
redis-cli -h localhost -p 6379 ping
# 응답: PONG

# 네트워크 연결 확인
telnet localhost 6379
# 또는
nc -zv localhost 6379
```

### 6.2 JWT 검증 실패

**증상**: `401 Unauthorized` 또는 `Invalid token`

**해결**:
```bash
# 1. SECRET_KEY 일치 확인
# Aura-Platform
cat /Users/joonbinchoi/Work/dwp/aura-platform/.env | grep SECRET_KEY

# dwp_backend
cat /path/to/dwp_backend/.env | grep SECRET_KEY

# 2. 토큰 디코딩 (디버깅)
python -c "
from jose import jwt
token = 'YOUR_TOKEN_HERE'
secret = 'YOUR_SECRET_KEY'
try:
    payload = jwt.decode(token, secret, algorithms=['HS256'])
    print('Payload:', payload)
except Exception as e:
    print('Error:', e)
"

# 3. 토큰 만료 확인
python -c "
from jose import jwt
from datetime import datetime, timezone
token = 'YOUR_TOKEN_HERE'
payload = jwt.decode(token, options={'verify_signature': False})
exp = datetime.fromtimestamp(payload['exp'], tz=timezone.utc)
now = datetime.now(timezone.utc)
print(f'Expires: {exp}')
print(f'Now: {now}')
print(f'Expired: {exp < now}')
"
```

### 6.3 CORS 에러

**증상**: Frontend에서 `CORS policy` 에러

**해결**:
```bash
# .env 파일 수정
nano .env

# ALLOWED_ORIGINS에 frontend URL 추가
ALLOWED_ORIGINS=["http://localhost:3000", "http://localhost:8001", "http://your-frontend-url"]

# 서버 재시작
```

### 6.4 Streaming 끊김

**증상**: 스트리밍 중간에 연결이 끊어짐

**해결**:
```bash
# 1. Nginx/프록시 타임아웃 설정 확인
# 2. Keep-alive 설정 확인
# 3. 네트워크 안정성 확인

# 로그 확인
tail -f /usr/local/var/log/uvicorn.log
```

### 6.5 Tenant ID 불일치

**증상**: `403 Forbidden - Tenant ID mismatch`

**해결**:
```bash
# JWT payload의 tenant_id 확인
python -c "
from jose import jwt
token = 'YOUR_TOKEN'
payload = jwt.decode(token, options={'verify_signature': False})
print('Tenant ID in token:', payload.get('tenant_id'))
"

# X-Tenant-ID 헤더와 일치하는지 확인
curl -v http://localhost:8000/health \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: <JWT의_tenant_id와_동일한_값>"
```

---

## 7. 통합 테스트 체크리스트

### ✅ Redis 연동
- [ ] Redis 서버 실행 확인 (`redis-cli ping`)
- [ ] RedisStore 기본 작업 테스트
- [ ] Checkpoint 저장/로드 테스트
- [ ] 대화 히스토리 저장/조회 테스트

### ✅ 독립 실행
- [ ] Aura-Platform 서버 시작
- [ ] 기본 엔드포인트 호출 (`/`, `/health`)
- [ ] API 문서 접근 (`/docs`)
- [ ] JWT 생성 및 검증

### ✅ Backend 연동
- [ ] SECRET_KEY 동기화 완료
- [ ] dwp_backend에서 JWT 발급
- [ ] 발급된 JWT로 Aura-Platform API 호출
- [ ] X-Tenant-ID 헤더 검증
- [ ] 인증 실패 시나리오 테스트 (401, 403)

### ✅ Frontend 연동
- [ ] 테스트 엔드포인트 구현 (`/test/stream`)
- [ ] React SSE 클라이언트 구현
- [ ] 실시간 스트리밍 수신 확인
- [ ] UI 업데이트 동작 확인

### ✅ 권한 시스템
- [ ] 역할별 권한 테스트 (Admin, User, Guest)
- [ ] 권한 없는 요청 403 응답 확인

---

## 8. 자동화된 통합 테스트 실행

**전체 테스트 스크립트**: `scripts/run_integration_tests.sh`

```bash
#!/bin/bash

echo "╔════════════════════════════════════════════════════════════╗"
echo "║     Aura-Platform Phase 2 Integration Tests               ║"
echo "╚════════════════════════════════════════════════════════════╝"

cd /Users/joonbinchoi/Work/dwp/aura-platform
source venv/bin/activate

# Redis 연결 확인
echo -e "\n[1/5] Checking Redis..."

# Docker Compose Redis 확인 (우선)
if docker ps | grep -q dwp-redis; then
    echo "  ✓ Redis is running (Docker Compose)"
elif docker-compose -f /path/to/dwp-backend/docker-compose.yml ps 2>/dev/null | grep -q redis; then
    echo "  ✓ Redis is running (Docker Compose)"
# 로컬 Redis 확인
elif redis-cli ping > /dev/null 2>&1; then
    echo "  ✓ Redis is running (Local)"
else
    echo "  ✗ Redis is not running"
    echo ""
    echo "  Please start Redis using one of the following methods:"
    echo "  1. Docker Compose: cd /path/to/dwp-backend && docker-compose up -d redis"
    echo "  2. Local install: brew services start redis"
    exit 1
fi

# Redis 기본 테스트
echo -e "\n[2/5] Testing Redis Store..."
python scripts/test_redis_basic.py
if [ $? -ne 0 ]; then
    echo "  ✗ Redis store test failed"
    exit 1
fi

# Checkpoint 테스트
echo -e "\n[3/5] Testing Checkpointer..."
python scripts/test_checkpoint.py
if [ $? -ne 0 ]; then
    echo "  ✗ Checkpoint test failed"
    exit 1
fi

# 대화 메모리 테스트
echo -e "\n[4/5] Testing Conversation Memory..."
python scripts/test_conversation.py
if [ $? -ne 0 ]; then
    echo "  ✗ Conversation test failed"
    exit 1
fi

# JWT 테스트
echo -e "\n[5/5] Testing JWT..."
python scripts/test_jwt_standalone.py
if [ $? -ne 0 ]; then
    echo "  ✗ JWT test failed"
    exit 1
fi

echo -e "\n╔════════════════════════════════════════════════════════════╗"
echo "║              ✅ All Integration Tests Passed!              ║"
echo "╚════════════════════════════════════════════════════════════╝"
```

**실행**:
```bash
chmod +x scripts/run_integration_tests.sh
./scripts/run_integration_tests.sh
```

---

## 9. 다음 단계

통합 테스트가 모두 통과하면:

1. ✅ **Backend JWT 연동 확인** → dwp_backend 팀과 협력
2. ✅ **Frontend Streaming 확인** → dwp_frontend 팀과 협력
3. 🚀 **Phase 3 시작** → Dev Domain 구현

---

**테스트 중 문제가 발생하면 언제든지 문의하세요!** 🙋‍♂️
