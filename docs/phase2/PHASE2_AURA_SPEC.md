# Phase2 Aura 케이스 분석 오케스트레이션 (aura.txt)

> **대상**: aura-platform  
> **작성일**: 2026-02-06  
> **출처**: /Users/joonbinchoi/Downloads/aura.txt

---

## 1. Phase2 목표

케이스 1건을 대상으로 사용자가 **분석 시작** → AI 분석 → 권고 → (시뮬레이션/승인/실행) 흐름을 끝까지 수행할 수 있고,  
모든 단계가 감사로그로 추적 가능해야 함.

---

## 2. 스트림 이벤트 (최소)

| event | payload |
|-------|---------|
| started | `{runId, caseId, at}` |
| step | `{label, detail, percent}` |
| evidence | `{type, items: [...]}` |
| confidence | `{anomalyScore, patternMatch, ruleCompliance, overall}` |
| proposal | `{type, riskLevel, rationale, requiresApproval, payload}` |
| completed | `{summary, score, severity}` |
| failed | `{error, stage}` |

---

## 3. 분석 파이프라인

1. **Step1**: 입력 정규화 (evidence json schema 통일)
2. **Step2**: 간단 룰 스코어링 (금액, 거래처 신규, 역분개 체인 등)
3. **Step3**: LLM 호출로 reasonText 생성
4. **Step4**: proposals 생성 (PAYMENT_BLOCK, REQUEST_INFO 등)
5. **Step5**: 결과 payload 구성 후 BE 콜백 (선택)

---

## 4. RAG/유사케이스 (Phase2 최소)

- **RAG**: 정책 문서/가이드 없으면 빈 배열 + reason
- **Similar**: 벡터DB 없으면 키 기반(거래처/금액/유형) topK 0~3

---

## 5. API

| Method | Path | 설명 |
|--------|------|------|
| POST | `/aura/cases/{caseId}/analysis-runs` | **Phase2-2** 분석 트리거, 202 + JSON (Feign 호환) |
| GET | `/aura/cases/{caseId}/analysis/stream?runId=` | **Phase2-2** SSE 스트림 (started/step/.../completed) |
| POST | `/aura/cases/{caseId}/analysis/trigger` | legacy SSE 트리거 |
| GET | `/aura/cases/{caseId}/analysis` | reasonText, proposals, confidenceBreakdown 반환 |

---

## 6. DoD 체크리스트

- [x] started→(step/evidence/proposal)→completed 이벤트 생성
- [x] finalResult에 reasonText/proposals 비어있지 않음
- [ ] BE 콜백 실패 시 재시도 3회 + 실패 로그 (선택)
- [x] DEMO_OFF 시 no-op/차단
