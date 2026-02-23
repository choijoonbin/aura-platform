# Aura SSE 스트리밍 스펙 (Phase2 Analysis Stream)

SynapseX 등 프록시가 안정적으로 중계할 수 있도록 Aura 분석 스트림의 포맷·헤더·이벤트 스키마를 고정합니다.

---

## 1. 엔드포인트·파라미터

| 항목 | 값 |
|------|-----|
| **Method** | `GET` |
| **Path** | `/aura/cases/{caseId}/analysis/stream` |
| **Query** | `runId` (필수) — `POST /aura/cases/{caseId}/analysis-runs` 202 응답 body의 `runId` |
| **인증** | `Authorization: Bearer <token>` (기존 인증 정책 동일) |

**전체 URL 예시**

```
GET http://<AURA_HOST>/aura/cases/85116/analysis/stream?runId=<runId>
```

---

## 2. Response Headers

Aura는 다음 헤더를 보냅니다 (표준 SSE·프록시 비버퍼링).

| Header | 값 | 비고 |
|--------|-----|------|
| **Content-Type** | `text/event-stream; charset=utf-8` | SSE 표준. charset 명시 권장. |
| **Cache-Control** | `no-cache, no-store` | 캐시 비활성화. |
| **Connection** | `keep-alive` | 장시간 연결 유지. |
| **X-Accel-Buffering** | `no` | nginx 등 프록시 버퍼링 비활성화. |

---

## 3. 이벤트 포맷·경계

- **인코딩**: UTF-8.
- **이벤트 경계**: 각 이벤트는 **반드시 `\n\n` (CRLF 아님, LF 두 개)로 종료**됩니다.
- **형식**: 한 이벤트당 `event: <type>\ndata: <JSON>\n\n` 형태. `data`는 한 줄로 직렬화된 JSON(이스케이프 없음, 개행 없음).

**프레임 형식 (고정)**

```
event: <event_type>
data: <JSON payload>

```

- `event:` / `data:` 뒤 공백 없음.
- `data` 직후 한 칸 공백 없이 JSON 시작.
- **항상 `\n\n`로 끝남** — 프록시는 이 경계로 프레임을 나누면 됨.

**Aura가 보내지 않는 것**

- **`id:` 라인**: Aura는 이벤트 ID를 붙이지 않음. `id:` 필드는 SynapseX 등 중간 계층에서 추가한 경우임.
- **빈 `data:` 라인**: 이벤트와 이벤트 사이에 빈 `data:` 또는 빈 주석 `:` 만 보내지 않음. 한 이벤트 = 한 블록(`event:` + `data:` + `\n\n`)만 전송.
- **한 이벤트의 `data:` 는 항상 한 줄**: JSON 내부 개행은 `\n` 이스케이프로 직렬화되므로, `data:` 다음에는 개행 없이 한 줄로 끝남. 중간에 줄을 나누면 프록시/클라이언트 측에서 잘못 파싱한 것.
- **UTF-8 중간 분할 금지**: 한 이벤트(한 줄 JSON)를 버퍼/바이트 단위로 자르면 한글 등 다바이트 문자가 깨짐(). 반드시 **이벤트 경계 `\n\n` 단위**로만 전달·파싱할 것.

---

## 4. Keep-alive (주석 라인)

- 연결 직후 **첫 번째 전송**은 SSE 주석 한 줄입니다.
- 형식: `: connected\n\n`
- 목적: 클라이언트/프록시가 스트림 연결을 인식하고, 빈 응답으로 오인하지 않도록 함.
- 이후에는 파이프라인이 큐에 넣은 이벤트만 순서대로 전송.

---

## 5. 이벤트 타입·JSON 스키마

### 5.1 `started`

분석 시작.

```json
{
  "runId": "<uuid>",
  "caseId": "<case_id>",
  "at": "<ISO 8601 datetime>"
}
```

### 5.2 `thought_pending` (LLM 추론 시작 직전 — FE 스켈레톤 대기)

**FE가 수신 대기하는 이벤트 타입.** LLM이 독백 문장을 생성하기 **직전**에 발행합니다.  
데이터: `step_label`, `message: "생각 중..."` 및 선택적 ID 매핑(`chunk_id`, `target_buzei` 등).

- **BE**: 이 이벤트를 그대로 FE에 전달.
- **FE**: 수신 시 스켈레톤·"생각 중..." 또는 스피너 표시 → 이후 동일 단계의 `AGENT_STREAM` / `step` 수신 시 실제 추론 문장으로 전환.

```json
{
  "step_label": "<INPUT_NORM | EVIDENCE_GATHER | REGULATION_MATCH | RULE_SCORING | LLM_REASONING | EVIDENCE_COLLECTED>",
  "message": "생각 중...",
  "doc_id": "<string | null>",
  "item_id": "<string | null>",
  "chunk_id": "<string | null>",
  "target_buzei": "<string | null>"
}
```

### 5.3 `AGENT_STREAM` (LLM 추론 문장 완성 시 — FE 실제 문장 표시)

**FE가 수신 대기하는 이벤트 타입.** LLM이 생성한 **한 문장 독백(추론 문장)**이 완성될 때마다 발행합니다.  
`thought_pending` 직후 → LLM 호출 → `AGENT_STREAM`(content) → `step`(기술적 단계 완료) 순서.

- **FE**: `content`를 추론 문장으로 표시. 문장 내 `****금액****`, `**제n조**` 등 마크다운 강조는 인하우스 렌더러로 표시.
- **ID 매핑**: `chunk_id`, `target_buzei`가 있으면 해당 전표 행에 'Red Glow' 등 하이라이트 적용 가능.

```json
{
  "content": "<한 문장 추론 독백. 마크다운 강조 포함 가능>",
  "step_label": "<단계 라벨>",
  "doc_id": "<string | null>",
  "item_id": "<string | null>",
  "chunk_id": "<string | null>",
  "target_buzei": "<string | null>"
}
```

### 5.4 `step` (기술적 단계 완료 시)

진행 단계 완료. **thought_pending → AGENT_STREAM → step** 순으로 발행됨.  
`total_steps`는 진행률(step_completion_rate) 계산용. `thought_stream`은 AGENT_STREAM의 `content`와 동일한 문장(호환용).

```json
{
  "label": "<단계 라벨>",
  "detail": "<상세 메시지>",
  "percent": <0..100>,
  "total_steps": <number | null>,
  "thought_stream": "<한 문장 독백 | null>",
  "doc_id": "<string | null>",
  "item_id": "<string | null>",
  "chunk_id": "<string | null>",
  "target_buzei": "<string | null>"
}
```

### 5.2.1 (구 레거시) thought_pending 상세

위 5.2와 동일. `step` 이벤트 직전에 먼저 전송되어 대기 상태(스켈레톤)에서 실제 추론 문장으로 자연스럽게 전환할 수 있게 함.

### 5.5 `evidence`

증거/문서 스니펫 (선택적, 단계별로 0회 이상).

```json
{
  "type": "<DOC_HEADER | DOC_ITEMS | OPEN_ITEMS | LINEAGE 등>",
  "items": [ ... ]
}
```

### 5.6 `confidence`

신뢰도 점수 (0회 또는 1회).

```json
{
  "anomalyScore": <float>,
  "patternMatch": <float>,
  "ruleCompliance": <float>,
  "overall": <float>
}
```

### 5.7 `proposal`

권고 조치 (0회 이상).

```json
{
  "type": "<PAYMENT_BLOCK | REQUEST_INFO 등>",
  "riskLevel": "<MEDIUM 등>",
  "rationale": "<string>",
  "requiresApproval": <boolean>,
  "payload": { ... }
}
```

### 5.8 `completed`

정상 완료. 스트림은 이 이벤트 후 **`data: [DONE]\n\n`** 한 줄 전송 후 종료.

```json
{
  "status": "completed",
  "runId": "<uuid>",
  "caseId": "<case_id>",
  "summary": "<요약 텍스트>",
  "score": <float>,
  "severity": "<LOW | MEDIUM | HIGH 등>"
}
```

### 5.9 `failed`

실패. **error 스키마**: **객체가 아니라 `error` 필드에 문자열**, `stage` 필드로 단계 구분.

```json
{
  "error": "<에러 메시지 문자열>",
  "stage": "<pipeline | background | trigger 등>"
}
```

- `error`: 항상 **string** (예: `str(exception)`).
- `stage`: string (발생 단계 식별용).
- `{ "message", "stage" }` 형태가 아니라 **`{ "error", "stage" }`** 객체로 고정.

---

## 6. 스트림 종료 신호 `[DONE]`

- **정상**: `event: completed` + `data: {...}` 전송 후, **`data: [DONE]\n\n`** 한 줄 전송 후 연결 종료.
- **실패**: `event: failed` + `data: {"error":"...","stage":"..."}` 전송 후, 동일하게 **`data: [DONE]\n\n`** 전송 후 연결 종료.
- **FE 수신 대기**: 이벤트 타입 문자열은 `[DONE]`이 아니라 **data 페이로드가 `[DONE]`**인 한 줄(`data: [DONE]\n\n`)로 스트림 최종 종료를 인식합니다.

---

## 7. 스트림 종료 (상세)

- **정상**: `event: completed` + `data: {...}` 전송 후, **`data: [DONE]\n\n`** 한 줄 전송 후 **즉시** 연결 종료.
- **실패**: `event: failed` + `data: {"error":"...","stage":"..."}` 전송 후, 동일하게 **`data: [DONE]\n\n`** 전송 후 연결 종료.
- **타임아웃/큐 제거**: 큐가 제거되면 스트림 측에서 fallback `completed` 또는 `[DONE]` 전송 후 종료.

**Aura가 [DONE] 다음에 보내는 데이터는 없음.**  
- Aura 코드: `yield "data: [DONE]\n\n"` 한 번만 수행 후 제너레이터 종료. 그 다음에 `yield` 하는 빈 줄(`\n`)이나 `data:\n` 같은 라인은 **없음**.
- 따라서 `data: [DONE]\n\n` 이후 Aura가 의도적으로 보내는 바이트는 0바이트임.
- [DONE] 뒤에 빈 payload 이벤트 1~2개가 보인다면, 가능한 원인은 (1) Starlette/uvicorn이 스트림 종료 시 빈 청크 또는 trailing flush를 보내는 경우, (2) Gateway가 `\n\n` 기준으로 블록을 나눌 때 연결 종료/버퍼 플러시 구간을 빈 블록으로 해석하는 경우.  
- **권장**: Gateway/프론트는 `data: [DONE]` 수신 시 **스트림 종료로 간주**하고, 이후 들어오는 빈 블록은 무시하거나 파싱하지 않음.

---

## 8. 필수 재현 (curl)

아래로 **표준 SSE·지속 스트리밍** 동작을 확인할 수 있습니다.

```bash
# 1) 트리거로 runId 취득
RUN_ID=$(curl -s -X POST "http://<AURA_HOST>/aura/cases/85116/analysis-runs" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{}' | jq -r '.runId')

# 2) 스트림 재현 (verbose, no buffer)
curl -N -v -H "Accept: text/event-stream" \
  "http://<AURA_HOST>/aura/cases/85116/analysis/stream?runId=$RUN_ID" \
  -H "Authorization: Bearer <TOKEN>"
```

**확인 사항**

| 확인 항목 | 기대 |
|-----------|------|
| **step 이벤트 2개 이상** | `event: step` 이 2회 이상 수신됨 (label·percent 포함). |
| **60초 이상 유지** | 분석이 끝날 때까지 연결 유지 (타임아웃 300초까지 대기 가능). |
| **`\n\n` 프레임 경계** | 각 이벤트가 `\n\n`로 끝나며, 중간에 경계가 깨지지 않음. |
| **Content-Type** | `text/event-stream` (또는 `text/event-stream; charset=utf-8`). |
| **Connection** | `keep-alive`. |
| **첫 줄** | `: connected` 주석 후 `event: started` … 순서. |

---

## 9. 엔진 내부 스트림 큐(run_store) 및 runId 점검

### 9.1 run_store 이벤트 적재 및 수명주기

- **적재**: `run_audit_analysis`가 yield하는 모든 이벤트(`started`, `thought_pending`, `AGENT_STREAM`, `step`, `evidence`, `confidence`, `proposal`, `completed`/`failed`)는 **동일 runId**를 키로 `run_store.put_event(run_id, event_type, payload)`로 큐에 넣음.
- **수명**: POST `/analysis-runs` 시 `get_or_create_queue(run_id)`로 큐 생성 → 백그라운드에서 `put_event` 반복 → `completed`/`failed` 수신 후 `finally`에서 **QUEUE_REMOVAL_DELAY_SEC(2초)** 대기 후 `remove_queue(run_id)` 호출.
- **체크포인트**: BE 프록시는 **202 수신 직후** GET `.../analysis/stream?runId=...`로 연결해야 함. 분석이 2초 안에 끝나면 큐가 삭제된 뒤 연결 시 **404**를 받을 수 있음. `thought_pending`/`AGENT_STREAM` 적재 여부는 로그 `run_store: put_event run_id=... event_type=...` (DEBUG 레벨)로 확인 가능.

### 9.2 runId 쿼리 파라미터 수신 및 검증

- **수신**: GET `/aura/cases/{caseId}/analysis/stream`에서 **runId**는 쿼리 스트링 필수. `coerce_case_run_id(runId)`로 문자열 정규화 후 `run_store.get_event(run_id, timeout=300)`에 전달.
- **runId 누락/빈 값**: **400** 응답, body `{"error": "runId is required", "runId": null}`. 빈 스트림을 보내지 않음.
- **runId 없음 또는 이미 완료**: **404** 응답, body `{"error": "runId not found or already completed", "runId": "<runId>"}`. 200 + JSON 에러가 아님.

### 9.3 SSE yield 루프 안정성

- **get_event 타임아웃**: 기본 300초. 이벤트가 오지 않으면 `get_event`가 `None`을 반환하고, 스트림은 `data: [DONE]\n\n` 전송 후 종료. 타임아웃으로 인해 스트림이 끊기지 않고 정상 종료됨.
- **event 헤더**: `format_sse_line(event_type, payload)`가 `event: {event_type}\ndata: {JSON}\n\n` 형태로 생성. `event_type`은 그대로 사용되므로 `AGENT_STREAM`, `thought_pending`, `step` 등이 올바르게 전송됨.

### 9.4 REST Push와의 관계

- **POST /api/synapse/agent/events**: 파이프라인에서 `thought_pending`/`AGENT_STREAM`/`step` 발생 시 **동일 내용**을 REST로 푸시하여 agent_activity_log 등에 저장. SSE와 **별도 경로**.
- **점검 순서**: DB(agent_activity_log)에는 이벤트가 있는데 SSE만 비어 있다면 → run_store와 put_event 연결(동일 runId 사용 여부, 큐 삭제 시점)을 집중 점검.

---

## 10. 참조 구현 위치 (Aura)

| 역할 | 경로 |
|------|------|
| 스트림 라우트 | `api/routes/aura_cases.py` — `GET /{case_id}/analysis/stream` |
| SSE 헤더·포맷 | `api/sse_utils.py` — `SSE_HEADERS`, `format_sse_line()` |
| 이벤트 스키마 | `core/analysis/audit_analysis_events.py` |
| 파이프라인(이벤트 발생 순서) | `core/analysis/audit_analysis_pipeline.py` |
| 이벤트 큐 (runId별) | `core/analysis/run_store.py` — put_event, get_event, remove_queue |

---

## 11. 다른 시스템에 공유할 내용 (FE·백엔드 전달용)

| 대상 | 공유 내용 |
|------|-----------|
| **FE** | ① **이벤트 타입 일치**: `thought_pending`, `AGENT_STREAM`, `step`, `data: [DONE]` 수신 대기. ② **thought_pending**: `{"step_label","message":"생각 중..."}` 수신 시 스켈레톤·"생각 중..." 표시. ③ **AGENT_STREAM**: `{"content":"추론문장", ...}` 수신 시 해당 문장으로 전환; `content` 내 `****금액****`, `**제n조**` 등 마크다운 강조는 인하우스 렌더러 지원. ④ **step**: 기술적 단계 완료(진행률 등). ⑤ **ID 매핑**: 페이로드의 `chunk_id`, `target_buzei`가 있으면 해당 전표 행에 Red Glow 등 하이라이트 적용. ⑥ **스트림 종료**: `data: [DONE]` 수신 시 스트림 종료로 간주. |
| **백엔드(프록시)** | 위 이벤트 타입·페이로드를 그대로 FE에 중계. `event:` 라인과 `data:` JSON을 변경하지 말 것. `data: [DONE]\n\n` 전까지 이벤트 순서 유지. |
| **Aura 엔진** | `reasoning_history`로 이전 단계 독백과 연속된 문장 생성; 독백 문장에 금액·조항 마크다운 강조 적극 포함; 모든 관련 이벤트 페이로드에 `chunk_id`, `target_buzei`(및 `doc_id`, `item_id`) 포함. |

---

## 12. 변경 이력

| 날짜 | 내용 |
|------|------|
| 2026-02-23 | §9 엔진 내부 스트림 큐(run_store) 및 runId 점검 추가. runId 누락 시 400, 큐 없음 시 404 반환. put_event 로깅(DEBUG), format_sse_line event_type 규격 명시. |
| 2026-02-23 | 이벤트 타입 정규화: `thought_pending`, `AGENT_STREAM`, `step`, `[DONE]` 명시. AGENT_STREAM 스키마(content, step_label, chunk_id, target_buzei) 추가. ID 매핑(chunk_id, target_buzei) 페이로드 포함. FE·백엔드 전달용 §11 추가. |
| 2026-02 | 최초 스펙 고정 (엔드포인트, 헤더, 이벤트 타입·스키마, `\n\n` 경계, failed 스키마, 재현 절차). |
