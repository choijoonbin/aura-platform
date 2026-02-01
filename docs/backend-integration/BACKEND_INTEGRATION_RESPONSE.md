# 백엔드 통합 체크리스트 응답

> **작성일**: 2026-01-16  
> **버전**: v1.0  
> **대상**: Aura-Platform 개발팀  
> **출처**: DWP Backend Team

이 문서는 백엔드 팀에서 전달한 `AURA_PLATFORM_INTEGRATION_RESPONSE.md`의 내용을 Aura-Platform에 반영한 것입니다.

---

## ✅ 백엔드 확인 완료 사항

### 1. 포트 충돌 방지

**✅ 확인 완료**: Gateway의 `application.yml`에서 Aura-Platform 라우팅이 `http://localhost:9000`으로 설정되어 있습니다.

**라우팅 설정**:
```yaml
spring:
  cloud:
    gateway:
      routes:
        - id: aura-platform
          uri: ${AURA_PLATFORM_URI:http://localhost:9000}  # ✅ 포트 9000 확정
          predicates:
            - Path=/api/aura/**
          filters:
            - StripPrefix=1  # /api/aura/** → /aura/**로 변환
```

**✅ 상태**: 모든 설정 파일에서 포트 9000으로 올바르게 설정됨

---

### 2. 사용자 식별자(User-ID) 일관성

#### 2.1 JWT 토큰 구조

**✅ 확인 완료**: 백엔드는 JWT의 `sub` 클레임을 사용자 식별자로 사용합니다.

**JWT Payload 구조** (백엔드 기대 형식):
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

**✅ 상태**: Aura-Platform과 백엔드 모두 JWT의 `sub` 클레임을 사용하므로 일관성 유지됨

#### 2.2 X-User-ID 헤더 처리

**✅ 확인 완료**: 백엔드는 `X-User-ID` 헤더를 처리하고 검증합니다.

**백엔드 검증 로직**:
- HITL API 호출 시 JWT의 `sub`와 `X-User-ID` 헤더 값이 **반드시 일치**해야 함
- 불일치 시 `403 Forbidden` 오류 발생

**Aura-Platform 구현**:
- ✅ `X-User-ID` 헤더 읽기 추가
- ✅ JWT `sub`와 `X-User-ID` 일치 검증 로직 추가
- ✅ 불일치 시 에러 이벤트 전송 및 요청 중단

**✅ 상태**: 백엔드와 동일한 검증 로직 적용 완료

---

### 3. SSE 전송 방식 (POST)

#### 3.1 Gateway 라우팅

**✅ 확인 완료**: Gateway가 POST 요청을 Aura-Platform으로 정상 전달합니다.

**✅ 상태**: POST 요청 라우팅 정상 작동 확인됨

#### 3.2 Gateway 타임아웃 설정

**✅ 확인 완료**: Gateway의 SSE 연결 타임아웃이 300초로 설정되어 있습니다.

**타임아웃 설정**:
```yaml
spring:
  cloud:
    gateway:
      httpclient:
        response-timeout: 300s  # ✅ 5분 (300초) - Aura-Platform HITL 대기 타임아웃과 일치
        connect-timeout: 10000  # 10초
```

**✅ 상태**: Aura-Platform의 HITL 대기 타임아웃(300초)과 일치하므로 문제없음

#### 3.3 요청 본문 크기 제한

**⚠️ 중요**: Gateway의 요청 본문 크기 제한은 **256KB** (기본값)입니다.

**현재 제한**:
- **Spring Cloud Gateway (Netty)**: **256KB** (262,144 bytes) - 기본값
- **FastAPI**: **1MB** (기본값, 설정 가능)

**⚠️ 주의사항**:
- `context` 객체가 256KB를 초과하는 경우 Gateway에서 요청이 거부될 수 있습니다
- FastAPI는 1MB까지 허용하지만, Gateway를 통과하지 못할 수 있습니다

**권장 조치**:
1. **일반적인 사용**: `context` 데이터를 **256KB 이하로 유지** (권장)
   - 필요한 데이터만 선별하여 전송
   - 불필요한 메타데이터 제거
   - 중첩된 객체 구조 최적화
2. **큰 데이터 필요 시**: 
   - 백엔드 팀과 별도 논의 후 Gateway 설정 조정
   - 또는 `context` 데이터를 압축하여 전송

**✅ 권장**: 
- 현재는 기본값(256KB) 유지
- `context` 데이터를 최적화하여 256KB 이하로 유지
- 큰 데이터가 반드시 필요한 경우, 백엔드 팀과 별도 논의 필요

#### 3.4 스트리밍 응답 버퍼링

**✅ 확인 완료**: Gateway가 POST 요청에 대한 SSE 응답을 버퍼링하지 않습니다.

**✅ 상태**: 스트리밍 응답이 버퍼링되지 않도록 보장됨

---

### 4. SSE 이벤트 ID 포함

**✅ 확인 완료**: Gateway의 `SseReconnectionFilter`가 SSE 응답에 `id:` 라인을 자동으로 추가합니다.

**Aura-Platform 구현**:
- ✅ 모든 SSE 이벤트에 `id:` 라인 포함
- ✅ Unix timestamp (밀리초) 기반 순차적 ID 생성
- ✅ `Last-Event-ID` 헤더 처리 및 재연결 지원

**✅ 상태**: SSE 재연결 지원 완료

---

## ✅ Aura-Platform 구현 완료 사항

### 1. X-User-ID 헤더 검증

**구현 위치**: `api/routes/aura_backend.py`

**구현 내용**:
```python
@router.post("/test/stream")
async def backend_stream(
    ...
    x_user_id: str | None = Header(None, alias="X-User-ID"),
):
    async def event_generator():
        # X-User-ID 헤더 검증 (백엔드 요구사항: JWT sub와 일치해야 함)
        if x_user_id and x_user_id != user.user_id:
            error_data = {
                "type": "error",
                "error": "User ID mismatch",
                "errorType": "ValidationError",
                "message": f"X-User-ID header ({x_user_id}) does not match JWT sub claim ({user.user_id})",
            }
            yield format_sse_event("error", error_data, "0")
            return
        ...
```

**✅ 상태**: 백엔드와 동일한 검증 로직 적용 완료

### 2. SSE 이벤트 ID 포함

**구현 위치**: `api/routes/aura_backend.py`의 `format_sse_event` 함수

**구현 내용**:
- 모든 SSE 이벤트에 `id: {event_id}` 라인 포함
- Unix timestamp (밀리초) 기반 순차적 ID 생성
- `Last-Event-ID` 헤더 처리 및 재연결 지원

**✅ 상태**: 구현 완료

### 3. 요청 본문 크기 제한 문서화

**⚠️ 주의사항**:
- Gateway 기본 제한: **256KB**
- `context` 데이터를 256KB 이하로 유지 권장
- 큰 데이터가 필요한 경우 백엔드 팀과 별도 논의 필요

**✅ 상태**: 문서화 완료

---

## 📋 최종 확인 체크리스트

### 백엔드 확인 완료 사항

- [x] **포트 9000 라우팅**: Gateway의 `application.yml`에서 `http://localhost:9000` 설정 확인
- [x] **POST 요청 라우팅**: POST `/api/aura/test/stream` 요청이 정상 작동하는지 확인
- [x] **SSE 타임아웃**: 300초로 설정되어 Aura-Platform HITL 타임아웃과 일치
- [x] **X-User-ID 헤더**: JWT `sub`와 일치 검증 구현 완료 (백엔드)
- [x] **스트리밍 응답**: 버퍼링되지 않도록 보장됨
- [x] **Last-Event-ID 헤더**: Aura-Platform으로 전파됨
- [x] **SSE 이벤트 ID**: Gateway의 `SseReconnectionFilter`로 자동 추가

### Aura-Platform 구현 완료 사항

- [x] **SSE 이벤트 ID**: Aura-Platform에서 `id:` 라인을 포함하는지 확인 ✅
- [x] **Last-Event-ID 헤더**: 재연결 시 `Last-Event-ID` 헤더를 올바르게 처리하는지 확인 ✅
- [x] **X-User-ID 헤더**: JWT `sub`와 `X-User-ID` 일치 검증 로직 추가 ✅
- [x] **요청 본문 크기**: Gateway의 256KB 제한 문서화 및 주의사항 명시 ✅

---

## 🔧 테스트 시나리오

### 시나리오 1: 기본 POST SSE 연결
```bash
# Gateway를 통한 접근
curl -N -X POST http://localhost:8080/api/aura/test/stream \
  -H "Authorization: Bearer {TOKEN}" \
  -H "X-Tenant-ID: tenant1" \
  -H "X-User-ID: user123" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "prompt": "테스트",
    "context": {"url": "http://localhost:4200/mail"}
  }'
```

### 시나리오 2: 재연결 테스트
```bash
# Last-Event-ID 헤더와 함께 재연결
curl -N -X POST http://localhost:8080/api/aura/test/stream \
  -H "Authorization: Bearer {TOKEN}" \
  -H "X-Tenant-ID: tenant1" \
  -H "X-User-ID: user123" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "Last-Event-ID: 1706156400123" \
  -d '{
    "prompt": "테스트",
    "context": {"url": "http://localhost:4200/mail"}
  }'
```

### 시나리오 3: X-User-ID 검증 테스트
```bash
# JWT sub와 일치하는 경우 (정상)
curl -N -X POST http://localhost:8080/api/aura/test/stream \
  -H "Authorization: Bearer {TOKEN}" \
  -H "X-Tenant-ID: tenant1" \
  -H "X-User-ID: user123" \  # JWT의 sub와 일치
  -H "Content-Type: application/json" \
  -d '{"prompt": "테스트", "context": {}}'

# JWT sub와 불일치하는 경우 (에러 발생)
curl -N -X POST http://localhost:8080/api/aura/test/stream \
  -H "Authorization: Bearer {TOKEN}" \
  -H "X-Tenant-ID: tenant1" \
  -H "X-User-ID: different_user" \  # JWT의 sub와 불일치
  -H "Content-Type: application/json" \
  -d '{"prompt": "테스트", "context": {}}'
```

---

## 📝 요청 본문 크기 제한 가이드

### Gateway 제한: 256KB

**권장 사항**:
1. **필수 데이터만 전송**: `context` 객체에 필요한 데이터만 포함
2. **메타데이터 최적화**: 불필요한 중첩 구조 제거
3. **데이터 압축**: 큰 데이터가 필요한 경우 압축 고려

**예시: 최적화된 context 구조**:
```json
{
  "prompt": "사용자 질문",
  "context": {
    "activeApp": "mail",           // 필수
    "selectedItemIds": [1, 2, 3],  // 필수
    "url": "http://localhost:4200/mail",  // 필수
    "path": "/mail",               // 선택
    "title": "메일 인박스",         // 선택
    "itemId": "msg-123"            // 선택
    // 불필요한 큰 메타데이터 제거
  }
}
```

---

## 📞 문의 사항

통합 과정에서 문제가 발생하면 다음을 확인하세요:

1. **포트 충돌**: `lsof -i :9000`으로 포트 사용 확인
2. **Gateway 로그**: Gateway 로그에서 라우팅 및 헤더 전파 확인
3. **요청 본문 크기**: 256KB 제한 초과 시 Gateway 설정 조정 필요
4. **SSE 연결**: 타임아웃(300초) 내에 응답이 완료되는지 확인
5. **X-User-ID 검증**: JWT `sub`와 `X-User-ID` 헤더 값이 일치하는지 확인

---

**최종 업데이트**: 2026-01-16  
**원본 문서**: `dwp-backend/docs/AURA_PLATFORM_INTEGRATION_RESPONSE.md`
