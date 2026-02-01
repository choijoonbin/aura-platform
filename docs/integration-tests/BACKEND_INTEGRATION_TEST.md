# Aura-Platform 통합 테스트 가이드 (백엔드)

> **작성일**: 2026-01-16  
> **버전**: v1.0  
> **대상**: DWP Backend 개발팀  
> **목적**: Aura-Platform과의 통합 테스트 수행 가이드

---

## 📋 목차

1. [Aura-Platform 구현 상태 요약](#aura-platform-구현-상태-요약)
2. [사전 준비사항](#사전-준비사항)
3. [백엔드 테스트 항목](#백엔드-테스트-항목)
4. [상세 테스트 시나리오](#상세-테스트-시나리오)
5. [문제 해결 가이드](#문제-해결-가이드)

---

## Aura-Platform 구현 상태 요약

### ✅ 구현 완료 사항

1. **SSE 스트리밍 API**
   - 엔드포인트: `POST /aura/test/stream`
   - Gateway 경로: `POST /api/aura/test/stream`
   - 포트: 9000
   - 이벤트 형식: `id: {event_id}\nevent: {type}\ndata: {json}`

2. **HITL 통신 시스템**
   - Redis Pub/Sub 구독 (`hitl:channel:{sessionId}`)
   - 승인 요청 저장/조회 API
   - 타임아웃: 300초

3. **인증 및 보안**
   - JWT 검증 (HS256, Unix timestamp)
   - X-Tenant-ID 헤더 검증
   - X-User-ID 헤더 검증 (JWT sub와 일치 확인)

4. **SSE 재연결 지원**
   - Last-Event-ID 헤더 처리
   - 이벤트 ID 기반 재개

---

## 사전 준비사항

### 1. 환경 확인

```bash
# Aura-Platform 서버 실행 확인
curl http://localhost:9000/health

# Redis 연결 확인 (Docker Compose 사용 시)
docker ps | grep redis

# Gateway 실행 확인
curl http://localhost:8080/api/main/health
```

### 2. JWT 토큰 생성

```bash
# dwp-auth-server에서 토큰 생성
cd dwp-backend/dwp-auth-server
python3 test_jwt_for_aura.py --token-only
```

**토큰 구조 확인**:
```json
{
  "sub": "user123",           // 사용자 ID (필수)
  "tenant_id": "tenant1",     // 테넌트 ID (필수)
  "exp": 1706152860,          // Unix timestamp (초 단위)
  "iat": 1706149260           // Unix timestamp (초 단위)
}
```

### 3. 테스트 변수 설정

```bash
# 환경 변수 설정
export TOKEN="<생성된_JWT_토큰>"
export TENANT_ID="tenant1"
export USER_ID="user123"  # JWT의 sub와 일치해야 함
export GATEWAY_URL="http://localhost:8080"
export AURA_URL="http://localhost:9000"
```

---

## 백엔드 테스트 항목

### ✅ 테스트 체크리스트

#### 1. Gateway 라우팅 테스트
- [ ] Gateway → Aura-Platform 라우팅 정상 작동
- [ ] POST 요청 전달 확인
- [ ] 헤더 전파 확인 (Authorization, X-Tenant-ID, X-User-ID 등)
- [ ] StripPrefix 필터 작동 확인

#### 2. SSE 스트리밍 테스트
- [ ] POST 요청으로 SSE 스트림 수신
- [ ] 이벤트 형식 검증 (`id:`, `event:`, `data:`)
- [ ] 이벤트 타입 확인 (start, thought, plan_step, content, end 등)
- [ ] 스트림 종료 표시 확인 (`data: [DONE]`)
- [ ] 타임아웃 설정 확인 (300초)

#### 3. 인증 및 보안 테스트
- [ ] JWT 토큰 검증
- [ ] X-Tenant-ID 헤더 검증
- [ ] X-User-ID 헤더 검증 (JWT sub와 일치)
- [ ] 인증 실패 시 401 응답
- [ ] 헤더 불일치 시 에러 처리

#### 4. HITL 통신 테스트
- [ ] HITL 승인 API 호출 (`POST /api/aura/hitl/approve/{requestId}`)
- [ ] HITL 거절 API 호출 (`POST /api/aura/hitl/reject/{requestId}`)
- [ ] Redis Pub/Sub 발행 확인
- [ ] Aura-Platform에서 신호 수신 확인
- [ ] 타임아웃 처리 확인 (300초)

#### 5. 재연결 지원 테스트
- [ ] Last-Event-ID 헤더 전파
- [ ] 재연결 시 이벤트 재개 확인

#### 6. 에러 처리 테스트
- [ ] 요청 본문 크기 제한 (256KB)
- [ ] 잘못된 요청 형식 처리
- [ ] 네트워크 오류 처리
- [ ] 타임아웃 처리

---

## 상세 테스트 시나리오

### 시나리오 1: 기본 SSE 스트리밍 테스트

**목적**: Gateway를 통한 기본 SSE 스트리밍이 정상 작동하는지 확인

**테스트 단계**:

1. **요청 전송**:
```bash
curl -N -X POST ${GATEWAY_URL}/api/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "X-User-ID: ${USER_ID}" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "prompt": "안녕하세요, 테스트입니다",
    "context": {
      "activeApp": "mail",
      "url": "http://localhost:4200/mail"
    }
  }'
```

2. **예상 결과**:
```
id: 1706149260000
event: start
data: {"type":"start","message":"Agent started","timestamp":1706149260}

id: 1706149260050
event: thought
data: {"type":"thought","thoughtType":"analysis","content":"사용자 요청을 분석 중...","timestamp":1706149260}

id: 1706149260100
event: plan_step
data: {"type":"plan_step","stepId":"step1","description":"계획 수립","status":"pending","confidence":0.8,"timestamp":1706149260}

id: 1706149260150
event: content
data: {"type":"content","content":"안녕하세요! 무엇을 도와드릴까요?","timestamp":1706149260}

id: 1706149260200
event: end
data: {"type":"end","message":"Agent finished","timestamp":1706149260}

data: [DONE]
```

3. **검증 사항**:
   - ✅ 모든 이벤트에 `id:` 라인 포함
   - ✅ 이벤트 타입이 올바르게 표시됨
   - ✅ JSON 데이터 형식이 올바름
   - ✅ 스트림 종료 표시 (`data: [DONE]`) 포함
   - ✅ 타임스탬프가 Unix timestamp (초 단위) 형식

---

### 시나리오 2: HITL 승인 프로세스 테스트

**목적**: HITL 승인 요청이 정상적으로 처리되는지 확인

**테스트 단계**:

1. **SSE 스트림 시작** (백그라운드 실행):
```bash
curl -N -X POST ${GATEWAY_URL}/api/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "X-User-ID: ${USER_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "GitHub PR을 생성해주세요",
    "context": {}
  }' > /tmp/sse_output.txt &
SSE_PID=$!
```

2. **HITL 이벤트 대기** (로그 확인):
```bash
# HITL 이벤트 확인
tail -f /tmp/sse_output.txt | grep "event: hitl"
```

3. **HITL 승인 요청 조회**:
```bash
# request_id 추출 (SSE 출력에서)
REQUEST_ID=$(grep -o '"requestId":"[^"]*"' /tmp/sse_output.txt | head -1 | cut -d'"' -f4)

# 승인 요청 조회
curl -X GET ${GATEWAY_URL}/api/aura/hitl/requests/${REQUEST_ID} \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "X-User-ID: ${USER_ID}"
```

4. **HITL 승인 API 호출**:
```bash
curl -X POST ${GATEWAY_URL}/api/aura/hitl/approve/${REQUEST_ID} \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "X-User-ID: ${USER_ID}" \
  -H "Content-Type: application/json" \
  -d '{}'
```

5. **예상 결과**:
   - ✅ 승인 API 호출 후 SSE 스트림이 계속 진행됨
   - ✅ Redis Pub/Sub을 통해 Aura-Platform에 신호 전달됨
   - ✅ Aura-Platform이 승인 신호를 수신하고 작업 계속

6. **검증 사항**:
   - ✅ HITL 이벤트가 올바른 형식으로 발행됨
   - ✅ 승인 요청이 Redis에 저장됨
   - ✅ 승인 API 호출 시 Redis Pub/Sub 발행됨
   - ✅ Aura-Platform이 신호를 수신하고 작업 재개

---

### 시나리오 3: 인증 및 보안 테스트

**목적**: 인증 및 보안 검증이 정상 작동하는지 확인

#### 3.1 JWT 토큰 검증

```bash
# 유효한 토큰으로 요청
curl -X POST ${GATEWAY_URL}/api/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test", "context": {}}'

# 예상: 200 OK 또는 SSE 스트림 시작

# 잘못된 토큰으로 요청
curl -X POST ${GATEWAY_URL}/api/aura/test/stream \
  -H "Authorization: Bearer invalid_token" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test", "context": {}}'

# 예상: 401 Unauthorized
```

#### 3.2 X-User-ID 헤더 검증

```bash
# JWT sub와 일치하는 경우
curl -X POST ${GATEWAY_URL}/api/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "X-User-ID: ${USER_ID}" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test", "context": {}}'

# 예상: 정상 작동

# JWT sub와 불일치하는 경우
curl -X POST ${GATEWAY_URL}/api/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "X-User-ID: different_user" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test", "context": {}}'

# 예상: 에러 이벤트 전송 및 요청 중단
```

#### 3.3 X-Tenant-ID 헤더 검증

```bash
# 올바른 테넌트 ID
curl -X POST ${GATEWAY_URL}/api/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test", "context": {}}'

# 예상: 정상 작동

# 잘못된 테넌트 ID
curl -X POST ${GATEWAY_URL}/api/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: wrong_tenant" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test", "context": {}}'

# 예상: 403 Forbidden 또는 에러 이벤트
```

---

### 시나리오 4: 재연결 지원 테스트

**목적**: Last-Event-ID 헤더를 통한 재연결이 정상 작동하는지 확인

**테스트 단계**:

1. **첫 번째 연결**:
```bash
curl -N -X POST ${GATEWAY_URL}/api/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "테스트",
    "context": {}
  }' > /tmp/first_connection.txt
```

2. **마지막 이벤트 ID 추출**:
```bash
LAST_EVENT_ID=$(grep "^id:" /tmp/first_connection.txt | tail -1 | cut -d' ' -f2)
echo "Last Event ID: ${LAST_EVENT_ID}"
```

3. **재연결 (Last-Event-ID 포함)**:
```bash
curl -N -X POST ${GATEWAY_URL}/api/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "Last-Event-ID: ${LAST_EVENT_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "테스트",
    "context": {},
    "thread_id": "previous_thread_id"
  }' > /tmp/reconnection.txt
```

4. **검증 사항**:
   - ✅ Last-Event-ID 헤더가 Aura-Platform으로 전파됨
   - ✅ Aura-Platform이 이벤트 ID를 읽고 다음 ID부터 시작
   - ✅ 체크포인트가 있으면 상태 복원 가능

---

### 시나리오 5: 요청 본문 크기 제한 테스트

**목적**: Gateway의 256KB 제한이 정상 작동하는지 확인

**테스트 단계**:

1. **작은 context 데이터** (정상):
```bash
curl -X POST ${GATEWAY_URL}/api/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "테스트",
    "context": {
      "activeApp": "mail",
      "url": "http://localhost:4200/mail"
    }
  }'

# 예상: 정상 작동
```

2. **큰 context 데이터** (256KB 초과):
```bash
# 큰 데이터 생성 (예: 300KB)
LARGE_DATA=$(python3 -c "print('x' * 300000)")

curl -X POST ${GATEWAY_URL}/api/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "Content-Type: application/json" \
  -d "{
    \"prompt\": \"테스트\",
    \"context\": {
      \"largeData\": \"${LARGE_DATA}\"
    }
  }"

# 예상: Gateway에서 요청 거부 또는 에러
```

---

### 시나리오 6: HITL 타임아웃 테스트

**목적**: HITL 승인 요청의 타임아웃 처리가 정상 작동하는지 확인

**테스트 단계**:

1. **HITL 요청 생성** (승인하지 않음):
```bash
curl -N -X POST ${GATEWAY_URL}/api/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "GitHub PR을 생성해주세요",
    "context": {}
  }' > /tmp/hitl_timeout.txt &
SSE_PID=$!
```

2. **HITL 이벤트 확인**:
```bash
# HITL 이벤트 대기
timeout 10 tail -f /tmp/hitl_timeout.txt | grep "event: hitl"
```

3. **300초 대기** (또는 타임아웃 시간 조정):
```bash
# 타임아웃 확인 (실제로는 300초 대기)
sleep 300
```

4. **예상 결과**:
   - ✅ 300초 후 `failed` 이벤트 전송
   - ✅ 에러 메시지: "사용자 응답 지연으로 작업이 취소되었습니다"
   - ✅ 스트림 종료

---

## 문제 해결 가이드

### 문제 1: Gateway 라우팅 실패

**증상**: `404 Not Found` 또는 연결 실패

**해결 방법**:
1. Gateway 설정 확인:
```bash
grep -r "localhost:9000" dwp-gateway/src/main/resources/
```

2. Aura-Platform 서버 실행 확인:
```bash
curl http://localhost:9000/health
```

3. Gateway 재시작:
```bash
cd dwp-gateway
./gradlew bootRun
```

### 문제 2: SSE 스트림이 시작되지 않음

**증상**: 요청 후 응답이 없음

**해결 방법**:
1. Aura-Platform 로그 확인:
```bash
# Aura-Platform 로그에서 에러 확인
tail -f /tmp/aura-platform.log
```

2. Redis 연결 확인:
```bash
docker ps | grep redis
redis-cli ping
```

3. JWT 토큰 유효성 확인:
```bash
# 토큰 만료 확인
python3 -c "from jose import jwt; import json; print(json.dumps(jwt.get_unverified_claims('${TOKEN}'), indent=2))"
```

### 문제 3: HITL 승인 신호가 전달되지 않음

**증상**: 승인 API 호출 후 작업이 계속되지 않음

**해결 방법**:
1. Redis Pub/Sub 확인:
```bash
# Redis에서 채널 확인
redis-cli PUBSUB CHANNELS "hitl:channel:*"
```

2. 백엔드 로그 확인:
```bash
# HITL API 호출 로그 확인
tail -f /tmp/dwp-backend.log | grep "hitl"
```

3. Aura-Platform HITL Manager 로그 확인:
```bash
# Aura-Platform 로그에서 HITL 관련 메시지 확인
tail -f /tmp/aura-platform.log | grep "HITL"
```

### 문제 4: 요청 본문 크기 제한 오류

**증상**: `413 Payload Too Large` 또는 요청 거부

**해결 방법**:
1. context 데이터 크기 확인:
```bash
# JSON 크기 확인
echo '{"prompt":"test","context":{...}}' | wc -c
```

2. context 데이터 최적화:
   - 불필요한 메타데이터 제거
   - 중첩 구조 단순화
   - 필요한 데이터만 포함

---

## 테스트 결과 기록

### 테스트 결과 템플릿

```markdown
## 테스트 결과

**테스트 일시**: YYYY-MM-DD HH:MM:SS
**테스트 담당자**: [이름]
**Aura-Platform 버전**: v0.3.3

### 테스트 항목별 결과

#### 1. Gateway 라우팅
- [ ] 통과
- [ ] 실패 (상세: ___________)

#### 2. SSE 스트리밍
- [ ] 통과
- [ ] 실패 (상세: ___________)

#### 3. 인증 및 보안
- [ ] 통과
- [ ] 실패 (상세: ___________)

#### 4. HITL 통신
- [ ] 통과
- [ ] 실패 (상세: ___________)

#### 5. 재연결 지원
- [ ] 통과
- [ ] 실패 (상세: ___________)

#### 6. 에러 처리
- [ ] 통과
- [ ] 실패 (상세: ___________)

### 발견된 이슈

1. [이슈 1]
   - 설명: ___________
   - 재현 방법: ___________
   - 우선순위: [High/Medium/Low]

2. [이슈 2]
   - 설명: ___________
   - 재현 방법: ___________
   - 우선순위: [High/Medium/Low]

### 추가 확인 사항

- ___________
```

---

## 참고 자료

- **Aura-Platform 문서**:
  - `docs/BACKEND_HANDOFF.md`: 백엔드 전달 문서
  - `docs/BACKEND_INTEGRATION_RESPONSE.md`: 백엔드 통합 체크리스트 응답
  - `docs/BACKEND_VERIFICATION_RESPONSE.md`: 백엔드 검증 문서 응답

- **API 엔드포인트**:
  - `POST /api/aura/test/stream`: SSE 스트리밍
  - `GET /api/aura/hitl/requests/{request_id}`: 승인 요청 조회
  - `GET /api/aura/hitl/signals/{session_id}`: 승인 신호 조회
  - `POST /api/aura/hitl/approve/{requestId}`: 승인 처리 (백엔드)
  - `POST /api/aura/hitl/reject/{requestId}`: 거절 처리 (백엔드)

---

**문서 버전**: v1.0  
**최종 업데이트**: 2026-01-16  
**담당자**: Aura-Platform 개발팀
