# Aura → 프론트엔드 Phase2 연동 전달 사항

> **대상**: 프론트엔드 팀  
> **배경**: front.txt 질문에 대한 Aura 관련 답변  
> **작성일**: 2026-02-06

---

## 1. FE가 Aura를 직접 호출하는가?

**아니요.** Phase2 분석 흐름은 **FE → BE → BE가 Aura 호출**입니다.

| 단계 | 호출 주체 | API |
|------|----------|-----|
| 1. 분석 트리거 | FE → BE | `POST /api/synapse/cases/{caseId}/analysis-runs` → 202 |
| 2. 스트림 구독 | FE → BE | `GET /api/synapse/analysis-runs/{runId}/stream` |
| 3. 분석 결과 조회 | FE → BE | `GET /api/synapse/cases/{caseId}/analysis?runId=` (runId 있으면 해당 run만) |
| 4. 액션 제안 | FE → BE | `GET /api/synapse/cases/{caseId}/action-proposals?runId=` (runId 있으면 해당 run만) |

**FE는 BE의 `/api/synapse/...` API만 사용**하면 됩니다. Aura는 BE 내부에서 호출됩니다.

---

## 2. Aura 직접 호출이 필요한 경우 (선택)

BE가 trigger 응답에 **streamUrl**을 담아 FE에 전달하는 경우, FE가 그 URL로 **Aura 상세 스트림**을 구독할 수 있습니다.

| 용도 | BE 스트림 | Aura 스트림 |
|------|----------|-------------|
| 경로 | `GET /api/synapse/analysis-runs/{runId}/stream` | `GET /api/aura/analysis-runs/{runId}/stream` |
| 이벤트 | started, completed, failed (단순) | started, step, evidence, confidence, proposal, completed (상세) |

**Aura 스트림 사용 시** (BE가 streamUrl로 전달할 때):
- FE 호출: `GET {DWP_HOST}/api/aura/analysis-runs/{runId}/stream`
- Gateway: `/api/aura/**` → Aura(9000) 프록시 필요
- DWP Host API 프록시에 `/api/aura/**` 경로가 Aura로 라우팅되면 됩니다.

---

## 3. DWP Host / Gateway 프록시

| 경로 | 대상 | 용도 |
|------|------|------|
| `/api/synapse/**` | BE (synapsex) | 분석 트리거, 스트림, 결과, 액션 제안 |
| `/api/aura/**` | Aura (9000) | Aura 스트림 직접 구독 (선택) |

FE가 **BE만** 사용한다면 `/api/aura/**` 프록시는 불필요합니다.  
Aura 상세 스트림(step, evidence, confidence, proposal)을 쓰려면 `/api/aura/**` 프록시를 추가하면 됩니다.

---

## 4. FE 수정 방향 (권장)

| 항목 | 현재 FE | 권장 |
|------|---------|------|
| 분석 트리거 | `POST /api/synapse/agent-tools/agents/finance/stream` | `POST /api/synapse/cases/{caseId}/analysis-runs` |
| 스트림 | 위 API에서 SSE 직접 수신 | `GET /api/synapse/analysis-runs/{runId}/stream` |
| 분석 결과 | `GET /api/synapse/cases/{caseId}/analysis` | 동일 (BE가 Aura에서 수집 후 반환) |
| 액션 제안 | case detail의 action.actions | `GET /api/synapse/cases/{caseId}/action-proposals` |
| 승인/거절 | `.../actions/{id}/approve`, `.../reject` | `.../action-proposals/{proposalId}/approve`, `.../reject` |

**결론**: FE는 **BE API**(back.txt 기준)에 맞춰 수정하는 것이 맞습니다. Aura는 BE와 연동되며 FE는 BE만 호출합니다.

---

## 5. Aura API (참고 – FE 직접 호출 시)

FE가 Aura를 직접 호출하는 구성(예: 스트림 URL 사용)일 때만 참고:

| Method | Path | 설명 |
|--------|------|------|
| POST | `/aura/cases/{caseId}/analysis-runs` | 분석 트리거 202+JSON (BE가 호출) |
| GET | `/aura/analysis-runs/{runId}/stream` | Aura 상세 SSE (runId 기반) |
| GET | `/aura/cases/{caseId}/analysis/stream?runId=` | Aura 상세 SSE (caseId 기반, legacy) |
| GET | `/aura/cases/{caseId}/analysis` | 분석 결과 |

---

## 6. 프론트 추가 질문 답변 (Aura 담당 3건)

### 6.1 BE 스트림 이벤트 형식 (started, completed, failed)

**BE 스트림**은 BE가 `case_analysis_run` 상태 폴링 기반으로 생성합니다. Aura는 해당 스트림을 정의하지 않습니다.

- **책임**: BE 정의
- **Aura 역할**: BE에 콜백(`POST /api/synapse/internal/aura/callback`)만 전송
- **확인 요청**: started, completed, failed의 data 필드 스키마는 **BE에 문의**

---

### 6.2 Aura 상세 스트림 이벤트 spec (step, evidence, confidence, proposal)

Aura 상세 스트림 `GET /api/aura/cases/{caseId}/analysis/stream?runId={runId}` 의 data JSON 예시:

**event: started**
```json
{
  "runId": "550e8400-e29b-41d4-a716-446655440000",
  "caseId": "85114",
  "at": "2026-02-06T12:00:00.000Z"
}
```

**event: step**
```json
{
  "label": "EVIDENCE_GATHER",
  "detail": "증거 수집 중",
  "percent": 25
}
```

**event: evidence**
```json
{
  "type": "COLLECTED",
  "items": [
    {"type": "CASE", "source": "get_case", "caseId": "85114", "keys": {"bukrs": "1000", "belnr": "1900000001", "gjahr": "2024"}},
    {"type": "DOC_HEADER", "source": "search_documents", "index": 0, "keys": {"caseId": "85114"}},
    {"type": "OPEN_ITEMS", "source": "get_open_items", "count": 3}
  ]
}
```

**event: confidence**
```json
{
  "anomalyScore": 0.45,
  "patternMatch": 0.7,
  "ruleCompliance": 0.85,
  "overall": 0.67
}
```

**event: proposal**
```json
{
  "type": "PAYMENT_BLOCK",
  "riskLevel": "HIGH",
  "rationale": "위험 점수에 따른 추가 검토 권고",
  "requiresApproval": true,
  "payload": {"caseId": "85114", "action": "block"}
}
```

**event: completed**
```json
{
  "summary": "케이스 85114: DUPLICATE_INVOICE 위험. 증거 4건 수집. 스코어 0.67.",
  "score": 0.67,
  "severity": "MEDIUM"
}
```

**event: failed**
```json
{
  "error": "Connection timeout",
  "stage": "pipeline"
}
```

---

### 6.3 DEMO_OFF 시 BE 처리

**Aura 반환**
- HTTP 200
- Body: `{"status": "disabled", "message": "Analysis disabled (DEMO_OFF)"}`

**BE 처리 방식**
- BE 설계 사항이며, Aura는 반환 형식만 정의합니다.
- **BE에 문의** 권장: run 상태 업데이트, FE 에러 메시지, graceful fallback 등
- back.txt 기준: BE `demo-mode=true` 시 Aura를 호출하지 않으므로, `DEMO_OFF` 응답은 BE가 demo 전용이 아닐 때 Aura를 호출한 경우에만 수신됩니다.

---

*작성: Aura 팀*
