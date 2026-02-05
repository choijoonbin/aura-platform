# Phase A: Finance Agent E2E 검증

> **목표**: 케이스 처리 단계에서 Agentic의 핵심(도구사용/상태유지/승인게이트/감사)을 런타임으로 증명  
> **Phase 0 스키마 준수**: 이벤트 타입+payload, trace/tenant/user/case 필수, Synapse Tool API 계약

---

## 1. 구현 범위 (Phase A)

### 1.1 caseId 입력 → evidence_refs 3종 이상 생성

- **evidence_gather 노드** (`domains/finance/agents/finance_agent.py`)
  - caseId가 있으면 `get_case`, `search_documents`, `get_open_items` 호출
  - 결과를 `evidence_refs` 형식으로 state에 저장
  - 3종: case, documents, open_items

### 1.2 analysis/plan 이벤트에 evidence_refs 포함

- **thought 이벤트**: `metadata.evidence_refs` 배열
- **plan_step 이벤트**: `metadata.evidence_refs` 배열
- **코드 근거**: `domains/finance/agents/hooks.py` — analysis, evidence_gather, plan 노드

### 1.3 hitl_proposed 이벤트에 proposal payload 포함

- **hitl 이벤트**: `data.proposal` = toolArgs (caseId, actionType, payload)
- **코드 근거**: `api/routes/finance_agent.py` — `hitl_event.data["proposal"] = proposal_payload`

### 1.4 approve/reject 이벤트 수신 후 resume 또는 종료

- **승인**: `resume_value = {"approved": True}` → execute_action 등 계속
- **거절**: `resume_value = {"approved": False}` → ToolMessage("사용자가 거절했습니다") → reflect → end

---

## 2. 이벤트 흐름 (1개 케이스 실행 로그)

```
start
  → thought (analysis)
  → thought (evidence_gather, evidence_refs 3종)
  → thought (planning, evidence_refs)
  → plan_step (evidence_refs)
  → thought (reasoning)
  → tool_execution (get_case, search_documents, get_open_items 등)
  → [hitl] (proposal payload 포함)
  → [승인/거절 수신]
  → [승인 시] tool_execution (propose_action, execute_action)
  → content
  → end
  → [DONE]
```

---

## 3. 검증 시나리오

### 3.1 단계별 이벤트 확인

1. `POST /agents/finance/stream` — body: `{"prompt": "...", "context": {"caseId": "case-001"}}`
2. 수신 이벤트 관찰:
   - `event: start`
   - `event: thought` (analysis)
   - `event: thought` (evidence_refs 3종 — case, documents, open_items)
   - `event: thought` (planning, evidence_refs)
   - `event: plan_step` (metadata.evidence_refs)
   - `event: tool_execution` (도구 실행)
   - `event: hitl` (proposal payload 포함)
3. 승인/거절 후 resume 또는 종료 확인

### 3.2 BE audit_event_log 연계

- `caseId`로 관련 이벤트 조회
- SCAN_STARTED, SCAN_COMPLETED, DETECTION_FOUND, RAG_QUERIED, REASONING_COMPOSED, ACTION_PROPOSED, ACTION_APPROVED, ACTION_EXECUTED

---

## 4. Definition of Done

- [x] 1개 케이스 실행 로그로 단계별 이벤트 + hitl_proposed + resume 확인
- [x] evidence_refs 3종 이상 생성 (case, documents, open_items)
- [x] analysis/plan 이벤트에 evidence_refs 포함
- [x] hitl_proposed 이벤트에 proposal payload 포함
- [ ] BE audit_event_log에서 caseId로 관련 이벤트 조회 (Synapse 연동 시)
