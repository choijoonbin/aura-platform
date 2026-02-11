# DWP SynapseX Phase3 (AURA) 스펙

> **목적**: Phase3에서 Aura는 “진짜 AI/Agentic + RAG + 스트리밍 + BE 콜백” 책임  
> **기간**: 2주(MVP) + 4주(고도화)  
> **Phase2 대비**: 룰 기반 제안 → 룰 후보 + LLM 보정 + RAG 근거

---

## A. 필수 엔드포인트

### 1) Trigger (BE 호출, 즉시 ack만)

**POST** `/aura/internal/cases/{caseId}/analysis-runs`

| 구분 | 내용 |
|------|------|
| req | runId, caseId, requestedBy, **artifacts**, **callbacks**, options |
| artifacts | fiDocument, lineItems, openItems, parties, policies, documents |
| callbacks | resultCallbackUrl, auth (type, token) |
| options | ragTopK, temperature, promptVersion |
| res(즉시) | accepted, runId, streamPath |

**Request 예시**
```json
{
  "runId": "<uuid>",
  "caseId": 85115,
  "requestedBy": "userId",
  "artifacts": {
    "fiDocument": {},
    "lineItems": [],
    "openItems": [],
    "parties": {},
    "policies": [],
    "documents": []
  },
  "callbacks": {
    "resultCallbackUrl": "http://dwp-backend/api/synapse/internal/aura/callback",
    "auth": { "type": "BEARER", "token": "..." }
  },
  "options": { "ragTopK": 5, "temperature": 0.2, "promptVersion": "phase3-mvp-v1" }
}
```

**Response (즉시)**
```json
{
  "accepted": true,
  "runId": "...",
  "streamPath": "/aura/cases/{caseId}/analysis/stream?runId=..."
}
```

### 2) SSE Stream (FE 직접 연결)

**GET** `/aura/cases/{caseId}/analysis/stream?runId=...`

- 이벤트: `started` | `step` | `agent` | `completed` | `failed`

---

## B. 스트리밍 이벤트 표준(강제)

| event | payload |
|-------|---------|
| started | `{"runId":"...","status":"started"}` |
| step | `{"label":"Normalize evidence","detail":"","percent":20}` |
| agent | `{"agent":"PolicyAgent","message":"...","percent":70}` |
| completed | `{"runId":"...","status":"completed"}` |
| failed | `{"runId":"...","status":"failed","error":"...","retryable":true}` |

---

## C. Phase3 MVP 파이프라인 (2주)

| 단계 | percent | 내용 |
|------|---------|------|
| 1) Normalize Evidence | 20% | document 없어도 openItems/fiDocument 기반 evidence 구성 |
| 2) RAG Retrieve | 55% | policies/documents/openItems/fiDocument chunking 후 topK retrieve |
| 3) Scoring + reasonText | 70% | 룰 점수 활용 + LLM로 reasonText 생성 (temperature 낮게) |
| 4) Proposals | 85% | 룰 후보 + LLM rationale/riskLevel/체크리스트, fingerprint |
| 5) Callback | 95~100% | callbackUrl로 POST (멱등), 실패 시 FAILED + error |

**RAG ragRefs 최소 필드**: refId, sourceType, sourceKey, excerpt, score (MVP에서도 1~2개 반드시 반환)

---

## D. Callback Payload 스키마 (권장)

```json
{
  "runId": "...",
  "caseId": 85115,
  "status": "COMPLETED",
  "analysis": {
    "score": 72.0,
    "severity": "MEDIUM",
    "reasonText": "정책 위반 가능성이 있는 전표 조합입니다.",
    "evidence": [{"key":"중복 지급 의심"},{"key":"벤더 계좌 변경 직후 지급"}],
    "ragRefs": [
      {"refId":"ref-1","sourceType":"POLICY","sourceKey":"POLICY-AP-72H","excerpt":"...","score":0.83}
    ]
  },
  "proposals": [
    {
      "proposalId": "<uuid>",
      "type": "HOLD_PAYMENT",
      "status": "PROPOSED",
      "riskLevel": "MEDIUM",
      "rationale": "계좌 변경 72시간 룰 위반 가능",
      "payload": {"companyCode":"1000","docKey":"1000-1900000005-2024","reasonCode":"POLICY_72H_VENDOR_CHANGE"},
      "fingerprint": "hold_payment|1000|1000-1900000005-2024|policy_72h_vendor_change"
    }
  ],
  "meta": {"promptVersion":"phase3-mvp-v1","model":"gpt-4.x","temperature":0.2}
}
```

---

## E. Phase3 고도화 (Week 3~4)

- Multi-agent: EvidenceAgent / PolicyAgent / ActionAgent
- agent 이벤트로 에이전트별 사고 과정 스트림 출력
- RAG source 확장, excerpt 하이라이트 강화
- 제안 타입 확장: REQUEST_INFO, MANUAL_REVIEW, SET_PAYMENT_BLOCK(sim) 등

---

## F. 테스트 Gate

1. Trigger는 즉시 ack (Feign 블로킹 금지)
2. FE SSE 접속 시 step/agent 로그가 충분히 흐름 (“빈 스트림” 금지)
3. completed 후 callback으로 BE 저장 → FE 분석/제안 탭에서 확인 가능

---

## Phase2 vs Phase3 요약

| 항목 | Phase2 | Phase3 |
|------|--------|--------|
| Trigger path | /aura/cases/{caseId}/analysis-runs | /aura/internal/cases/{caseId}/analysis-runs |
| Input | runId, caseId, evidence | runId, caseId, artifacts, callbacks, options |
| Stream event | step, evidence, confidence, proposal | step, **agent**, completed/failed |
| RAG | BE search_documents | Aura chunking + topK retrieve, ragRefs 필드 강제 |
| Proposals | 룰만 | 룰 후보 + LLM rationale/fingerprint |
| Callback body | finalResult (flat) | analysis + proposals + meta |
