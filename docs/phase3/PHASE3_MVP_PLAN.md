# Phase3 MVP 구현 계획 (2주)

> **참조**: PHASE3_SPEC.md

---

## 1. 엔드포인트

| 작업 | 내용 | 비고 |
|------|------|------|
| [ ] Trigger | POST /aura/internal/cases/{caseId}/analysis-runs | artifacts, callbacks, options 수신 |
| [ ] Stream | GET /aura/cases/{caseId}/analysis/stream?runId= | event: agent 추가, step 라벨 정합 |

Phase2 경로와 병행 유지 여부는 BE 연동 정리 후 결정.

---

## 2. 스트리밍 이벤트

| event | Phase2 | Phase3 |
|-------|--------|--------|
| started | runId, caseId, at | runId, status |
| step | label, detail, percent | 동일 |
| agent | 없음 | agent, message, percent |
| evidence | type, items | (analysis 내 evidence로 이동 가능) |
| completed | status, runId, caseId, summary, score, severity | runId, status |
| failed | error, stage | runId, status, error, retryable |

---

## 3. 파이프라인 (MVP)

| 단계 | 구현 포인트 |
|------|-------------|
| Normalize Evidence (20%) | artifacts.fiDocument, openItems, documents 없어도 evidence 구성 |
| RAG Retrieve (55%) | policies/documents/openItems/fiDocument → chunking → topK, ragRefs(refId, sourceType, sourceKey, excerpt, score) |
| Scoring + reasonText (70%) | 기존 룰 점수 + LLM reasonText (low temp) |
| Proposals (85%) | 룰 후보 + LLM rationale/riskLevel/체크리스트, fingerprint |
| Callback | callbacks.resultCallbackUrl + auth, analysis/proposals/meta 스키마 |

---

## 4. RAG

| 항목 | 내용 |
|------|------|
| 입력 | artifacts.policies, documents, openItems, fiDocument |
| Chunking | 텍스트 추출 후 청킹 (토큰/문단 기준) |
| Retrieve | topK (options.ragTopK), 유사도 검색 |
| 출력 | ragRefs[]: refId, sourceType, sourceKey, excerpt, score (최소 1~2건) |

Pinecone/벡터 DB 연동 여부는 환경에 따라 결정.

---

## 5. 콜백

| 항목 | 내용 |
|------|------|
| URL | request.callbacks.resultCallbackUrl |
| 인증 | request.callbacks.auth (BEARER token) |
| Body | status, analysis{}, proposals[], meta{} (PHASE3_SPEC §D) |

---

## 6. 체크리스트

- [ ] Trigger 즉시 ack
- [ ] Stream에 step/agent 이벤트 충분히 출력
- [ ] completed 후 callback 성공 → BE 저장 → FE에서 확인
