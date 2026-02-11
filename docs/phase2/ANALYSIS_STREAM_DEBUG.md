# Phase2 Analysis Stream 빈 응답 디버깅

## BE 반영 완료 (2026-02)

BE에서 Aura 문서에 맞춰 **`BodyHandlers.ofLines()`** 로 변경 반영함.  
- 기존: `ofInputStream()` + 바이트 루프 → **ofLines()** 라인 단위 스트리밍  
- 로그: `SSE proxy first line received`, `totalBytesForwarded`, `lineCount`  
상세: `docs/phase2/BE_ACTION_ITEMS.md` 상단 "BE 반영 완료" 참고.

---

## BE 중계 시 확인 사항 (Aura 측)

- **엔드포인트**: `GET /aura/cases/{caseId}/analysis/stream?runId={runId}` 구현됨 (`api/routes/aura_cases.py`).
- **Content-Type**: `StreamingResponse(..., media_type="text/event-stream")` 로 `text/event-stream` 응답.
- **실제 전송**: 연결 직후 `: connected\n\n` 한 줄 전송, 이후 `event: started`, `event: step`, … `event: completed`/`failed`, 마지막 `data: [DONE]\n\n` 순으로 flush.
- **바로 닫기 금지**: 200만 보내고 본문 없이 닫지 않음. 로깅은 raw ASGI로 처리해 스트림 본문을 버퍼링/소비하지 않음.

## 현상

- `GET /api/synapse/analysis-runs/{runId}/stream` (또는 `/aura/analysis-runs/{runId}/stream`) 호출 시 **200** 이지만 **응답 본문(스트림)이 비어 있음**.

## 관련 코드 위치

| 역할 | 파일 | 설명 |
|------|------|------|
| 스트림 엔드포인트 | `api/routes/aura_analysis_runs.py` | `GET /{run_id}/stream`, `queue_exists` / `get_event` 사용 |
| 이벤트 큐 | `core/analysis/run_store.py` | `get_or_create_queue`, `put_event`, `get_event`, `remove_queue` (in-memory) |
| 트리거(큐 생성·백그라운드 실행) | `api/routes/aura_cases.py` | `POST /{case_id}/analysis-runs` → `get_or_create_queue(run_id)` + `_run_analysis_background` |
| Phase3 트리거 | `api/routes/aura_internal.py` | `POST /aura/internal/cases/{caseId}/analysis-runs` (Phase3용) |

## 동작 흐름

1. **트리거**: BE/클라이언트가 `POST .../analysis-runs` 호출 → `runId`로 큐 생성 + 백그라운드에서 분석 실행하며 `put_event(run_id, event_type, payload)` 호출.
2. **스트림**: 클라이언트가 `GET .../analysis-runs/{runId}/stream` 연결 → `get_event(run_id, timeout=300)`으로 큐에서 이벤트를 읽어 SSE로 전송.
3. **완료 후**: 백그라운드에서 `remove_queue(run_id)` 호출 → 해당 runId 큐 제거. 이후 스트림 측 `get_event`는 `None`을 받고 `[DONE]` 전송 후 종료.

## 빈 응답이 나올 수 있는 경우

1. **runId 불일치**  
   스트림 URL의 `runId`가 트리거 응답(202 body)의 `runId`와 다름. → 큐가 없으면 `queue_exists(run_id)`가 False → **JSON** `{"error": "runId not found or already completed", "runId": "..."}` 반환. 이 경우 200이면 body에 이 JSON이 있어야 함.

2. **트리거와 스트림이 서로 다른 프로세스**  
   `run_store`는 **프로세스 내 in-memory** dict. 트리거를 받은 워커(A)와 스트림을 받은 워커(B)가 다르면, B에는 해당 runId 큐가 없음. → 위와 동일하게 "runId not found" JSON이 나와야 함.  
   **확인**: 동일 서버 단일 프로세스인지, 로드밸런서로 여러 인스턴스로 나가는지 확인.

3. **스트림을 너무 늦게 연결**  
   분석이 이미 끝나 `remove_queue(run_id)`가 호출된 뒤에 스트림을 열면, `queue_exists(run_id)`가 False → "runId not found" JSON 반환.

4. **큐는 있지만 이벤트가 아직/전혀 없음**  
   큐가 있어서 스트림이 시작되지만, 백그라운드가 아직 `put_event`를 하지 않았거나 다른 프로세스에서만 put 하는 경우. 스트림 쪽은 `get_event(run_id, timeout=300)`에서 **최대 300초 대기**. 그동안 한 번도 이벤트가 오지 않으면 `None`을 받고, 그때 fallback `completed` + `[DONE]`을 보냄.  
   → **300초 동안은 빈 스트림처럼 보일 수 있음.**

5. **게이트웨이/프록시 버퍼링**  
   8080 게이트웨이가 스트리밍 응답을 버퍼링해 두고, 한 번에 보내거나 연결 종료 시에만 보내는 경우. 클라이언트는 200만 보고 본문을 거의 못 받을 수 있음.  
   → 게이트웨이에서 `X-Accel-Buffering: no` 등 스트리밍 비버퍼 설정 확인.

## 확인할 것 (체크리스트)

- [ ] 트리거 202 응답의 `runId`와 스트림 URL의 `runId`가 **완전 동일**한지.
- [ ] 트리거 호출과 스트림 연결이 **같은 aura 인스턴스**로 가는지 (단일 프로세스 또는 동일 워커).
- [ ] 스트림을 **트리거 직후** 연결했는지 (분석 완료 후가 아님).
- [ ] 로그 레벨을 `DEBUG`로 올린 뒤, 다음 로그가 나오는지:
  - `analysis_run_stream: runId not found or already completed run_id=...` → 큐 없음.
  - `analysis_run_stream: start consuming run_id=...` → 스트림 진입.
  - `analysis_run_stream: get_event returned None ...` → 타임아웃 또는 큐 제거됨.
  - `run_store: queue removed run_id=...` → 백그라운드에서 큐 제거 시점.

## 로그로 보는 방법

환경변수 또는 `core.config`에서 `log_level=DEBUG`로 설정한 뒤 aura 서버 로그를 확인.

- 스트림 요청 시: `analysis_run_stream: start consuming run_id=556a7675-...` 가 있으면 큐가 있어서 스트림이 시작된 것.
- `get_event returned None` 만 반복되거나, 한 번도 이벤트가 오지 않으면 → 해당 runId로 **put_event를 하는 쪽이 이 프로세스에서 실행되지 않음** (트리거가 다른 인스턴스로 갔거나, Phase3 트리거만 쓰고 Phase2 큐를 안 쓰는 경우 등).

## 같이 봐야 하는 시스템 (여전히 0바이트일 때)

로그에 **`Status: 200 - Duration: 0.117s`** 처럼 스트림이 **0.1~0.2초 만에 끝난 것처럼** 나오면,  
Aura는 스트림을 열었지만 **반대쪽에서 연결을 먼저 끊은 것**으로 보는 게 맞습니다. (분석은 4~6초 뒤에 끝나는데 스트림만 0.1초에 끝남.)

| 확인할 시스템 | 확인 내용 |
|---------------|-----------|
| **BE (Synapse) 프록시** | 1) **totalBytesForwarded** 값: 0이면 Aura→BE로 0바이트 전달된 것. 0보다 크면 Aura는 데이터를 보냈고, BE 중계/클라이언트 쪽을 봐야 함.<br>2) Aura로 스트림 연결한 뒤 **본문을 계속 읽는 루프**가 있는지 (한 번만 읽고 끊지 않는지).<br>3) Aura 연결 **타임아웃**이 너무 짧지 않은지 (예: 1초 이하).<br>4) **Upgrade** 헤더를 BE→Aura 요청에 붙이지 않는지 (SSE는 Upgrade 불필요). |
| **게이트웨이(8080 등)** | Aura 앞단에 프록시가 있으면: 스트리밍 응답 버퍼링 여부, `X-Accel-Buffering: no` 전달 여부. |
| **클라이언트(브라우저/앱)** | EventSource 또는 fetch로 스트림을 **끝까지 읽는지**, 연결을 바로 닫지 않는지. |

### Aura만 직접 확인하는 방법 (BE 제외)

BE를 거치지 않고 Aura 스트림만 열어서 데이터가 오는지 확인:

```bash
# 1) 트리거 (runId 받기)
curl -s -X POST "http://localhost:9000/aura/cases/85116/analysis-runs" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "X-Tenant-ID: 1" \
  -d '{"runId":"test-run-001","caseId":"85116"}' 
# → 202와 body에 "runId","streamUrl" 확인

# 2) 스트림 연결 (위 runId 사용, 30초 대기)
curl -s -N "http://localhost:9000/aura/cases/85116/analysis/stream?runId=test-run-001" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "X-Tenant-ID: 1" \
  -H "Accept: text/event-stream"
# → : connected / event: started / event: step / ... / data: [DONE] 이 보이면 Aura는 정상
```

- **Aura 직접 호출에서 데이터가 보이면** → Aura는 정상, **BE 중계 또는 클라이언트**에서 연결을 끊거나 읽지 않는 쪽을 보면 됨.
- **Aura 직접 호출에서도 0바이트면** → Aura 서버/uvicorn 설정(버퍼, 스트리밍) 추가 확인.

## BE 답변 (2026-02-10, Aura 확인 요청 1·2번)

Aura 측에서 전달한 확인 요청에 대한 BE 답변 요약.

| 항목 | BE 동작 |
|------|--------|
| **본문 읽기 루프** | Aura 연결 후 `response.body()` InputStream을 `while ((n = in.read(buf)) != -1)` 로 **스트림이 닫힐 때까지 계속 읽고**, 읽은 바이트를 그대로 클라이언트(SseEmitter)로 전달. |
| **타임아웃** | Connect 10초, **Read 30분**. 30분 동안 데이터가 없어도 연결 유지. |
| **Upgrade 헤더** | **보내지 않음.** Aura 요청에는 **Accept: text/event-stream** 만 사용 (코드 반영 완료). |

BE 정리: totalBytesForwarded=0 이면, BE 동작과 무관하게 **Aura가 200 후 본문 0바이트를 보내고 연결을 닫은 경우**에 해당한다고 봄.

**Aura 측 검증 결과**: BE를 거치지 않고 Aura에 직접 `GET /aura/cases/{caseId}/analysis/stream?runId=...` 호출 시 **1816 bytes** 수신 확인 (`scripts/verify_aura_stream_direct.py`). 즉 Aura 단독 동작은 정상.

**BE 추가 답변 (경유 경로·검증 방법)**  
- **BE → Aura**: SynapseX(8085) → **Aura(9000) 직연결**, 게이트웨이/프록시 미경유. `java.net.http.HttpClient`로 `aura.base-url`(기본 `http://localhost:9000`) 직접 GET.  
- **totalBytesForwarded 검증**: Aura에서 동일 URL로 직접 호출해 본문이 나오면, BE 경유 시에도 totalBytesForwarded > 0이 되어야 함. (Aura 측에서 `scripts/verify_aura_stream_direct.py`로 이미 1816 bytes 수신 확인됨.)

**BE 추가 반영 (Q1·Q2, 문서 §3.1 및 프록시 로그)**  
- **Q1 (동일 인스턴스)**: SynapseX 로그 `SSE proxy connecting to Aura: runId=... caseId=... url=http://...` 의 **url** 값이 BE가 접속한 주소. Aura 직접 검증 시 이 url로 curl 하면 같은 인스턴스로 볼 수 있음. 설정: aura.base-url 또는 AURA_BASE_URL / AURA_PLATFORM_URL.  
- **Q2 (누가 먼저 끊었는지)**: totalBytesForwarded=0일 때 BE 로그로 구분. `SSE proxy Aura stream ended: ... totalBytesForwarded=0` 뒤에 **`SSE proxy: stream closed by remote (Aura) without sending any bytes: runId=...`** → Aura가 먼저 연결을 닫은 경우. `SSE proxy Aura stream error: runId=... (TimeoutException 등)` → BE/HttpClient 쪽에서 끊긴 경우. (상세 로그 메시지는 BE 문서 §3.1 참고.)

---

## "Unsupported upgrade request" / BE HTTP/1.1 수정

Aura 로그에 나오던 **`WARNING: Unsupported upgrade request.`** 는 BE(SynapseX)가 Aura로 스트림 요청을 보낼 때 **Java HttpClient가 HTTP/2 업그레이드를 시도**하면서 `Upgrade: h2c` 등 헤더를 보내서 발생한 것으로 확인되었습니다.

**BE 수정**: `AnalysisStreamProxyService`에서 Aura로 요청하는 HttpClient를 **HTTP/1.1 전용**으로 변경 (`HttpClient.Version.HTTP_1_1`). HTTP/2 업그레이드를 시도하지 않으므로 Upgrade 헤더가 나가지 않습니다.  
→ Aura에서는 해당 경고가 더 이상 나오지 않아야 하고, 스트림 동작이 정상화될 수 있습니다.

---

## 스트림 빈 응답: BaseHTTPMiddleware 취소 → Stream Bypass

BE HTTP/1.1 수정 후에도 **스트림 API 응답이 비어 있는** 경우, Aura 로그에  
`case_analysis_stream: stream closed ... reason=Cancelled via cancel scope ... by BaseHTTPMiddleware.__call__` 가 찍힐 수 있음.  
Starlette의 **BaseHTTPMiddleware**가 스트리밍 응답 body를 소비하는 태스크를 취소하는 동작 때문.

**Aura 측 조치**:  
- **StreamBypassMiddleware** (raw ASGI): `GET /aura/cases/{id}/analysis/stream` 요청만 별도 서브앱(`stream_app`)으로 넘김.  
- `stream_app`에는 **BaseHTTPMiddleware를 전혀 두지 않음** (CORS도 제거. BE→Aura는 서버 간 호출이라 CORS 불필요).  
- 인증은 스트림 라우트의 `CurrentUser` 의존성에서 헤더 기반 fallback으로 처리.

**스트림이 여전히 취소되는 경우** (`reason=Cancelled ... by RequestResponseCycle.run_asgi()`):  
uvicorn이 **클라이언트(BE) 연결 종료**를 감지해 태스크를 취소한 상태.

### 정밀 진단 (타임라인 분석 결과)

```
15:26:10.064 - GET /aura/cases/.../analysis/stream 요청 도착
15:26:10.065 - 첫 청크 전송 (": connected\n\n")           ← 1ms 후
15:26:10.072 - 스트림 취소 (클라이언트 연결 종료)         ← 8ms 후!
15:26:10.161 - 첫 tool 응답 도착 (started 이벤트 큐 적재 시점)
```

**초기 진단**: Aura 로그 상 "BE가 연결을 끊었다"처럼 보임.

### ✅ 스트림 조기 끊김 — 원인: FE(브라우저) 조기 종료 (BE 답변 반영)

BE 확인 결과, **끊김 순서**는 다음과 같음:

1. **FE(브라우저)가 먼저 연결 종료**
2. BE가 다음 청크를 FE로 보내려 할 때 `emitter.send()` 에서 **IllegalStateException** (FE 이미 끊김)
3. BE가 Aura 읽기 루프 break → Aura 스트림도 종료
4. Aura 입장에서는 "클라이언트(BE)가 끊었다"로 로그에 찍힘

| BE 확인 항목 | BE 답변 |
|--------------|--------|
| ofLines() 배포 반영 | ✅ 코드 반영됨. 로그에 `SSE proxy first line received`, `totalBytesForwarded` 찍히면 해당 경로 동작. |
| 첫 N줄만 읽고 끊는 로직 | ✅ **없음.** 스트림을 끊는 유일한 경우는 FE가 이미 끊었을 때 `emitter.send()` → IllegalStateException. |
| totalBytesForwarded | ✅ 찍힘. 예: totalBytesForwarded=12, lineCount=1 → 첫 줄(`: connected`) 수신·전달됨. |

**권장**: **FE에서 EventSource/스트림을 유지하는지**, 첫 이벤트(`: connected` 등) 수신 후 닫는 로직이 있는지 확인.

**Aura 측**: 수정 사항 없음. `GET /aura/cases/{caseId}/analysis/stream?runId=` 제공 유지.

---

### BE 측 필수 조치 (과거·참고)

BE의 HTTP 클라이언트가 **스트리밍을 제대로 읽지 않음**. 다음을 확인·수정 필요:

1. **Streaming HTTP Client 사용**
   - Java HttpClient의 경우: `BodySubscribers.ofLines()` 또는 `BodySubscribers.ofByteArrayConsumer()` 등 스트리밍 body subscriber 사용
   - 응답 본문을 **청크 단위로 읽으면서** 처리 (전체 응답 대기 X)

2. **연결 유지**
   - SSE는 **장시간 연결**(몇 초~몇 분)이 유지되어야 함
   - Read timeout을 충분히 설정 (최소 30초 이상, 권장 5분)
   - 데이터가 즉시 안 와도 연결을 끊지 말 것

3. **검증 방법**
   - BE 로그에서 해당 요청의 `totalBytesForwarded` 값 확인
   - 0이면 Aura에서 바이트를 거의 받지 못한 것 → BE가 읽기 전에 연결 종료
   - Aura 직접 호출 (`curl -N http://localhost:9000/aura/cases/.../analysis/stream?runId=...`) 시 정상 수신되면 BE 클라이언트 문제

### Aura 스트림 동작 (정석)

- 연결 직후 SSE 주석 한 줄 `: connected\n\n` 전송 (스트림 연결 인식용).
- 이후 **큐에서만** 이벤트 수신: 파이프라인이 `put_event` 하는 `started` → `step` → … → `completed`/`failed` 순으로 전송, 마지막에 `data: [DONE]\n\n`.

### Aura 정상 동작 검증 (BE 없이)

```bash
# 방법 1: Python 스크립트
python scripts/test_stream_direct.py

# 방법 2: curl
# 1) 트리거
curl -X POST http://localhost:9000/aura/cases/85115/analysis-runs \
  -H "Authorization: Bearer test-token" | jq -r '.runId'

# 2) 스트림 (runId 교체)
curl -N http://localhost:9000/aura/cases/85115/analysis/stream?runId=<RUN_ID> \
  -H "Authorization: Bearer test-token"
```

→ **이벤트가 정상 출력되면 Aura는 정상, BE 클라이언트 문제 확정**

---

## BE 측 조치 사항 (상세)

**→ 자세한 내용은 `docs/phase2/BE_ACTION_ITEMS.md` 참고**

핵심 요약:
1. ✅ **Streaming HTTP Client 사용** (`BodyHandlers.ofLines()`)
2. ✅ **Read timeout 충분히** (최소 5분)
3. ✅ **받은 즉시 FE 전달** (버퍼링 금지, flush)
4. ✅ **로그 추가** (totalBytesForwarded, 라인별 수신)

---

## Phase2 vs Phase3

- **Phase2**: `POST /aura/cases/{caseId}/analysis-runs` (aura_cases) → `run_store` + `phase2_pipeline`.
- **Phase3**: `POST /aura/internal/cases/{caseId}/analysis-runs` (aura_internal) → 동일 `run_store` + `phase3_pipeline`.

같은 runId에 대해 트리거한 쪽(Phase2/Phase3)과 스트림을 여는 URL이 같은 서비스(aura)를 바라보는지, 그리고 위 체크리스트를 확인하면 원인 범위를 좁힐 수 있습니다.
