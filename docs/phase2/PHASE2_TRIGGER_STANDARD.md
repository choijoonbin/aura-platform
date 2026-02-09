# Phase2 트리거 202 + 스트림/콜백 표준

> **작성일**: 2026-02-06  
> **목표**: Feign/HTTP 호환, SSE 분리, BE 콜백 기반 proposals/analysis 저장

---

## 1. 트리거 (202 즉시 반환)

**POST** `/aura/cases/{caseId}/analysis-runs`

### Request Body
| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| runId | string | ✅ | BE가 생성한 run 식별자 |
| caseId | string | - | (path와 중복 가능) |
| evidence | object | - | evidence snapshot |
| options | object | - | model, policyVersion 등 |

### Response (202)
```json
{
  "status": "ACCEPTED",
  "runId": "...",
  "caseId": "85114",
  "streamUrl": "/aura/analysis-runs/{runId}/stream"
}
```

- SSE를 직접 반환하지 않음
- streamUrl이 null인 경우: BE streamUrl 방식 사용 (계약 문서화)

---

## 2. 스트림 (runId 기반)

**GET** `/aura/analysis-runs/{runId}/stream`

- Content-Type: text/event-stream
- 이벤트: started → step → evidence → confidence → proposal → completed | failed

---

## 3. 콜백

**POST** `{DWP_GATEWAY_URL}/api/synapse/internal/aura/callback`

### Payload
- runId, caseId
- status: COMPLETED | FAILED
- finalResult (COMPLETED 시, flat 구조):
  - score, severity, reasonText, confidence, evidence, ragRefs, similar, proposals
  - proposals[]: type, riskLevel, rationale, payload, createdAt, requiresApproval

### 멱등성
- 동일 (runId, proposal) 재전송 시 BE dedup으로 안전 처리
- Aura는 최소 1회 이상 재전송 가능

---

## 4. 완료 기준

- [x] trigger는 SSE를 직접 반환하지 않음
- [x] 202 + runId 기반으로 BE/FE 끊김 없이 실행 가능
- [x] callback 기반으로 proposals/analysis 저장 가능
