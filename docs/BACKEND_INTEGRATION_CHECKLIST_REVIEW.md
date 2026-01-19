# 백엔드 통합 체크리스트 응답 검토 결과

> **작성일**: 2026-01-16  
> **대상**: Aura-Platform 개발팀  
> **목적**: 백엔드 팀의 통합 체크리스트 응답 문서 검토 및 Aura-Platform 확인 사항 점검

---

## 📋 백엔드 확인 완료 사항 (참고)

### 1. 포트 충돌 방지 ✅
- Gateway 라우팅: `http://localhost:9000` 설정 확인 완료
- **Aura-Platform 상태**: 포트 9000 사용 중 ✅

### 2. 사용자 식별자 일관성 ✅
- JWT `sub` 클레임 사용 확인
- `X-User-ID` 헤더 검증 구현 완료
- **Aura-Platform 상태**: JWT `sub` 사용 및 `X-User-ID` 검증 구현 완료 ✅

### 3. SSE 전송 방식 (POST) ✅
- POST 요청 라우팅 정상 작동
- SSE 타임아웃: 300초 설정
- 스트리밍 응답 버퍼링 없음
- **Aura-Platform 상태**: POST 엔드포인트 구현 완료 ✅

### 4. SSE 이벤트 ID 포함 ✅
- Gateway의 `SseReconnectionFilter`가 자동 추가
- `Last-Event-ID` 헤더 전파
- **Aura-Platform 상태**: `id:` 라인 포함 및 `Last-Event-ID` 처리 구현 완료 ✅

---

## ⚠️ Aura-Platform 확인 필요 사항

### 1. X-User-ID 헤더 검증 ✅ (이미 구현됨)

**백엔드 요구사항**:
- HITL API 호출 시 `X-User-ID` 헤더 값이 JWT의 `sub`와 일치해야 함
- 불일치 시 `403 Forbidden` 오류 발생

**Aura-Platform 현재 구현**:
```python
# api/routes/aura_backend.py (129-143번 라인)
if x_user_id and x_user_id != user.user_id:
    logger.warning(
        f"User ID mismatch: JWT sub={user.user_id}, X-User-ID header={x_user_id}"
    )
    error_data = {
        "type": "error",
        "error": "User ID mismatch",
        "errorType": "ValidationError",
        "message": f"X-User-ID header ({x_user_id}) does not match JWT sub claim ({user.user_id})",
        "timestamp": int(datetime.utcnow().timestamp()),
    }
    yield format_sse_event("error", error_data, "0")
    yield "data: [DONE]\n\n"
    return
```

**✅ 상태**: 백엔드와 동일한 검증 로직 적용 완료

**권장 사항**:
- 현재 구현 유지 (JWT `sub` 사용) - 보안상 더 안전
- 백엔드와 동일한 검증 로직이므로 일관성 유지됨

---

### 2. SSE 이벤트 ID 포함 ✅ (이미 구현됨)

**백엔드 요구사항**:
- Aura-Platform에서 `id:` 라인을 직접 포함하는 것이 권장됨
- Gateway의 `SseReconnectionFilter`가 자동으로 추가하지만, Aura-Platform에서 직접 포함 권장

**Aura-Platform 현재 구현**:
```python
# api/routes/aura_backend.py (53-88번 라인)
def format_sse_event(event_type: str, data: dict[str, Any], event_id: str | None = None) -> str:
    if event_id is None:
        # Unix timestamp (밀리초)를 이벤트 ID로 사용
        event_id = str(int(datetime.utcnow().timestamp() * 1000))
    
    # ... datetime 변환 로직 ...
    
    return f"id: {event_id}\nevent: {event_type}\ndata: {json.dumps(converted_data, ensure_ascii=False)}\n\n"
```

**✅ 상태**: 모든 SSE 이벤트에 `id:` 라인 포함 구현 완료

**Last-Event-ID 헤더 처리**:
```python
# api/routes/aura_backend.py (136-143번 라인)
event_id_counter = 0
if last_event_id:
    try:
        # Last-Event-ID가 있으면 해당 지점부터 재개
        last_id = int(last_event_id)
        event_id_counter = last_id + 1
        logger.info(f"Resuming from event ID: {last_event_id}")
    except (ValueError, TypeError):
        logger.warning(f"Invalid Last-Event-ID: {last_event_id}, starting from 0")
```

**✅ 상태**: `Last-Event-ID` 헤더 처리 및 재연결 지원 구현 완료

---

### 3. 요청 본문 크기 제한 ⚠️ (검증 로직 추가 필요)

**백엔드 요구사항**:
- Gateway 기본 제한: **256KB** (262,144 bytes)
- `context` 객체가 256KB를 초과하는 경우 Gateway에서 요청이 거부될 수 있음
- FastAPI는 1MB까지 허용하지만, Gateway를 통과하지 못할 수 있음

**Aura-Platform 현재 상태**:
- ❌ `context` 데이터 크기 검증 로직 없음
- ❌ 요청 본문 크기 제한 검증 없음

**권장 조치**:
1. **요청 본문 크기 검증 추가**
   - `BackendStreamRequest` 모델에 크기 검증 추가
   - 또는 엔드포인트에서 요청 본문 크기 확인

2. **context 데이터 크기 제한**
   - `context` 객체 크기를 256KB 이하로 제한
   - 초과 시 명확한 에러 메시지 반환

3. **문서화**
   - `context` 데이터 최적화 가이드 제공
   - 권장 데이터 구조 문서화

---

## 🔧 구현 필요 사항

### 1. 요청 본문 크기 검증 추가

**구현 위치**: `api/routes/aura_backend.py`

**구현 내용**:
```python
# 요청 본문 크기 제한 (256KB)
MAX_REQUEST_BODY_SIZE = 256 * 1024  # 256KB

@router.post("/test/stream")
async def backend_stream(
    request: BackendStreamRequest,
    ...
):
    async def event_generator():
        # 요청 본문 크기 검증
        import sys
        request_size = sys.getsizeof(request.model_dump_json())
        if request_size > MAX_REQUEST_BODY_SIZE:
            error_data = {
                "type": "error",
                "error": "Request body too large",
                "errorType": "PayloadTooLargeError",
                "message": f"Request body size ({request_size} bytes) exceeds Gateway limit (256KB). Please optimize context data.",
                "timestamp": int(datetime.utcnow().timestamp()),
            }
            yield format_sse_event("error", error_data, "0")
            yield "data: [DONE]\n\n"
            return
        
        # context 데이터 크기 검증
        context_size = sys.getsizeof(json.dumps(request.context or {}))
        if context_size > MAX_REQUEST_BODY_SIZE:
            error_data = {
                "type": "error",
                "error": "Context data too large",
                "errorType": "PayloadTooLargeError",
                "message": f"Context data size ({context_size} bytes) exceeds Gateway limit (256KB). Please optimize context data.",
                "timestamp": int(datetime.utcnow().timestamp()),
            }
            yield format_sse_event("error", error_data, "0")
            yield "data: [DONE]\n\n"
            return
        
        # ... 기존 로직 ...
```

**또는 Pydantic 모델에서 검증**:
```python
from pydantic import field_validator

class BackendStreamRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="사용자 프롬프트")
    context: dict[str, Any] = Field(default_factory=dict, description="컨텍스트 정보")
    thread_id: str | None = Field(default=None, description="스레드 ID (선택)")
    
    @field_validator('context')
    @classmethod
    def validate_context_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        """context 데이터 크기 검증 (256KB 제한)"""
        import json
        context_json = json.dumps(v)
        context_size = len(context_json.encode('utf-8'))
        
        if context_size > 256 * 1024:  # 256KB
            raise ValueError(
                f"Context data size ({context_size} bytes) exceeds Gateway limit (256KB). "
                "Please optimize context data."
            )
        return v
```

---

### 2. 문서화 업데이트

**문서 위치**: `docs/BACKEND_INTEGRATION_RESPONSE.md` 또는 새 문서 생성

**추가 내용**:
- 요청 본문 크기 제한 (256KB)
- `context` 데이터 최적화 가이드
- 권장 데이터 구조 예시

---

## ✅ 최종 확인 체크리스트

### Aura-Platform 구현 완료 사항

- [x] **포트 9000 사용**: Aura-Platform이 포트 9000에서 실행 중
- [x] **POST 엔드포인트**: `POST /aura/test/stream` 구현 완료
- [x] **X-User-ID 헤더 검증**: JWT `sub`와 일치 검증 구현 완료
- [x] **SSE 이벤트 ID 포함**: 모든 이벤트에 `id:` 라인 포함
- [x] **Last-Event-ID 헤더 처리**: 재연결 지원 구현 완료
- [x] **datetime 직렬화**: Unix timestamp로 변환 구현 완료
- [x] **종료 플래그**: `data: [DONE]` 전송 구현 완료

### Aura-Platform 추가 구현 필요 사항

- [ ] **요청 본문 크기 검증**: `context` 데이터가 256KB 이하인지 검증
  - ⚠️ Gateway 기본 제한: 256KB
  - 권장: 요청 본문 크기 검증 로직 추가
  - 권장: `context` 데이터 크기 검증 로직 추가
  - 권장: 초과 시 명확한 에러 메시지 반환

- [ ] **문서화**: 요청 본문 크기 제한 및 `context` 데이터 최적화 가이드 추가
  - Gateway 제한: 256KB
  - 권장 데이터 구조 예시
  - 최적화 방법 가이드

---

## 📝 권장 사항

### 1. 요청 본문 크기 검증 추가 (우선순위: High)

**이유**:
- Gateway에서 256KB 초과 요청이 거부될 수 있음
- 사전 검증으로 명확한 에러 메시지 제공 가능
- 사용자 경험 개선

**구현 방법**:
- Pydantic 모델에 `field_validator` 추가
- 또는 엔드포인트에서 요청 본문 크기 확인

### 2. context 데이터 최적화 가이드 작성 (우선순위: Medium)

**이유**:
- 프론트엔드 개발자가 `context` 데이터를 효율적으로 구성할 수 있도록 안내
- 불필요한 데이터 전송 방지
- Gateway 제한 준수

**내용**:
- 권장 데이터 구조 예시
- 불필요한 메타데이터 제거 방법
- 중첩 구조 최적화 방법

---

## 🔍 테스트 시나리오

### 시나리오 1: 요청 본문 크기 검증 테스트

```bash
# 작은 context 데이터 (정상)
curl -N -X POST http://localhost:9000/aura/test/stream \
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

# 큰 context 데이터 (256KB 초과) - 에러 발생 예상
python3 -c "
import json
large_data = {'largeField': 'x' * 300000}  # 300KB
request = {
    'prompt': '테스트',
    'context': large_data
}
print(json.dumps(request))
" | curl -N -X POST http://localhost:9000/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: tenant1" \
  -H "Content-Type: application/json" \
  -d @-
```

---

## 📞 다음 단계

1. **요청 본문 크기 검증 로직 추가**
   - Pydantic 모델에 `field_validator` 추가
   - 또는 엔드포인트에서 검증

2. **문서화 업데이트**
   - 요청 본문 크기 제한 문서 추가
   - `context` 데이터 최적화 가이드 작성

3. **테스트 수행**
   - 작은 context 데이터 테스트
   - 큰 context 데이터 테스트 (256KB 초과)
   - 에러 메시지 확인

---

**최종 업데이트**: 2026-01-16  
**담당자**: Aura-Platform 개발팀
