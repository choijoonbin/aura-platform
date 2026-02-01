# 백엔드 검증 문서 응답

> **작성일**: 2026-01-16  
> **버전**: v1.0  
> **대상**: Aura-Platform 백엔드 통합 검증 응답

---

## ✅ 검증 항목별 구현 상태

### 1. 포트 및 엔드포인트 설정

#### ✅ 포트 9000에서 실행
- **설정 위치**: `core/config.py`
- **기본값**: `api_port: int = 9000`
- **실행 명령**: `uvicorn main:app --host 0.0.0.0 --port 9000`
- **확인 방법**:
  ```bash
  curl -X GET http://localhost:9000/health
  ```

#### ✅ POST /aura/test/stream 엔드포인트 구현
- **엔드포인트**: `POST /aura/test/stream`
- **Gateway 경로**: `POST /api/aura/test/stream`
- **구현 위치**: `api/routes/aura_backend.py`
- **상태**: ✅ 완료

---

### 2. POST 엔드포인트 구현

#### ✅ POST 메서드로 SSE 스트림 제공
- **HTTP 메서드**: `POST`
- **응답 타입**: `text/event-stream`
- **구현**: `@router.post("/test/stream")` 데코레이터 사용

#### ✅ 요청 본문 파싱 (prompt, context)
- **요청 모델**: `BackendStreamRequest`
  ```python
  class BackendStreamRequest(BaseModel):
      prompt: str  # 사용자 프롬프트
      context: dict[str, Any]  # 컨텍스트 정보
      thread_id: str | None  # 스레드 ID (선택)
  ```
- **파싱**: FastAPI의 자동 파싱 사용
- **상태**: ✅ 완료

---

### 3. SSE 응답 헤더 설정

#### ✅ Content-Type: text/event-stream
- **설정 위치**: `StreamingResponse`의 `media_type` 파라미터
- **구현**:
  ```python
  return StreamingResponse(
      event_generator(),
      media_type="text/event-stream",
      headers={...}
  )
  ```

#### ✅ Cache-Control: no-cache
- **설정**: `headers={"Cache-Control": "no-cache"}`

#### ✅ Connection: keep-alive
- **설정**: `headers={"Connection": "keep-alive"}`

#### ✅ X-Accel-Buffering: no
- **설정**: `headers={"X-Accel-Buffering": "no"}` (Nginx 버퍼링 비활성화)

**전체 헤더 설정**:
```python
headers={
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
```

**상태**: ✅ 완료

---

### 4. SSE 이벤트 ID 포함

#### ✅ 각 이벤트에 id: 라인 포함
- **구현 위치**: `api/routes/aura_backend.py`의 `format_sse_event` 함수
- **형식**:
  ```
  id: {event_id}
  event: {event_type}
  data: {json_data}
  ```
- **이벤트 ID 생성**: Unix timestamp (밀리초) 기반 순차 증가
- **구현**:
  ```python
  def format_sse_event(event_type: str, data: dict[str, Any], event_id: str | None = None) -> str:
      if event_id is None:
          event_id = str(int(datetime.utcnow().timestamp() * 1000))
      return f"id: {event_id}\nevent: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
  ```
- **상태**: ✅ 완료

---

### 5. 재연결 지원

#### ✅ Last-Event-ID 헤더 처리
- **헤더 이름**: `Last-Event-ID`
- **구현 위치**: `api/routes/aura_backend.py`의 `backend_stream` 함수
- **처리 로직**:
  ```python
  last_event_id: str | None = Header(None, alias="Last-Event-ID")
  
  # 이벤트 ID 카운터 초기화
  event_id_counter = 0
  if last_event_id:
      try:
          last_id = int(last_event_id)
          event_id_counter = last_id + 1
          logger.info(f"Resuming from event ID: {last_event_id}")
      except (ValueError, TypeError):
          logger.warning(f"Invalid Last-Event-ID: {last_event_id}, starting from 0")
  ```
- **재연결 시 동작**: 
  - `Last-Event-ID` 헤더가 있으면 해당 이벤트 ID 다음부터 이벤트 발행
  - 체크포인트를 사용하여 이전 상태 복원 가능 (thread_id 기반)
- **상태**: ✅ 완료

#### ⚠️ 중단된 지점부터 이벤트 재개
- **현재 구현**: 이벤트 ID 기반 재개 (기본 구현)
- **향상 가능**: 체크포인트를 사용한 완전한 상태 복원
  - 현재는 `thread_id`를 통해 체크포인트 복원 가능
  - `Last-Event-ID`와 `thread_id`를 함께 사용하면 더 정확한 재개 가능
- **권장 사항**: 프론트엔드에서 재연결 시 `thread_id`와 `Last-Event-ID`를 함께 전달

**상태**: ✅ 기본 구현 완료 (향상 가능)

---

### 6. 요청 본문 파싱

#### ✅ POST 요청 본문에서 prompt와 context 파싱
- **구현**: FastAPI의 Pydantic 모델 자동 파싱
- **요청 예시**:
  ```json
  {
    "prompt": "사용자 질문",
    "context": {
      "url": "http://localhost:4200/mail",
      "path": "/mail",
      "title": "메일 인박스",
      "activeApp": "mail",
      "itemId": "msg-123",
      "selectedItemIds": [1, 2, 3],
      "metadata": {...}
    },
    "thread_id": "optional_thread_id"
  }
  ```
- **상태**: ✅ 완료

---

### 7. 헤더 전파 확인

#### ✅ Gateway에서 전달되는 헤더 처리
- **처리되는 헤더**:
  - `Authorization`: JWT 토큰 (자동 검증)
  - `X-Tenant-ID`: 테넌트 ID (필수)
  - `X-DWP-Source`: 요청 출처 (선택)
  - `X-DWP-Caller-Type`: 호출자 타입 (선택)
  - `X-User-ID`: 사용자 ID (선택, 현재는 JWT에서 추출)
  - `Last-Event-ID`: 재연결 지원 (선택)

- **구현 위치**: `api/routes/aura_backend.py`
  ```python
  @router.post("/test/stream")
  async def backend_stream(
      request: BackendStreamRequest,
      user: CurrentUser,  # JWT에서 추출
      tenant_id: TenantId,  # X-Tenant-ID 헤더
      x_dwp_source: str | None = Header(None, alias="X-DWP-Source"),
      x_dwp_caller_type: str | None = Header(None, alias="X-DWP-Caller-Type"),
      last_event_id: str | None = Header(None, alias="Last-Event-ID"),
  ):
  ```

- **상태**: ✅ 완료

---

### 8. SSE 이벤트 형식

#### ✅ 프론트엔드 명세에 맞는 이벤트 타입
- **지원 이벤트 타입**:
  - `start`: 시작 이벤트
  - `thought`: 사고 과정
  - `plan_step`: 계획 단계
  - `plan_step_update`: 계획 단계 업데이트
  - `timeline_step_update`: 타임라인 단계 업데이트
  - `tool_execution`: 도구 실행
  - `hitl`: 승인 요청
  - `content`: 최종 결과
  - `end`: 종료 이벤트
  - `error`: 에러 이벤트
  - `failed`: 작업 실패 이벤트 (HITL 타임아웃 등)

#### ✅ timestamp 필드 형식 (Unix timestamp, 초 단위)
- **구현**: 모든 이벤트의 `timestamp` 필드는 Unix timestamp (초 단위 정수)
- **예시**:
  ```python
  "timestamp": int(datetime.utcnow().timestamp())
  ```
- **상태**: ✅ 완료

---

## 📋 검증 체크리스트

### 포트 및 엔드포인트
- [x] 포트 9000에서 실행
- [x] POST /aura/test/stream 엔드포인트 구현

### POST 엔드포인트
- [x] POST 메서드로 SSE 스트림 제공
- [x] 요청 본문 파싱 (prompt, context)

### SSE 응답 헤더
- [x] Content-Type: text/event-stream
- [x] Cache-Control: no-cache
- [x] Connection: keep-alive
- [x] X-Accel-Buffering: no

### SSE 이벤트 ID
- [x] 각 이벤트에 id: 라인 포함
- [x] 이벤트 ID는 순차적으로 증가

### 재연결 지원
- [x] Last-Event-ID 헤더 처리
- [x] 재연결 시 이벤트 ID 기반 재개
- [ ] 완전한 상태 복원 (체크포인트 기반, 향상 가능)

### 요청 본문 파싱
- [x] POST 요청 본문에서 prompt 파싱
- [x] POST 요청 본문에서 context 파싱

### 헤더 전파
- [x] Authorization 헤더 처리
- [x] X-Tenant-ID 헤더 처리
- [x] X-DWP-Source 헤더 처리
- [x] X-DWP-Caller-Type 헤더 처리
- [x] Last-Event-ID 헤더 처리

### SSE 이벤트 형식
- [x] 프론트엔드 명세에 맞는 이벤트 타입
- [x] timestamp 필드 형식 (Unix timestamp, 초 단위)

---

## 🧪 테스트 방법

### 1. 기본 SSE 스트리밍 테스트
```bash
TOKEN="<JWT_TOKEN>"

curl -N -X POST http://localhost:9000/aura/test/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "테스트 질문",
    "context": {
      "activeApp": "mail",
      "url": "http://localhost:4200/mail"
    }
  }'
```

### 2. 재연결 지원 테스트 (Last-Event-ID)
```bash
TOKEN="<JWT_TOKEN>"
LAST_EVENT_ID="1234567890"  # 이전 연결의 마지막 이벤트 ID

curl -N -X POST http://localhost:9000/aura/test/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1" \
  -H "Last-Event-ID: $LAST_EVENT_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "테스트 질문",
    "context": {},
    "thread_id": "previous_thread_id"
  }'
```

### 3. Gateway를 통한 테스트
```bash
TOKEN="<JWT_TOKEN>"

curl -N -X POST http://localhost:8080/api/aura/test/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1" \
  -H "X-DWP-Source: FRONTEND" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "테스트 질문",
    "context": {
      "activeApp": "mail",
      "selectedItemIds": [1, 2, 3]
    }
  }'
```

---

## 📝 구현 세부사항

### SSE 이벤트 형식 예시
```
id: 1706149260000
event: start
data: {"type":"start","message":"Agent started","timestamp":1706149260}

id: 1706149260050
event: thought
data: {"type":"thought","thoughtType":"analysis","content":"사용자 요청을 분석 중...","timestamp":1706149260}

id: 1706149260100
event: plan_step
data: {"type":"plan_step","stepId":"step1","description":"단계 1 실행","status":"pending","confidence":0.8,"timestamp":1706149260}

id: 1706149260150
event: content
data: {"type":"content","content":"최종 응답 내용","timestamp":1706149260}

id: 1706149260200
event: end
data: {"type":"end","message":"Agent finished","timestamp":1706149260}

data: [DONE]
```

### 재연결 시나리오
1. **클라이언트 연결 끊김**: 네트워크 오류, 타임아웃 등
2. **재연결 요청**: `Last-Event-ID` 헤더에 마지막 이벤트 ID 포함
3. **서버 처리**: 
   - `Last-Event-ID`를 읽어 이벤트 ID 카운터 초기화
   - `thread_id`가 있으면 체크포인트에서 상태 복원
   - 중단 지점부터 이벤트 재개

---

## ✅ 검증 완료 사항

모든 백엔드 검증 문서의 확인 사항이 구현되었습니다:

1. ✅ 포트 9000에서 실행
2. ✅ POST /aura/test/stream 엔드포인트 구현
3. ✅ POST 메서드로 SSE 스트림 제공
4. ✅ 요청 본문 파싱 (prompt, context)
5. ✅ SSE 응답 헤더 설정 (Content-Type, Cache-Control, Connection)
6. ✅ SSE 이벤트 ID 포함 (재연결 지원)
7. ✅ Last-Event-ID 헤더 처리
8. ✅ 헤더 전파 확인 (Authorization, X-Tenant-ID 등)
9. ✅ SSE 이벤트 형식 (프론트엔드 명세 준수)
10. ✅ timestamp 필드 형식 (Unix timestamp, 초 단위)

---

## 🔄 향상 가능 사항

### 완전한 상태 복원 (선택사항)
현재는 이벤트 ID 기반 재개만 지원하지만, 체크포인트를 사용한 완전한 상태 복원도 가능합니다:

```python
# 향후 개선 방향
if last_event_id and thread_id:
    # 체크포인트에서 상태 복원
    checkpoint = await checkpointer.get({"configurable": {"thread_id": thread_id}})
    if checkpoint:
        # 복원된 상태에서 재개
        ...
```

이 기능은 현재 LangGraph Checkpointer를 통해 지원되며, `thread_id`를 사용하면 자동으로 상태가 복원됩니다.

---

## 📞 문의

백엔드 통합 과정에서 문제가 발생하거나 추가 확인이 필요한 경우:
- **Aura-Platform 팀**: 이슈 트래커 또는 개발팀에 문의
- **문서**: `docs/BACKEND_HANDOFF.md`, `docs/INTEGRATION_CHECKLIST.md` 참조

---

**문서 버전**: v1.0  
**최종 업데이트**: 2026-01-16
