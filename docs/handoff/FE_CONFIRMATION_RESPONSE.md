# front.txt 확인 요청 — Aura/BE 답변

> **대상**: 프론트엔드 팀  
> **작성일**: 2026-02-06  
> **출처**: Aura 팀 (BE 문의 항목은 BE 팀 확인 필요)

---

## 1. 백엔드 (Synapse) 서버 — BE 담당

### 1.1 action-proposals runId 없을 때 동작

**질문**: `GET /api/synapse/cases/{caseId}/action-proposals` (runId 쿼리 없음) 호출 시 응답은?

- [x] **최신 completed run의 proposals만 반환** (추정)
- [ ] 모든 run의 proposals 반환 (누적)
- [ ] 기타

**근거**: `BACKEND_PHASE2_202_STANDARD.md` §2.3 — runId 없을 때 "(기존 동작)". analysis와 동일 패턴으로 **최신 completed run 추정**. BE 최종 확인 권장.

---

### 1.2 analysis-runs latest=true, run이 없을 때

**질문**: 케이스에 analysis run이 하나도 없을 때 `GET .../analysis-runs?latest=true` 응답은?

- [ ] `{ data: { runId: null } }` 또는 `{ data: {} }`
- [ ] 404 또는 빈 배열
- [ ] **기타 — BE 확인 필요**

**Aura 의견**: Aura는 해당 API를 제공하지 않음. **BE에 문의** 필요.

---

### 1.3 analysis-runs 응답 스키마 (ApiResponse 래핑)

**질문**: `latest=true` 응답이 `ApiResponse` 래핑인지 확인.

- 예상: `{ status: "SUCCESS", data: { runId: "uuid-..." } }`
- latest 없음(목록): `{ status: "SUCCESS", data: { items: [...] } }` ?

**Aura 의견**: **BE에 문의** 필요. Aura는 analysis-runs 목록 API를 제공하지 않음.

---

### 1.4 evidenceSnapshot 요청 body 스키마

**질문**: `POST analysis-runs` body의 `evidenceSnapshot` 요구 구조는?

**Aura 답변** (BE→Aura 시 evidence 전달 기준):

- Aura 트리거 body: `evidence: dict[str, Any] | None` — **optional, 별도 스키마 강제 없음**
- FE가 `useCaseDetail().evidence` (documentOrOpenItem, reasonText 등) 그대로 전달해도 전달 가능
- 현재 Phase2 파이프라인은 내부에서 `get_case`, `search_documents` 등으로 증거를 수집하므로, body.evidence는 **선택적 enrichment용**
- **결론**: FE가 보내는 구조 그대로 BE가 Aura에 전달하면 Aura는 수용함. 별도 스키마 없음.

**BE 확인 필요**: FE→BE `POST analysis-runs` body의 `evidenceSnapshot` 필드명 및 스키마는 **BE spec**에 따름.

---

## 2. Aura 서버 — Aura 답변

### 2.1 status 필드 (STARTED vs ACCEPTED)

**질문**: POST analysis-runs 응답의 `data.status` 값은?

- [ ] `STARTED` (run 상태)
- [x] **`ACCEPTED`** (HTTP 202 의미)
- [ ] 기타

**Aura 실제 반환** (`api/routes/aura_cases.py`):

```json
{
  "status": "ACCEPTED",
  "runId": "...",
  "caseId": "85114",
  "streamUrl": "/aura/analysis-runs/{runId}/stream"
}
```

- **`ACCEPTED`** 사용. HTTP 202(수락됨)를 의미하며, run이 백그라운드에서 시작됨을 나타냄.

---

### 2.2 streamUrl 경로 형식

**질문**: 응답 `streamUrl` 값 형식 확인.

**Aura 답변**:

- Aura 반환값: `streamUrl: "/aura/analysis-runs/{runId}/stream"` (상대 경로)
- FE 사용 시: `{NX_API_URL}` + streamUrl
  - 예: `NX_API_URL = https://gateway.example.com/api` → `https://gateway.example.com/api/aura/analysis-runs/{runId}/stream`
  - 예: `NX_API_URL = https://gateway.example.com` → `https://gateway.example.com/aura/analysis-runs/{runId}/stream`
- **`/api/synapse/analysis-runs/{runId}/stream`로 변환할 필요 없음** — BE 스트림과 Aura 스트림은 다른 경로
  - BE 스트림: `GET /api/synapse/analysis-runs/{runId}/stream` (BE가 제공)
  - Aura 스트림: `GET /api/aura/analysis-runs/{runId}/stream` (Aura 직접, 상세 이벤트)

---

### 2.3 step 이벤트 지원 여부

**질문**: Aura 스트림에서 `event: step` 및 `data: { label, detail, percent }` 지원 여부?

- [x] **지원함**
- [ ] 미지원 (BE 스트림만 사용)
- [ ] 향후 지원 예정

**Aura 실제 구현** (`core/analysis/phase2_pipeline.py`, `core/analysis/phase2_events.py`):

- 이벤트 순서: `started` → `step` → `evidence` → `confidence` → `proposal` → `completed` | `failed`
- `event: step` 스키마: `{ "label": "EVIDENCE_GATHER", "detail": "증거 수집 중", "percent": 25 }`
- label 예: INPUT_NORM, EVIDENCE_GATHER, RULE_SCORING, LLM_REASONING, PROPOSALS

FE의 `step` 이벤트 기반 진행률 UI는 **Aura 스트림에서 그대로 사용 가능**합니다.

---

## 3. Gateway / Proxy — Gateway 담당

### 3.1 streamUrl 라우팅

**질문**: SSE 연결 시 사용할 URL 패턴의 라우팅 규칙.

| FE 요청 URL (예시) | 라우팅 대상 | 비고 |
|-------------------|------------|------|
| `{NX_API_URL}/api/synapse/analysis-runs/{runId}/stream` | BE (Synapse) | BE가 제공하는 스트림 (started, completed, failed) |
| `{NX_API_URL}/api/aura/analysis-runs/{runId}/stream` | Aura (9000) | Aura 상세 스트림 (step, evidence, confidence, proposal 포함) |

**권장 구성**:

- `/api/synapse/**` → BE (POST analysis-runs, analysis, action-proposals 등과 동일)
- `/api/aura/**` → Aura (9000) — Aura 상세 스트림 사용 시 필요

**FE가 BE 스트림만 사용**하면 `/api/aura/**` 프록시는 불필요.  
**Aura 상세 스트림**을 사용하려면 Gateway에 `/api/aura/**` → Aura 라우팅이 필요합니다.

---

## 4. 정리 (답변 후 체크)

| # | 항목 | 담당 | 상태 |
|---|------|------|------|
| 1.1 | action-proposals runId 없을 때 | BE | ✅ 최신 completed run만 |
| 1.2 | analysis-runs run 없을 때 | BE | ⬜ BE 확인 필요 |
| 1.3 | analysis-runs ApiResponse 스키마 | BE | ⬜ BE 확인 필요 |
| 1.4 | evidenceSnapshot 스키마 | Aura | ✅ dict, optional, 별도 스키마 없음 |
| 2.1 | status STARTED vs ACCEPTED | Aura | ✅ ACCEPTED |
| 2.2 | streamUrl 경로 형식 | Aura | ✅ `/aura/analysis-runs/{runId}/stream` |
| 2.3 | step 이벤트 지원 | Aura | ✅ 지원함 |
| 3.1 | streamUrl 라우팅 | Gateway | ⬜ `/api/aura/**` → Aura 필요 시 |

---

*작성: Aura 팀 | 참조: front.txt, BACKEND_PHASE2_202_STANDARD.md, FRONTEND_AURA_PHASE2_RESPONSE.md*
