# 백엔드 Phase2 202 표준화 및 proposal 멱등성

> **작성일**: 2026-02-06  
> **출처**: 백엔드 팀 공유  
> **목적**: Aura 연동 시 참고용 BE API 계약

---

## 1. BE 변경 요약

| 항목 | 내용 |
|------|------|
| **202 표준** | POST analysis-runs → 202 Accepted |
| **runId 기반 조회** | analysis, action-proposals에 runId 쿼리 파라미터 |
| **proposal 멱등성** | dedup_key로 중복 제거 (BE가 계산) |
| **analysis-runs 목록** | GET analysis-runs?latest=true |

---

## 2. API 계약

### 2.1 POST /api/synapse/cases/{caseId}/analysis-runs
- **응답**: 202 Accepted
- **Body**: runId, status=STARTED, streamUrl, startedAt(optional)

### 2.2 GET /api/synapse/cases/{caseId}/analysis?runId={runId}
| runId | 동작 |
|-------|------|
| 있음 | 해당 run 결과만 반환 |
| 없음 | 최신 completed run 결과 반환 (기존) |

### 2.3 GET /api/synapse/cases/{caseId}/action-proposals?runId={runId}
| runId | 동작 |
|-------|------|
| 있음 | 해당 run의 proposals만 반환 |
| 없음 | (기존 동작) |

### 2.4 GET /api/synapse/cases/{caseId}/analysis-runs?latest=true
| latest | 응답 |
|--------|------|
| true | 최신 runId만 `{ runId: "..." }` |
| 없음 | run 목록 반환 |

---

## 3. Proposal 멱등성 (BE)

- **dedup_key**: `sha256(lower(type)|canonicalize(payload)|normalize(rationale))`
- **제약**: UNIQUE(case_id, run_id, dedup_key)
- **Aura 역할**: type, payload, rationale 원본만 전송 (dedup_key는 BE가 계산)
- **콜백 재전송**: 동일 (runId, proposal) 재전송 시 BE dedup으로 안전 처리

---

## 4. Aura 연동 확인

| 항목 | Aura 상태 |
|------|----------|
| 콜백 payload | type, riskLevel, rationale, payload, createdAt 제공 |
| dedup_key | BE가 계산 → Aura 전송 불필요 |
| runId | 콜백 시 runId 포함 |

---

*BE 재기동 시 V34 마이그레이션 적용됨*
