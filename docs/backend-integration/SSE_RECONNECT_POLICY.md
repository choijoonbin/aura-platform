# SSE 재연결 정책 (id / Last-Event-ID)

> **대상**: Aura-Platform (Python), FE는 SSE 표준 `id` / `Last-Event-ID` 재연결을 전제로 함  
> **작성일**: 2026-02-01

---

## 1. 정책 요약

| 항목 | 정책 | 구현 상태 |
|------|------|-----------|
| **이벤트 ID** | 모든 SSE 이벤트에 `id: <eventId>` 라인 **필수** | ✅ |
| **Last-Event-ID** | 헤더가 오면 **그 이후 이벤트만** 재전송(이벤트 ID > Last-Event-ID) | ✅ |
| **중복/순서** | Exactly-once 불가 → **At-least-once + 클라이언트 dedupe(id)** | 문서화 |
| **종료** | 모든 서버 종료 경로에서 `data: [DONE]\n\n` **보장** | ✅ |

---

## 2. 이벤트 ID (`id: <eventId>`)

### 2.1 규칙

- **모든** 데이터 이벤트(thought, plan_step, tool_execution, hitl, content, start, end, error, failed 등)는 반드시 한 줄 `id: <eventId>` 를 포함한다.
- 종료 마커 `data: [DONE]\n\n` 는 이벤트가 아니므로 `id` 를 붙이지 않는다.
- `eventId` 는 **문자열**이며, 한 스트림 내에서 **단조 증가**하는 값으로 사용한다(재연결 시에도 이어갈 수 있도록).

### 2.2 코드 근거

- **포맷**: `api/routes/aura_backend.py` 의 `format_sse_event()` (라인 77–115).
  - 반환 형식: `id: {event_id}\nevent: {event_type}\ndata: {json}\n\n`
  - 모든 `yield format_sse_event(...)` 호출에는 세 번째 인자로 `str(event_id_counter)` 를 넘겨 `id` 를 부여한다.
- **발행 경로**: `backend_stream()` 내부의 모든 이벤트 발행은 `format_sse_event(..., str(event_id_counter))` 를 통해 이루어지며, 예외 없이 `id` 가 포함된다.
  - 시작: 194라인  
  - HITL: 278, 302, 312, 321라인  
  - 큐 이벤트: 357라인  
  - 정상 종료: 370라인  
  - 예외/에러: 164, 337, 384라인  

---

## 3. Last-Event-ID 재전송(replay) 정책

### 3.1 동작

- 요청 헤더에 **`Last-Event-ID: <id>`** 가 있으면, 서버는 **이벤트 ID가 `id` 보다 큰 이벤트만** 보낸다.
- 즉, “그 이후 이벤트만 재전송”한다. 이미 클라이언트가 받은 `id` 이하의 이벤트는 **다시 보내지 않는다**.

### 3.2 구현 방식

- Aura-Platform은 **이벤트 로그를 영속 저장하지 않는다**. 따라서 “저장된 이벤트 목록에서 Last-Event-ID 다음 것만 재전송”하는 형태가 아니라, **이벤트 ID만 이어 붙이는 방식**으로 정책을 만족한다.
- 동작:
  1. `Last-Event-ID` 를 파싱해 `last_id` (정수) 로 사용.
  2. 다음 이벤트 ID를 `event_id_counter = last_id + 1` 로 설정.
  3. 이후 모든 이벤트는 `event_id_counter` 를 1씩 증가시키며 발행.

따라서 **같은 연결(세션) 내**에서:
- 재연결 요청에 `Last-Event-ID` 를 넣으면, 새로 보내는 이벤트의 `id` 는 모두 `Last-Event-ID` 보다 크다.
- “그 이후 이벤트만 재전송”은 **“Last-Event-ID 초과인 id를 가진 이벤트만 보낸다”** 로 보장된다.

### 3.3 코드 근거

- **헤더 수신**: `api/routes/aura_backend.py` 125라인  
  `last_event_id: str | None = Header(None, alias="Last-Event-ID")`
- **재개 로직**: 176–184라인  
  - `last_event_id` 가 있으면 `last_id = int(last_event_id)`, `event_id_counter = last_id + 1`  
  - 파싱 실패 시 `event_id_counter = 0` (처음부터)

---

## 4. 중복 방지 및 순서 보장

### 4.1 전제

- **Exactly-once** 는 네트워크/재연결/서버 재시작을 고려할 때 **보장 불가**로 간주한다.
- 따라서 **At-least-once** 를 전제로 하고, **중복 제거는 클라이언트 책임**으로 정책을 정한다.

### 4.2 정책

| 구분 | 정책 |
|------|------|
| **전달 보장** | **At-least-once**: 같은 이벤트가 0번 올 수는 없고, 1번 이상 올 수 있음(재연결/재시도 시). |
| **중복 제거** | 클라이언트는 **이벤트 `id`** 를 기준으로 dedupe 한다. 이미 처리한 `id` 는 무시한다. |
| **순서** | **단일 연결 내**에서는 이벤트 ID가 단조 증가하므로, **같은 연결에서 수신 순서 = 이벤트 순서**로 간주한다. 재연결 후에는 새 연결의 첫 `id` 가 `Last-Event-ID + 1` 이상이므로, 기존에 받은 이벤트와의 순서도 `id` 로 판단 가능하다. |

### 4.3 클라이언트 권장 사항

- 마지막으로 처리한 이벤트의 `id` 를 저장한다.
- 재연결 시 요청 헤더에 **`Last-Event-ID: <저장한 id>`** 를 넣어 요청한다.
- 수신한 각 이벤트에 대해 `id` 가 “이미 처리한 집합”에 있으면 **무시**하고, 없으면 처리 후 집합에 추가한다.

---

## 5. 종료: `data: [DONE]\n\n`

### 5.1 규칙

- 스트림이 **서버에 의해 종료되는 모든 경로**에서, 마지막에 **반드시** 한 번 `data: [DONE]\n\n` 를 보낸다.
- 클라이언트가 먼저 연결을 끊는 경우(사용자 취소 등)에는 서버가 추가로 전송할 수 없으므로, **서버가 종료를 결정한 경우에만** [DONE] 을 보장한다.

### 5.2 서버 종료 경로별 [DONE] 발행 여부

| 종료 경로 | 파일:라인 | [DONE] 발행 |
|-----------|-----------|-------------|
| X-User-ID 불일치 → 에러 후 즉시 종료 | aura_backend.py:169 | ✅ |
| HITL 타임아웃 → failed/error/end 후 종료 | aura_backend.py:325 | ✅ |
| HITL 거절 → error 후 종료 | aura_backend.py:337 | ✅ |
| 정상 완료 → end 후 종료 | aura_backend.py:373 | ✅ |
| 예외 발생 → error 후 종료 | aura_backend.py:385 | ✅ |

위 경로 외에 **return** 또는 **예외**로 제너레이터가 끝나는 경로는 없으며, 모두 위 표의 경로에서 `yield "data: [DONE]\n\n"` 후 종료된다.

---

## 6. 테스트 시나리오

### 6.1 시나리오 1: 모든 이벤트에 `id` 포함

- **목적**: 데이터 이벤트마다 `id: <eventId>` 라인이 있는지 확인.
- **방법**: POST `/aura/test/stream` 로 스트리밍 후, 수신한 각 이벤트(줄 단위)에서 `id:` 로 시작하는 줄이 있는지 검사. `data: [DONE]` 전까지의 모든 `event:` / `data:` 블록에 대응하는 `id` 가 있어야 함.
- **기대**: 모든 데이터 이벤트에 `id` 존재.

### 6.2 시나리오 2: Last-Event-ID 이후 이벤트만 수신

- **목적**: 재연결 시 Last-Event-ID 이후 이벤트만 오는지 확인.
- **방법**:
  1. 스트림 연결 후 이벤트 몇 개 수신(예: id 1, 2, 3).
  2. 연결 종료.
  3. 동일 body로 **`Last-Event-ID: 3`** 헤더를 넣어 다시 POST.
- **기대**: 새 연결에서 받는 이벤트의 `id` 는 모두 4 이상. 1, 2, 3은 재전송되지 않음.

### 6.3 시나리오 3: 중간 끊김 후 재연결 + dedupe

- **목적**: 끊김 후 재연결 시 id 기반 dedupe 가능 여부.
- **방법**:
  1. 스트림 수신 중 일부만 받고(예: id 1, 2) 연결 강제 종료.
  2. `Last-Event-ID: 2` 로 재연결.
  3. 클라이언트는 id 1, 2는 이미 처리한 것으로 두고, id ≥ 3만 처리.
- **기대**: 중복 없이 이어서 처리 가능. (실제 스트림 내용은 새 실행이면 새 start/… 이벤트가 올 수 있음.)

### 6.4 시나리오 4: 중복 클릭(동시 요청)

- **목적**: 같은 사용자가 짧은 시간에 두 번 “스트림 시작”을 눌렀을 때, 두 연결이 각각 id를 가진 이벤트를 보내는지, [DONE] 으로 종료되는지 확인.
- **방법**: 동일 body로 동시에 두 개의 POST `/aura/test/stream` 요청.
- **기대**: 각 연결에서 (1) 모든 데이터 이벤트에 `id` 포함, (2) 각 연결이 끝날 때 `data: [DONE]\n\n` 수신. 클라이언트는 연결별로 또는 id 기준으로 dedupe.

### 6.5 시나리오 5: HITL 대기 중 종료

- **목적**: HITL 대기 상태에서 타임아웃/거절 시에도 [DONE] 이 나오는지 확인.
- **방법**: 승인이 필요한 도구가 나오는 프롬프트로 스트림 시작 → HITL 이벤트 수신 후 (a) 타임아웃까지 대기 또는 (b) 거절 API 호출.
- **기대**: (a) failed/error/end 이벤트 후 `data: [DONE]\n\n`, (b) error 이벤트 후 `data: [DONE]\n\n`.

### 6.6 시나리오 6: 모든 종료 경로에서 [DONE]

- **목적**: 정상 종료, 에러, HITL 타임아웃, HITL 거절, X-User-ID 불일치 등에서 [DONE] 이 한 번씩 나오는지 확인.
- **방법**: 위 5개 종료 유형별로 요청을 보내고, 스트림 끝에 `data: [DONE]\n\n` 이 오는지 검사.
- **기대**: 모든 경우에 [DONE] 수신.

---

## 7. 참고

- Gateway는 **Last-Event-ID 헤더 전달** 및 필요 시 **id 라인 보강**만 담당한다. 재연결 시 “그 이후 이벤트만 재전송”하는 쪽은 Aura-Platform이다.
- 이벤트 ID는 현재 **연결 단위 순차 정수**로 생성되며, Last-Event-ID 로 그 연속성이 이어진다.

---

## 8. 코드 근거 요약

| 항목 | 파일 | 라인(대략) | 내용 |
|------|------|------------|------|
| 이벤트 포맷(id 포함) | api/routes/aura_backend.py | 77–115 | `format_sse_event()` → `id: {event_id}\n...` |
| Last-Event-ID 수신 | api/routes/aura_backend.py | 125 | `last_event_id = Header(None, alias="Last-Event-ID")` |
| 재개(이후 이벤트만) | api/routes/aura_backend.py | 176–184 | `event_id_counter = last_id + 1` |
| [DONE] X-User-ID 불일치 | api/routes/aura_backend.py | 169 | `yield "data: [DONE]\n\n"` 후 return |
| [DONE] HITL 타임아웃 | api/routes/aura_backend.py | 325 | failed/error/end 후 `yield "data: [DONE]\n\n"` |
| [DONE] HITL 거절 | api/routes/aura_backend.py | 337 | error 후 `yield "data: [DONE]\n\n"` |
| [DONE] 정상 완료 | api/routes/aura_backend.py | 373 | end 후 `yield "data: [DONE]\n\n"` |
| [DONE] 예외 | api/routes/aura_backend.py | 385 | error 후 `yield "data: [DONE]\n\n"` |
