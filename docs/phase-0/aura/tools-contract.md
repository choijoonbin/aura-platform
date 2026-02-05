# Aura Synapse Tool API 계약 (Phase 0)

> **목적**: Finance Agent 도구 호출 표준화, evidence_refs 생성 규칙  
> **근거**: `tools/synapse_finance_tool.py`, Synapse 백엔드 Tool API  
> **원칙**: caseId 입력 → 관련 데이터 조회 → evidence_refs 생성

---

## 1. 호출 표준

모든 Synapse Tool API 호출 시:

| 헤더 | 필수 | 설명 |
|------|------|------|
| X-Tenant-ID | ✅ | 테넌트 ID |
| X-User-ID | ✅ | 사용자 ID |
| X-Trace-ID | ✅ | 요청 추적 ID |
| Authorization | ✅ | JWT Bearer 토큰 |
| X-Idempotency-Key | simulate/execute 시 | 중복 호출 방지 |

**코드 근거**: `core/context.py` → `get_synapse_headers()`, `tools/synapse_finance_tool.py:45-52`

---

## 2. Synapse Tool API 목록

### 2.1 get_case

케이스 상세 조회.

| 항목 | 내용 |
|------|------|
| **경로** | `GET /tools/finance/cases/{caseId}` |
| **입력** | caseId (string) |
| **출력** | JSON: caseKey, riskTypeKey, score, documentIds, entityIds, openItemIds 등 |
| **Audit** | DETECTION_FOUND (riskTypeKey, score 있을 때) |

**코드 근거**: `tools/synapse_finance_tool.py:136-171`

---

### 2.2 search_documents

문서 검색.

| 항목 | 내용 |
|------|------|
| **경로** | `POST /tools/finance/documents/search` |
| **입력** | filters: { caseId?, documentIds?, dateRange?, topK? } |
| **출력** | JSON: 문서 목록 (docIds, metadata 등) |
| **Audit** | RAG_QUERIED (docIds, topK, latencyMs) |

**코드 근거**: `tools/synapse_finance_tool.py:174-214`

---

### 2.3 get_document

단일 문서 조회.

| 항목 | 내용 |
|------|------|
| **경로** | `GET /tools/finance/documents/{bukrs}/{belnr}/{gjahr}` |
| **입력** | bukrs, belnr, gjahr |
| **출력** | JSON: 문서 상세 |

**코드 근거**: `tools/synapse_finance_tool.py:217-233`

---

### 2.4 get_entity

엔티티 조회.

| 항목 | 내용 |
|------|------|
| **경로** | `GET /tools/finance/entities/{entityId}` |
| **입력** | entityId |
| **출력** | JSON: 엔티티 상세 |

**코드 근거**: `tools/synapse_finance_tool.py:236-248`

---

### 2.5 get_open_items

미결 항목 조회.

| 항목 | 내용 |
|------|------|
| **경로** | `POST /tools/finance/open-items/search` |
| **입력** | filters: { openItemIds?, entityId?, caseId? } |
| **출력** | JSON: 미결 항목 목록 |

**코드 근거**: `tools/synapse_finance_tool.py:251-269`

---

### 2.6 get_lineage (P1: lineageRef)

데이터 계보(Lineage) 조회. evidence_refs 4번째 유형.

| 항목 | 내용 |
|------|------|
| **경로** | `GET /tools/finance/lineage` (또는 Synapse lineage API) |
| **입력** | caseId (string) |
| **출력** | JSON: lineage 배열 (원천 데이터 추적) |
| **evidence_refs** | type=lineage, source=get_lineage |

**코드 근거**: `tools/synapse_finance_tool.py`, `domains/finance/agents/finance_agent.py` evidence_gather

---

### 2.7 simulate_action

액션 시뮬레이션 (실행 없이 결과 확인).

| 항목 | 내용 |
|------|------|
| **경로** | `POST /tools/finance/actions/simulate` |
| **입력** | { caseId, actionType, payload }, X-Idempotency-Key |
| **출력** | JSON: result (PASS/FAIL), diffJson, actionId |
| **Audit** | SIMULATION_RUN |

**코드 근거**: `tools/synapse_finance_tool.py:272-326`

---

### 2.8 propose_action

액션 제안. **HITL 승인 필요.**

| 항목 | 내용 |
|------|------|
| **경로** | `POST /tools/finance/actions/propose` |
| **입력** | { caseId, actionType, payload } |
| **출력** | JSON: actionId, status 등 |
| **Audit** | ACTION_PROPOSED |
| **HITL** | propose_action 호출 시 interrupt → approve/reject → resume |

**코드 근거**: `tools/synapse_finance_tool.py:329-370`, `FINANCE_HITL_TOOLS = {"propose_action"}`

---

### 2.9 execute_action

승인 완료된 액션 실행.

| 항목 | 내용 |
|------|------|
| **경로** | `POST /tools/finance/actions/execute` |
| **입력** | { actionId }, X-Idempotency-Key |
| **출력** | JSON: sapRef, outcome, error? |
| **Audit** | ACTION_EXECUTED, SAP_WRITE_SUCCESS/FAILED |

**코드 근거**: `tools/synapse_finance_tool.py:373-450`

---

## 3. evidence_refs 생성 규칙

**원칙**: caseId 입력 → 관련 도구 호출 → evidence_refs 배열 생성

| evidence 유형 | 생성 도구 | 내용 |
|--------------|-----------|------|
| **case** | get_case | 케이스 상세 (riskTypeKey, score, caseKey) |
| **documents** | search_documents, get_document | 문서 목록/상세 (규정 인용, 원천 데이터) |
| **entity** | get_entity | 엔티티 정보 |
| **open_items** | get_open_items | 미결 항목 (통계 근거) |
| **lineage** | get_lineage | 데이터 계보 (원천 추적, P1) |
| **simulation** | simulate_action | 시뮬레이션 결과 (diffJson) |

**생성 시점**: analysis/plan 이벤트 발행 시, 도구 실행 결과를 evidence_refs로 정리하여 payload에 포함.

**Phase A 확장**: evidence_refs 3종 이상 생성 후 analysis/plan에 포함.

---

## 4. 재시도 정책

- **5xx, timeout**: exponential backoff (1, 2, 4초), 최대 `synapse_max_retries` 회
- **코드 근거**: `tools/synapse_finance_tool.py:55-116`

---

## 5. 실패 처리

- 도구 호출 실패 시: `tool_execution` status=FAILED, error 필드 포함
- 전체 실패/타임아웃 시: `error` 이벤트 발행 (침묵 금지)
- **코드 근거**: `api/routes/finance_agent.py` except 블록
