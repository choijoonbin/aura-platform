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

### 5.2 `step` (여러 번 발생)

진행 단계. **Phase2에서는 2개 이상** 발생 (INPUT_NORM, EVIDENCE_GATHER, RULE_SCORING, LLM_REASONING, PROPOSALS 등).

```json
{
  "label": "<단계 라벨, 예: INPUT_NORM | EVIDENCE_GATHER | RULE_SCORING | LLM_REASONING | PROPOSALS>",
  "detail": "<상세 메시지>",
  "percent": <0..100>
}
```

### 5.3 `evidence`

증거/문서 스니펫 (선택적, 단계별로 0회 이상).

```json
{
  "type": "<DOC_HEADER | DOC_ITEMS | OPEN_ITEMS | LINEAGE 등>",
  "items": [ ... ]
}
```

### 5.4 `confidence`

신뢰도 점수 (0회 또는 1회).

```json
{
  "anomalyScore": <float>,
  "patternMatch": <float>,
  "ruleCompliance": <float>,
  "overall": <float>
}
```

### 5.5 `proposal`

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

### 5.6 `completed`

정상 완료. 스트림은 이 이벤트 후 `data: [DONE]\n\n` 한 줄 더 보내고 종료.

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

### 5.7 `failed`

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

## 6. 스트림 종료

- **정상**: `event: completed` + `data: {...}` 전송 후, **`data: [DONE]\n\n`** 한 줄 전송 후 **즉시** 연결 종료.
- **실패**: `event: failed` + `data: {"error":"...","stage":"..."}` 전송 후, 동일하게 **`data: [DONE]\n\n`** 전송 후 연결 종료.
- **타임아웃/큐 제거**: 큐가 제거되면 스트림 측에서 fallback `completed` 또는 `[DONE]` 전송 후 종료.

**Aura가 [DONE] 다음에 보내는 데이터는 없음.**  
- Aura 코드: `yield "data: [DONE]\n\n"` 한 번만 수행 후 제너레이터 종료. 그 다음에 `yield` 하는 빈 줄(`\n`)이나 `data:\n` 같은 라인은 **없음**.
- 따라서 `data: [DONE]\n\n` 이후 Aura가 의도적으로 보내는 바이트는 0바이트임.
- [DONE] 뒤에 빈 payload 이벤트 1~2개가 보인다면, 가능한 원인은 (1) Starlette/uvicorn이 스트림 종료 시 빈 청크 또는 trailing flush를 보내는 경우, (2) Gateway가 `\n\n` 기준으로 블록을 나눌 때 연결 종료/버퍼 플러시 구간을 빈 블록으로 해석하는 경우.  
- **권장**: Gateway/프론트는 `data: [DONE]` 수신 시 **스트림 종료로 간주**하고, 이후 들어오는 빈 블록은 무시하거나 파싱하지 않음.

---

## 7. 필수 재현 (curl)

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

## 8. 참조 구현 위치 (Aura)

| 역할 | 경로 |
|------|------|
| 스트림 라우트 | `api/routes/aura_cases.py` — `GET /{case_id}/analysis/stream` |
| SSE 헤더·포맷 | `api/sse_utils.py` — `SSE_HEADERS`, `format_sse_line()` |
| 이벤트 스키마 | `core/analysis/phase2_events.py` |
| 파이프라인(이벤트 발생 순서) | `core/analysis/phase2_pipeline.py` |

---

## 9. 변경 이력

| 날짜 | 내용 |
|------|------|
| 2026-02 | 최초 스펙 고정 (엔드포인트, 헤더, 이벤트 타입·스키마, `\n\n` 경계, failed 스키마, 재현 절차). |
