# 통합/협업 체크리스트

> **작성일**: 2026-01-16  
> **버전**: v1.0  
> **대상**: Aura-Platform ↔ DWP Backend ↔ DWP Frontend 통합 검증

---

## ✅ 1. 포트 충돌 방지

### Aura-Platform 설정
- ✅ **포트**: 9000 (기본값)
- ✅ **설정 위치**: `core/config.py` (`api_port: int = 9000`)
- ✅ **실행 명령**: `uvicorn main:app --host 0.0.0.0 --port 9000`

### Gateway 라우팅 확인 필요
**⚠️ 백엔드 팀 확인 필요**:
- `dwp-gateway/application.yml`에서 `/api/aura/**` 라우팅이 `http://localhost:9000`으로 설정되어 있는지 확인
- 이전 포트(8000)로 설정되어 있다면 업데이트 필요

**확인 방법**:
```yaml
# dwp-gateway/application.yml
spring:
  cloud:
    gateway:
      routes:
        - id: aura-platform
          uri: http://localhost:9000  # ✅ 9000으로 설정되어야 함
          predicates:
            - Path=/api/aura/**
```

**문서화 상태**:
- ✅ `README.md`에 포트 9000 명시
- ✅ `docs/BACKEND_HANDOFF.md`에 포트 변경 사항 기록
- ⚠️ Gateway 라우팅 설정은 백엔드 팀이 확인 필요

---

## ✅ 2. 사용자 식별자(User-ID) 일관성

### JWT 토큰 구조
**Aura-Platform이 기대하는 JWT 클레임**:
```json
{
  "sub": "user123",           // ✅ 사용자 ID (필수)
  "tenant_id": "tenant1",     // ✅ 테넌트 ID (필수)
  "email": "user@dwp.com",    // 선택
  "role": "user",             // 선택
  "exp": 1706152860,          // Unix timestamp (초 단위)
  "iat": 1706149260           // Unix timestamp (초 단위)
}
```

### 사용자 식별자 추출 로직
**Aura-Platform 구현** (`core/security/auth.py`):
```python
# JWT에서 사용자 정보 추출
def extract_user_from_token(token: str) -> User:
    payload = verify_token(token)
    return User(
        user_id=payload.sub,        # ✅ "sub" 클레임 사용
        tenant_id=payload.tenant_id,
        email=payload.email,
        role=payload.role,
    )
```

**API 엔드포인트에서 사용** (`api/dependencies.py`):
```python
# CurrentUser 의존성
user: CurrentUser  # user.user_id = JWT의 "sub" 값
```

### X-User-ID 헤더 처리
**현재 상태**:
- ⚠️ **Aura-Platform은 X-User-ID 헤더를 직접 처리하지 않음**
- JWT의 `sub` 클레임을 사용자 식별자로 사용
- HITL 승인/거절 시 백엔드에서 `X-User-ID` 헤더를 전달하지만, Aura-Platform은 JWT에서 추출한 `user_id` 사용

**백엔드와의 일관성 확인 필요**:
1. **프론트엔드**: JWT의 `sub` 또는 `userId` 추출 → 백엔드로 전달
2. **백엔드**: `X-User-ID` 헤더로 Aura-Platform에 전달 (HITL API 호출 시)
3. **Aura-Platform**: JWT의 `sub` 클레임을 사용자 식별자로 사용

**⚠️ 잠재적 문제**:
- 백엔드가 `X-User-ID` 헤더를 전달하지만, Aura-Platform은 JWT에서 직접 추출
- HITL 승인/거절 API 호출 시 백엔드의 `X-User-ID`와 Aura-Platform의 JWT `sub`가 일치해야 함

**권장 사항**:
- ✅ JWT의 `sub` 클레임을 표준 사용자 식별자로 사용 (현재 구현)
- ⚠️ 백엔드 팀과 확인: HITL API 호출 시 `X-User-ID` 헤더 값이 JWT의 `sub`와 일치하는지

---

## ✅ 3. SSE 전송 방식 (POST)

### 현재 구현
**Aura-Platform**:
- ✅ **엔드포인트**: `POST /aura/test/stream`
- ✅ **요청 본문**: `{"prompt": "...", "context": {...}}`
- ✅ **응답**: `text/event-stream` (SSE)
- ✅ **FastAPI StreamingResponse 사용**

**구현 코드** (`api/routes/aura_backend.py`):
```python
@router.post("/test/stream")
async def backend_stream(
    request: BackendStreamRequest,
    ...
):
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

### POST SSE 테스트 필요 사항
**⚠️ 확인 필요**:

1. **Gateway 라우팅**:
   - POST 요청이 Gateway를 통해 Aura-Platform으로 정상 전달되는지
   - Gateway의 POST 요청 타임아웃 설정 (SSE는 장시간 연결 유지)

2. **요청 본문 크기**:
   - `context` 객체가 큰 경우 Gateway/서버의 요청 본문 크기 제한 확인
   - FastAPI 기본 제한: 1MB (설정 가능)

3. **스트리밍 응답**:
   - Gateway가 POST 요청에 대한 SSE 응답을 버퍼링하지 않는지
   - `X-Accel-Buffering: no` 헤더가 Gateway를 통해 전달되는지

**테스트 시나리오**:
```bash
# 1. 직접 Aura-Platform 호출 (Gateway 우회)
curl -N -X POST http://localhost:9000/aura/test/stream \
  -H "Authorization: Bearer {TOKEN}" \
  -H "X-Tenant-ID: tenant1" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "테스트",
    "context": {"url": "http://localhost:4200/mail"}
  }'

# 2. Gateway를 통한 호출
curl -N -X POST http://localhost:8080/api/aura/test/stream \
  -H "Authorization: Bearer {TOKEN}" \
  -H "X-Tenant-ID: tenant1" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "테스트",
    "context": {"url": "http://localhost:4200/mail"}
  }'
```

**예상 문제점**:
- ⚠️ Gateway가 POST 요청의 SSE 응답을 버퍼링할 수 있음
- ⚠️ Gateway 타임아웃 설정이 SSE 연결 시간보다 짧을 수 있음 (현재: 300초)

---

## 📋 추가 확인 사항

### 4. 이벤트 타입 일관성
**Aura-Platform 발행 이벤트**:
- `start` - 시작 이벤트
- `thought` - 사고 과정
- `plan_step` - 계획 단계
- `plan_step_update` - 계획 단계 업데이트 (새로 추가)
- `timeline_step_update` - 타임라인 단계 업데이트 (새로 추가)
- `tool_execution` - 도구 실행
- `hitl` - 승인 요청
- `content` - 최종 결과
- `end` - 종료 이벤트
- `error` - 에러 이벤트

**프론트엔드 기대 이벤트**:
- ✅ 프론트엔드 명세 v1.0에 맞춰 모든 이벤트 타입 구현 완료

### 5. 스트림 종료 표시
**Aura-Platform 구현**:
- ✅ `data: [DONE]\n\n` 전송 (프론트엔드 요구사항)

### 6. HITL 통신 프로토콜
**Redis Pub/Sub 채널**:
- ✅ `hitl:channel:{sessionId}` - 신호 수신
- ✅ `hitl:request:{requestId}` - 승인 요청 저장
- ✅ `hitl:session:{sessionId}` - 세션 정보 저장
- ✅ `hitl:signal:{sessionId}` - 승인 신호 저장 (백엔드에서 발행)

**신호 형식**:
- ✅ Unix timestamp (초 단위 정수) 사용
- ✅ JSON 형식

---

## 🔧 Aura-Platform에서 보완 필요 사항

### 1. X-User-ID 헤더 처리 (선택사항)
**현재**: JWT의 `sub` 클레임만 사용  
**권장**: `X-User-ID` 헤더가 있으면 우선 사용, 없으면 JWT `sub` 사용

**구현 예시**:
```python
# api/routes/aura_backend.py
@router.post("/test/stream")
async def backend_stream(
    request: BackendStreamRequest,
    user: CurrentUser,
    x_user_id: str | None = Header(None, alias="X-User-ID"),
    ...
):
    # X-User-ID 헤더가 있으면 우선 사용
    effective_user_id = x_user_id or user.user_id
    ...
```

**⚠️ 주의**: JWT 검증은 여전히 필수이며, `X-User-ID`는 추가 식별자로만 사용

### 2. Gateway 타임아웃 문서화
**현재 상태**:
- ✅ Aura-Platform HITL 대기 타임아웃: 300초
- ⚠️ Gateway 타임아웃 설정은 백엔드 팀 확인 필요

**문서화 필요**:
- Gateway SSE 타임아웃 설정 값
- Gateway POST 요청 본문 크기 제한

### 3. 에러 처리 개선
**현재**: 기본 에러 이벤트 발행  
**권장**: Gateway 연결 끊김, 타임아웃 등 구체적인 에러 타입 구분

---

## ✅ 검증 완료 사항

1. ✅ 포트 9000 설정 완료
2. ✅ POST SSE 엔드포인트 구현 완료
3. ✅ JWT `sub` 클레임 사용 확인
4. ✅ 새로운 이벤트 타입 구현 완료
5. ✅ 스트림 종료 표시 (`[DONE]`) 구현 완료
6. ✅ HITL 통신 프로토콜 구현 완료

---

## ⚠️ 백엔드 팀 확인 필요 사항

1. **Gateway 라우팅**:
   - `/api/aura/**` → `http://localhost:9000` 설정 확인
   - POST 요청 라우팅 정상 작동 확인

2. **Gateway 타임아웃**:
   - SSE 연결 타임아웃: 300초 이상 설정
   - POST 요청 본문 크기 제한 확인

3. **X-User-ID 헤더**:
   - HITL API 호출 시 `X-User-ID` 헤더 값이 JWT의 `sub`와 일치하는지 확인

---

## ⚠️ 프론트엔드 팀 확인 필요 사항

1. **POST SSE 요청**:
   - `POST /api/aura/test/stream` 엔드포인트 사용
   - 요청 본문 형식: `{"prompt": "...", "context": {...}}`

2. **이벤트 타입**:
   - 새로운 이벤트 타입 (`plan_step_update`, `timeline_step_update`) 처리
   - 스트림 종료 표시 (`data: [DONE]`) 처리

3. **에러 처리**:
   - SSE 연결 끊김 시 재연결 로직
   - 타임아웃 에러 처리

---

## 📞 문의

통합 과정에서 문제가 발생하거나 추가 확인이 필요한 경우:
- **Aura-Platform 팀**: 이슈 트래커 또는 개발팀에 문의
- **백엔드 팀**: Gateway 설정 및 라우팅 관련 문의
- **프론트엔드 팀**: API 사용 및 이벤트 처리 관련 문의

---

**문서 버전**: v1.0  
**최종 업데이트**: 2026-01-16
