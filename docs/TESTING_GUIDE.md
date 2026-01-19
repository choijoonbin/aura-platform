# Aura-Platform 테스트 가이드

> **작성일**: 2026-01-16  
> **목적**: Aura-Platform API 테스트 방법 안내

---

## 📋 테스트 방법 개요

Aura-Platform API를 테스트하는 방법은 **3가지**가 있습니다:

1. **직접 테스트** (Aura-Platform에 직접 요청)
2. **Gateway를 통한 테스트** (백엔드 Gateway 경유)
3. **프론트엔드에서 테스트** (실제 사용 시나리오)

---

## 🔐 인증 요구사항

**모든 `/aura/**` 엔드포인트는 JWT 인증이 필요합니다.**

필수 헤더:
- `Authorization: Bearer {JWT_TOKEN}`
- `X-Tenant-ID: {tenant_id}`

---

## 방법 1: 직접 테스트 (Aura-Platform에 직접 요청)

### 장점
- 빠른 테스트
- Gateway 없이 직접 검증 가능
- 디버깅 용이

### 단점
- 실제 운영 환경과 다를 수 있음
- Gateway 라우팅 검증 불가

### 테스트 방법

#### 1. JWT 토큰 생성

```bash
cd /Users/joonbinchoi/Work/dwp/aura-platform
python3 -c "
from core.security.auth import create_token
token = create_token(
    user_id='test_user_001',
    tenant_id='tenant1',
    email='test@dwp.com',
    role='user'
)
print(token)
"
```

#### 2. API 호출

```bash
# 환경 변수 설정
export TOKEN="<위에서_생성한_JWT_토큰>"
export TENANT_ID="tenant1"

# SSE 스트리밍 테스트
curl -N -X POST http://localhost:9000/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "안녕하세요",
    "context": {
      "activeApp": "mail"
    }
  }'
```

**예상 응답**:
```
id: 1
event: start
data: {"type": "start", "message": "Agent started", "timestamp": 1768521256}

id: 2
event: thought
data: {"type": "thought", "data": {...}}

...

data: [DONE]
```

---

## 방법 2: Gateway를 통한 테스트 (백엔드 Gateway 경유)

### 장점
- 실제 운영 환경과 동일
- Gateway 라우팅 검증 가능
- 헤더 전파 검증 가능

### 단점
- 백엔드 Gateway가 실행 중이어야 함
- 설정이 복잡할 수 있음

### 사전 준비

1. **백엔드 Gateway 실행 확인**
   ```bash
   # Gateway가 포트 8080에서 실행 중인지 확인
   curl http://localhost:8080/api/main/health
   ```

2. **JWT 토큰 생성** (백엔드에서 발급받은 토큰 사용 권장)

### 테스트 방법

```bash
# Gateway를 통한 접근
curl -N -X POST http://localhost:8080/api/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "X-User-ID: test_user_001" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "prompt": "테스트",
    "context": {
      "activeApp": "mail",
      "url": "http://localhost:4200/mail"
    }
  }'
```

**주의사항**:
- Gateway 경로: `/api/aura/test/stream` (Aura-Platform의 `/aura/test/stream`로 라우팅됨)
- `X-User-ID` 헤더는 JWT의 `sub`와 일치해야 함

---

## 방법 3: 프론트엔드에서 테스트 (실제 사용 시나리오)

### 장점
- 실제 사용자 시나리오와 동일
- UI/UX 검증 가능
- 전체 플로우 검증 가능

### 단점
- 프론트엔드 개발이 완료되어야 함
- 디버깅이 복잡할 수 있음

### 테스트 방법

프론트엔드에서 다음 API를 호출:

```typescript
// 프론트엔드 예시 코드
const response = await fetch('http://localhost:8080/api/aura/test/stream', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${jwtToken}`,
    'X-Tenant-ID': tenantId,
    'X-User-ID': userId,  // JWT의 sub와 일치해야 함
    'Content-Type': 'application/json',
    'Accept': 'text/event-stream',
  },
  body: JSON.stringify({
    prompt: '사용자 질문',
    context: {
      activeApp: 'mail',
      selectedItemIds: [1, 2, 3],
      url: window.location.href,
      path: window.location.pathname,
      title: document.title,
    },
  }),
});

// SSE 스트림 읽기
const reader = response.body?.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  
  const chunk = decoder.decode(value);
  // SSE 이벤트 파싱 및 처리
  console.log(chunk);
}
```

---

## ⚠️ 자주 발생하는 오류

### 오류 1: 401 Unauthorized

**증상**:
```
WARNING - Missing Authorization header: /aura/test/stream
401 Unauthorized
```

**원인**:
- `Authorization` 헤더가 없음
- JWT 토큰이 유효하지 않음
- JWT 토큰이 만료됨

**해결 방법**:
1. `Authorization: Bearer {TOKEN}` 헤더 추가
2. 유효한 JWT 토큰 생성
3. 토큰 만료 시간 확인

**테스트**:
```bash
# JWT 토큰 생성
python3 -c "
from core.security.auth import create_token
token = create_token(
    user_id='test_user_001',
    tenant_id='tenant1',
    email='test@dwp.com',
    role='user'
)
print('TOKEN=' + token)
"

# 토큰으로 테스트
curl -X POST http://localhost:9000/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: tenant1" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "테스트", "context": {}}'
```

---

### 오류 2: 403 Forbidden

**증상**:
```
403 Forbidden
User ID mismatch
```

**원인**:
- `X-User-ID` 헤더 값이 JWT의 `sub`와 일치하지 않음

**해결 방법**:
- `X-User-ID` 헤더 값을 JWT의 `sub`와 동일하게 설정

**테스트**:
```bash
# JWT 토큰에서 sub 확인
python3 -c "
from core.security.auth import verify_token, extract_bearer_token
token = 'YOUR_TOKEN'
payload = verify_token(token)
print(f'User ID (sub): {payload.user_id}')
"

# 올바른 X-User-ID 헤더 사용
curl -X POST http://localhost:9000/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: tenant1" \
  -H "X-User-ID: test_user_001" \  # JWT의 sub와 일치
  -H "Content-Type: application/json" \
  -d '{"prompt": "테스트", "context": {}}'
```

---

### 오류 3: ValidationError (Context data too large)

**증상**:
```
ValidationError: Context data size (300018 bytes) exceeds Gateway limit (262144 bytes)
```

**원인**:
- `context` 데이터가 256KB를 초과함

**해결 방법**:
- `context` 데이터를 256KB 이하로 최적화
- 불필요한 메타데이터 제거

**테스트**:
```bash
# 작은 context 데이터 사용
curl -X POST http://localhost:9000/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: tenant1" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "테스트",
    "context": {
      "activeApp": "mail",
      "url": "http://localhost:4200/mail"
    }
  }'
```

---

## 📝 테스트 체크리스트

### 기본 테스트

- [ ] JWT 토큰 생성 성공
- [ ] Authorization 헤더 포함
- [ ] X-Tenant-ID 헤더 포함
- [ ] POST 요청 성공 (200 OK 또는 SSE 스트림 시작)
- [ ] SSE 이벤트 수신 (`start`, `thought`, `content` 등)
- [ ] 종료 플래그 수신 (`data: [DONE]`)

### 고급 테스트

- [ ] X-User-ID 헤더 검증 (JWT sub와 일치)
- [ ] Last-Event-ID 헤더 처리 (재연결)
- [ ] Context 데이터 크기 검증 (256KB 이하)
- [ ] Gateway를 통한 라우팅 (포트 8080)
- [ ] HITL 이벤트 발행 및 승인 프로세스

---

## 🚀 빠른 테스트 스크립트

### 스크립트 1: 기본 SSE 스트리밍 테스트

```bash
#!/bin/bash
# scripts/test_sse_basic.sh

cd /Users/joonbinchoi/Work/dwp/aura-platform

# JWT 토큰 생성
TOKEN=$(python3 -c "
from core.security.auth import create_token
print(create_token(
    user_id='test_user_001',
    tenant_id='tenant1',
    email='test@dwp.com',
    role='user'
))
")

# SSE 스트리밍 테스트
curl -N -X POST http://localhost:9000/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: tenant1" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "안녕하세요",
    "context": {
      "activeApp": "mail"
    }
  }'
```

### 스크립트 2: Gateway를 통한 테스트

```bash
#!/bin/bash
# scripts/test_sse_gateway.sh

# Gateway URL
GATEWAY_URL="http://localhost:8080"

# JWT 토큰 (백엔드에서 발급받은 토큰 사용)
TOKEN="YOUR_BACKEND_JWT_TOKEN"
TENANT_ID="tenant1"
USER_ID="test_user_001"

# Gateway를 통한 SSE 스트리밍 테스트
curl -N -X POST ${GATEWAY_URL}/api/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "X-User-ID: ${USER_ID}" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "prompt": "테스트",
    "context": {
      "activeApp": "mail",
      "url": "http://localhost:4200/mail"
    }
  }'
```

---

## 📞 문제 해결

### 문제 1: Authorization 헤더가 없어서 401 오류 발생

**해결 방법**:
1. JWT 토큰 생성
2. `Authorization: Bearer {TOKEN}` 헤더 추가
3. `X-Tenant-ID` 헤더 추가

### 문제 2: 프론트엔드에서 테스트할 때 CORS 오류 발생

**해결 방법**:
1. Aura-Platform의 CORS 설정 확인 (`main.py`)
2. 프론트엔드 Origin이 `allowed_origins`에 포함되어 있는지 확인
3. Gateway를 통한 접근 사용 (권장)

### 문제 3: Gateway를 통한 접근 시 라우팅 오류

**해결 방법**:
1. Gateway가 실행 중인지 확인
2. Gateway의 `application.yml`에서 Aura-Platform 라우팅 확인
3. Aura-Platform이 포트 9000에서 실행 중인지 확인

---

## ✅ 권장 테스트 순서

1. **직접 테스트** (Aura-Platform에 직접 요청)
   - 빠른 검증
   - 기본 기능 확인

2. **Gateway를 통한 테스트** (백엔드 Gateway 경유)
   - 실제 운영 환경 검증
   - 라우팅 및 헤더 전파 확인

3. **프론트엔드에서 테스트** (실제 사용 시나리오)
   - 전체 플로우 검증
   - UI/UX 확인

---

**최종 업데이트**: 2026-01-16  
**담당자**: Aura-Platform 개발팀
