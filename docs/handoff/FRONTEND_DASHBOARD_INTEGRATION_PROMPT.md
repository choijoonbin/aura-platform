# Frontend 프롬프트 — SynapseX UI: 대시보드 완전 연동 + 드릴다운 표준

> **대상**: Frontend (React + TanStack Query)  
> **목표**: 대시보드 mock 제거, API 연동, 드릴다운 라우팅 표준화

---

## 1. API 연동

### 기존 3개 (유지)
- `/api/synapse/dashboard/summary`
- `/api/synapse/dashboard/top-risk-drivers`
- `/api/synapse/dashboard/action-required`

### 신규 2개 (추가)
- `/api/synapse/dashboard/team-snapshot`
- `/api/synapse/dashboard/agent-stream` 또는 `/api/synapse/dashboard/agent-activity` (동일 API)

**참고**: `agent-execution-stream`은 미구현. `agent-stream` 또는 `agent-activity` 사용.
- 예: `GET /api/synapse/dashboard/agent-stream?range=6h&limit=50`

**Gateway**: `/api/aura/dashboard/*` 프록시로 동일 API 제공.

### Mock 처리
- mock 데이터 제거 또는 `devOnly` 플래그로만 유지

---

## 2. 드릴다운 라우팅 (표준)

| 클릭 대상 | 이동 경로 |
|-----------|-----------|
| Open Cases by Severity | `/cases?severity=CRITICAL,HIGH&status=OPEN,TRIAGED&range=24h` |
| Top Risk Drivers bar | `/anomalies?type={TYPE}&range=24h` |
| Action Required row (Review) | `/cases/{caseId}` 또는 `/cases?ids={caseId}` |
| Team Snapshot row | `/cases?assigneeUserId={userId}&range=7d` |
| Agent Stream "View Full Audit Log" | `/audit?category=AGENT&range=24h` 또는 `type=SCAN,DETECT,ANALYZE,SIMULATE,EXECUTE` (stage별 필터) |

---

## 3. 필터 파라미터 표준 (계약 v1.0)

### 공통 유틸
- `filters/schema.ts` — enum + allowedKeys
- `filters/parse.ts` — URL → state
- `filters/serialize.ts` — state → URL

### 규칙
- 다중값: comma-separated
- `range` vs `from/to` 상호 배타
- `filtersApplied` 칩 UI: `/cases`, `/anomalies`, `/actions` 동일 패턴

### 우선순위
- `/anomalies`, `/actions` 상단에 "Applied Filters" 섹션 추가
- 칩 클릭 시 필터 제거 → URL 업데이트 → Query refetch

---

## 4. queryKeys.ts 정리

- `CASES_ALLOWED_KEYS`에 `caseKey` 포함
- `/anomalies`, `/actions` 동일 패턴 `ALLOWED_KEYS` 정의
- QueryKey: `(tenantId, route, normalizedFilters)` 형태

---

## 5. Agent 실행 스트림 UX

- **실시간**: 10초 폴링 또는 `refetchInterval: 5000~10000`
- **Row 클릭**:
  - `caseId` 있으면 → Case Detail
  - `traceId`/`gatewayRequestId` 있으면 → `/audit?...` (필터 포함)
- **빈 상태/로딩/에러**: API 미응답, 401/403/500 표준 처리

---

## 6. 백엔드 확인 결과 (2026-02)

| 항목 | 결과 |
|------|------|
| **agent-stream** | `agent-stream`, `agent-activity` 사용. `agent-execution-stream` 미구현. |
| **/audit category=AGENT** | 지원됨 |
| **/audit type** | `EXECUTION_EVENT` 미지원. 사용 가능: `SCAN`, `DETECT`, `ANALYZE`, `SIMULATE`, `EXECUTE` |

**Agent 실행 이벤트 조회 예시:**
- `?category=AGENT` — AGENT 전체
- `?category=AGENT&type=EXECUTE` — 실행 단계만
- `?category=AGENT&type=SCAN,DETECT,ANALYZE,SIMULATE,EXECUTE` — 모든 stage

---

## 7. 백엔드 확인 결과 (2026-02)

### Cases API: caseId vs caseKey

| 파라미터 | 지원 | 용도 |
|----------|------|------|
| caseKey | ✅ | CS-2026-0001 형식 (`/cases?caseKey=CS-123`) |
| ids | ✅ | 숫자 ID 목록 (`/cases?ids=123` 또는 `ids=123,456`) |
| caseId | ❌ | 쿼리 파라미터 미지원 |

| 경로 | 지원 |
|------|------|
| `/cases/{caseId}` | ✅ 상세 조회 |
| `/cases?caseId=123` | ❌ 미지원 |
| `/cases?ids=123` | ✅ 목록 필터 |
| `/cases?caseKey=CS-123` | ✅ 목록 필터 |

**권장**: 단건 `/cases/{caseId}` 또는 `/cases?ids={caseId}`. 표시용 키는 `caseKey`.

### Anomalies API: type

| 항목 | 지원 |
|------|------|
| type=DUPLICATE_INVOICE | ✅ |
| type=BANK_CHANGE_RISK, POLICY_VIOLATION 등 | ✅ |
| range=24h | ✅ |

예: `/anomalies?type=DUPLICATE_INVOICE&range=24h`

### CaseStatus: TRIAGE

| 항목 | 지원 |
|------|------|
| status=OPEN,TRIAGED | ✅ |
| status=OPEN,TRIAGE | ⚠️ TRIAGE 미지원 (TRIAGED 사용) |

**권장**: `status=OPEN,TRIAGED` (TRIAGE 대신 TRIAGED)

---

## 8. 프론트엔드 전달 요약

### API
- 기존: summary, top-risk-drivers, action-required
- 신규: team-snapshot, agent-stream (또는 agent-activity)
- agent-execution-stream 미구현 → agent-stream 사용

### 드릴다운 경로
- Open Cases: `status=OPEN,TRIAGED` (TRIAGE 아님)
- Cases 상세: `/cases/{caseId}` 또는 `/cases?ids={caseId}` (caseId 쿼리 파라미터 미지원)
- Anomalies: `/anomalies?type=DUPLICATE_INVOICE&range=24h` 등
- Team Snapshot: `/cases?assigneeUserId={userId}&range=7d`
- View Full Audit Log: `/audit?category=AGENT&range=24h`

### Cases API 파라미터
- caseId: 쿼리 파라미터 미지원
- ids, caseKey: 지원

### Anomalies API
- type=DUPLICATE_INVOICE, BANK_CHANGE_RISK 등 지원

### Audit API
- category=AGENT 지원
- type=EXECUTION_EVENT 미지원 → SCAN, DETECT, ANALYZE, SIMULATE, EXECUTE 사용
