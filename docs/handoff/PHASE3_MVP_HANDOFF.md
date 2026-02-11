# Phase3 MVP 구현 완료 — 시스템별 공유 사항

> 구현 기준: PHASE3_SPEC.md, PHASE3_MVP_PLAN.md

---

## 전달 요약 (각 시스템에 복사해 전달용)

### ▶ BE (dwp-backend) 팀에 전달

```
[Phase3 Aura 분석 연동 안내]

Phase3 분석 트리거/콜백이 적용되었습니다.

■ 트리거 (BE → Aura)
  - POST /aura/internal/cases/{caseId}/analysis-runs
  - Authorization: Bearer <token> 필수 (Phase2와 동일)
  - Body: runId, caseId, requestedBy, artifacts, callbacks, options
  - 즉시 202 응답: { accepted: true, runId, streamPath }
  - streamPath는 FE 스트림 URL로 전달 (GET /aura/cases/{caseId}/analysis/stream?runId=...)

■ 콜백 (Aura → BE)
  - 요청 시 보낸 callbacks.resultCallbackUrl 로 POST
  - Header: Authorization: Bearer { callbacks.auth.token }
  - 성공 시 Body: runId, caseId, status: "COMPLETED", analysis{}, proposals[], meta{}
  - 실패 시 Body: runId, caseId, status: "FAILED", error
  - ※ Phase2와 스키마 상이: finalResult가 아닌 analysis + proposals + meta 구조

Phase3 전용 콜백 엔드포인트를 두고, 해당 URL을 resultCallbackUrl에 넣어 호출해 주시면 됩니다.
```

### ▶ FE (dwp_frontend) 팀에 전달

```
[Phase3 분석 스트림 안내]

Phase3 분석 시 스트림은 Phase2와 동일 URL을 사용합니다.

■ 스트림
  - GET /aura/cases/{caseId}/analysis/stream?runId={runId}
  - BE가 트리거 후 받은 streamPath를 그대로 사용

■ 이벤트 (Phase3)
  - started  : { runId, status: "started" }
  - step     : { label, detail, percent }
  - agent    : { agent, message, percent }  ← Phase3 추가
  - completed: { runId, status: "completed" }
  - failed   : { runId, status: "failed", error, retryable }

※ Phase2의 evidence, confidence, proposal 이벤트는 Phase3 스트림에서는 없습니다.
  최종 결과는 BE가 콜백으로 저장하므로, 분석/제안 탭은 기존처럼 BE API로 조회하면 됩니다.
```

### ▶ Aura/운영 참고

```
Phase3 MVP 반영 사항:
- POST /aura/internal/cases/{caseId}/analysis-runs (인증 필수)
- 스트림은 기존 GET .../analysis/stream?runId= 동일, 이벤트만 started/step/agent/completed/failed
- 콜백은 요청 시 받은 resultCallbackUrl + auth 로만 전송 (설정 파일 callback_path와 무관)
```

---

## 1. BE (dwp-backend) 상세

### Trigger 호출

- **Method/URL**: `POST /aura/internal/cases/{caseId}/analysis-runs`
- **인증**: Aura 플랫폼 전역 인증 사용. **Authorization: Bearer &lt;token&gt;** 필수 (기존 Phase2와 동일한 게이트웨이/토큰 정책 적용).
- **즉시 응답**: `202 Accepted`, body:
  - `accepted`: true
  - `runId`: 요청 시 보낸 runId
  - `streamPath`: `/aura/cases/{caseId}/analysis/stream?runId={runId}` (FE 스트림 URL)

### Request Body

- `runId`, `caseId`, `requestedBy`, `artifacts`, `callbacks`, `options` (스펙 §A와 동일).
- `callbacks.resultCallbackUrl`: **Aura가 분석 완료/실패 시 POST하는 URL** (BE가 제공).
- `callbacks.auth`: `{ "type": "BEARER", "token": "..." }` — Aura가 해당 URL로 콜백할 때 사용할 인증. BE가 발급한 토큰 또는 서비스 간 시크릿 등.

### Callback 수신

- **URL**: 요청 시 BE가 준 `callbacks.resultCallbackUrl` 로 **POST**.
- **Headers**: `Authorization: Bearer {callbacks.auth.token}` (auth가 있는 경우).
- **Body (COMPLETED)**: `runId`, `caseId`, `status: "COMPLETED"`, `analysis` (score, severity, reasonText, evidence, ragRefs), `proposals[]`, `meta` (promptVersion, model, temperature).
- **Body (FAILED)**: `runId`, `caseId`, `status: "FAILED"`, `error`.

BE는 기존 Phase2 콜백 경로와 별도로, Phase3 전용 콜백 엔드포인트를 두고 `resultCallbackUrl`에 그 주소를 넣어주면 됩니다. 콜백 스키마는 Phase2 `finalResult`가 아닌 **analysis + proposals + meta** 구조입니다.

---

## 2. FE (dwp_frontend) 공유

### 스트림 연결

- **URL**: `GET /aura/cases/{caseId}/analysis/stream?runId={runId}` (Phase2와 동일 경로).
- Phase3 런의 경우에도 동일 스트림 URL 사용. Trigger 응답의 `streamPath`를 그대로 사용하면 됨.

### 이벤트 타입 (Phase3)

- `started`: `{ runId, status: "started" }`
- `step`: `{ label, detail, percent }` (예: Normalize evidence 20%, RAG Retrieve 55%, …)
- `agent`: `{ agent, message, percent }` (예: PolicyAgent, 메시지, 70%)
- `completed`: `{ runId, status: "completed" }`
- `failed`: `{ runId, status: "failed", error, retryable }`

Phase2의 `evidence`, `confidence`, `proposal` 이벤트는 Phase3 스트림에서는 사용하지 않습니다. 최종 결과는 **콜백**으로 BE에 저장되며, FE는 분석/제안 탭에서 BE API를 통해 조회하면 됩니다.

---

## 3. Aura-Platform 내부 정리

- **Trigger**: `api/routes/aura_internal.py` — `POST /aura/internal/cases/{caseId}/analysis-runs`
- **Pipeline**: `core/analysis/phase3_pipeline.py` — Normalize Evidence → RAG Retrieve → Scoring/reasonText → Proposals → (콜백 페이로드 생성)
- **Callback 전송**: `core/analysis/phase3_callback.py` — `resultCallbackUrl` + auth 로 POST
- **스트림**: 기존 `GET /aura/cases/{caseId}/analysis/stream?runId=` 그대로 사용, Phase3 이벤트(started/step/agent/completed/failed)만 추가로 발생

RAG는 MVP에서 artifacts(policies, documents, openItems, fiDocument)를 청킹해 topK만 반환하며, 벡터 DB 없이 동작합니다. 필요 시 이후 Pinecone 등 연동으로 확장 가능합니다.

---

## 4. 체크리스트 (테스트 Gate)

- [ ] Trigger는 즉시 202 ack (Feign 블로킹 금지)
- [ ] FE SSE 접속 시 step/agent 이벤트가 충분히 흐름 (빈 스트림 금지)
- [ ] completed 후 BE가 콜백 수신 → 저장 → FE 분석/제안 탭에서 확인 가능

이 문서는 Phase3 MVP 구현 완료 시점의 시스템별 공유용입니다. 추가 연동 이슈가 있으면 handoff 문서에 보완해 두시면 됩니다.
