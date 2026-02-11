# Log Alignment for Integrated Workbench

> **목표**: `dwp_aura.agent_activity_log`의 모든 로그가 특정 `case_id`와 연계되어 통합 워크벤치에서 '탐지-추론-조치' 타임라인으로 일관되게 표시되도록 보장.

---

## 1. Pre-Check 결과

### 1.1 `agent_activity_log`에 case_id 없이 기록되는 경우가 있는가?

**결론: 예. 다음 경우에 case_id가 비어 있을 수 있습니다.**

| 발생 위치 | 이벤트 | 원인 |
|-----------|--------|------|
| `tools/synapse_finance_tool.py` | **RAG_QUERIED** | `rag_queried()` 호출 시 evidence_json에 caseId 미포함. context에서도 보강하지 않음. |
| `core/audit/schemas.py` | **ACTION_PROPOSED** | `action_proposed()`는 caseKey만 optional로 받고, evidence_json에 caseId 파라미터 없음. (도구에서는 caseId 인자로 받지만 evidence에 안 넣음) |
| `api/routes/finance_agent.py` | **ACTION_APPROVED** | `action_approved()` 호출 시 case_id/caseKey 미전달. |
| `tools/synapse_finance_tool.py` | **SAP_WRITE_SUCCESS / SAP_WRITE_FAILED** | evidence_json에 caseId 없음. resource_type=INTEGRATION, resource_id=actionId만 있음. |
| `core/agent_stream/writer.py` | **모든 이벤트** | `case_id = ev.get("caseId") or (rid if rt == "CASE" else None)` 이므로, evidence에 caseId가 없고 resource_type이 CASE가 아니면 null. |
| `domains/finance/agents/hooks.py` | **SCAN_STARTED / SCAN_COMPLETED / REASONING_COMPOSED** | state.context에 caseId가 없으면 (예: case 없이 plan만 실행) case_id 없음. |

**조치**: 에이전트 활동 기록 시 `agent_case` PK와 매핑되도록, (1) Audit 이벤트 생성 시 context의 case_id를 evidence_json에 반영하고, (2) Agent Stream 변환 시 resource_type이 CASE가 아닌 이벤트도 evidence 또는 context에서 case_id를 채우고, (3) Synapse 수신 측에서 `agent_activity_log`에 `case_id` 컬럼이 있다면 resource_id(resource_type=CASE일 때) 또는 evidence_json.caseId로 채우도록 규격화.

---

### 1.2 `stage` 컬럼 표준화 계획 (통합 워크벤치 '탐지-추론-조치')

**현재 정의** (`docs/handoff/TEAM_SNAPSHOT_AGENT_STREAM_SOT.md`, `core/agent_stream/writer.py`):

| Aura event_type | agent_activity_log stage |
|-----------------|--------------------------|
| SCAN_STARTED, SCAN_COMPLETED | SCAN |
| DETECTION_FOUND | DETECT |
| RAG_QUERIED, REASONING_COMPOSED, DECISION_MADE | ANALYZE |
| SIMULATION_RUN | SIMULATE |
| ACTION_* , SAP_WRITE_* | EXECUTE |
| CASE_* | EXECUTE |

**표준화 방안**:

- **DB/API**: `stage` 값은 이미 표준화됨 — `SCAN | DETECT | ANALYZE | SIMULATE | EXECUTE | MATCH` 만 사용.
- **통합 워크벤치 타임라인**:
  - **탐지**: `SCAN` + `DETECT` (스캔 시작/완료, 위험 탐지)
  - **추론**: `ANALYZE` + `SIMULATE` (RAG/추론/시뮬레이션)
  - **조치**: `EXECUTE` (제안·승인·실행·SAP 반영)
  - **매칭**(선택): `MATCH` — 유사 케이스 등
- **프론트엔드**: `stage` → `stageGroup` 매핑 테이블을 두고, 타임라인 필터/그룹핑에 사용.  
  예: `{ SCAN: "detection", DETECT: "detection", ANALYZE: "reasoning", SIMULATE: "reasoning", EXECUTE: "action", MATCH: "match" }`.
- **추가 권장**: Synapse에 `agent_activity_log`에 `stage_group`(또는 `phase`) 컬럼을 두고 ETL 시 위 매핑으로 채우면, 통합 뷰 쿼리가 단순해짐.

---

## 2. 구현 가이드 (적용 사항)

### 2.1 Logging Logic — case_id 연동

- **hooks.py**: `_case_context(state)`로 context에서 caseId/caseKey 추출. **`_apply_case_resource(event, state)`** 호출로 context에 case_id가 있으면 모든 Audit 이벤트에 `resource_type='CASE'`, `resource_id=case_id` 자동 설정 (scan_started, scan_completed, reasoning_composed).
- **synapse_finance_tool.py**:  
  - `rag_queried`: context에서 case_id 추출해 evidence_json에 `caseId` 포함.  
  - `action_proposed`: evidence_json에 `caseId` 포함 (이미 인자로 caseId 있음 → 스키마에 반영).  
  - `action_executed` / `sap_write_*`: context의 case_id를 evidence에 포함.  
  - `action_approved` (finance_agent.py): 요청 context에서 case_id/caseKey 추출해 이벤트에 전달.
- **core/audit/writer.py**: `_event_to_payload`에서 이미 context의 case_id를 evidence_json에 보강. 유지.
- **core/agent_stream/writer.py**: `_audit_event_to_agent_event`에서 evidence에 caseId가 없을 때, resource_type이 AGENT_ACTION/INTEGRATION인 경우에도 trace/context에서 case_id를 채우는 로직은 Aura가 HTTP로 보내는 payload에 caseId가 들어가도록 위 이벤트 보강으로 해결. 필요 시 writer에서 request context에서 case_id 한 번 더 보강 가능.

### 2.2 metadata_json 스키마 표준화 (워크벤치 UI)

에이전트 추적용 `metadata_json`(Agent Stream payload → Synapse `payload_json`/metadata) 규격 통일:

```json
{
  "title": "<단계 제목>",
  "reasoning": "<사고 과정/메시지>",
  "evidence": { ... },
  "status": "SUCCESS | WARNING | ERROR"
}
```

- **title**: 단계 한 줄 제목 (`core/agent_stream/writer._stage_to_title`).
- **reasoning**: 운영자 이해용 설명 (기존 message).
- **evidence**: 단계별 상세(docIds, actionId, score 등) 객체.
- **status**: `SUCCESS` | `WARNING` | `ERROR` — severity/outcome 기반 (`_severity_to_metadata_status`).

- **stage 상수**: `core/agent_stream/constants.py`에 `STAGE_*`, `STAGE_GROUP_*`, `STAGE_TO_GROUP` 정의. `writer.py`의 `_AUDIT_TO_STAGE`·`_stage_to_title`에서 이 상수 사용 → 프론트 필터링 가능.
- **format_metadata**: `core/agent_stream/metadata.format_metadata(title, reasoning, evidence, status)`로 metadata_json 규격 강제. writer에서 모든 Agent 이벤트 payload 생성 시 사용.

---

## 3. Pre-Check (Reasoning Trace 표준화)

- **Q1. hooks.py에서 비어있는 case_id를 context로부터 주입하는 로직 식별?**  
  **예.** `_case_context(state)`가 `state.get("context")`에서 `caseId`/`caseKey`를 추출하고, SCAN_STARTED/SCAN_COMPLETED/REASONING_COMPOSED 발행 시 `ev["caseId"]`, `ev["caseKey"]` 및 `event.resource_type="CASE"`, `event.resource_id=case_id`로 주입함.
- **Q2. stage 컬럼값을 프론트 단계별 그룹핑(탐지-추론-조치) 기준으로 상수 정의?**  
  **예.** `core/agent_stream/constants.py`에 `STAGE_SCAN`~`STAGE_MATCH`, `STAGE_GROUP_DETECTION`/`REASONING`/`ACTION`, `STAGE_TO_GROUP` 매핑 정의.

## 4. 금융 도구 이벤트 누락 보강

다음 도구에서도 `agent_activity_log`에 기록되도록 RAG_QUERIED(ANALYZE) 감사 추가:

- **get_document**: 문서 조회 성공 시 `rag_queried(doc_ids=[bukrs/belnr/gjahr], message="Document fetched: ...")`.
- **get_open_items**: 조회 성공 시 `rag_queried(message="Open items queried", source="open_items")`.
- **get_lineage**: 조회 성공 시 `rag_queried(message="Lineage queried", source="lineage")`.

## 5. Phase 3: Resource Linkage for Lineage (Pre-Check)

### Q1. resource_key가 누락되어 계보에서 고립(Orphan)될 가능성이 있는 구간이 있나요?

**예.** 다음 구간에서 SAP 원천 전표 식별자(bukrs, belnr, gjahr / resource_key)가 evidence에 누락됨.

| 구간 | 현재 evidence | 누락 |
|------|----------------|------|
| get_case (detection_found) | caseId, riskTypeKey, score, caseKey | 케이스 응답의 bukrs, belnr, gjahr 미포함 |
| search_documents (rag_queried) | docIds, topK, latencyMs, caseId | filters의 bukrs, gjahr 미포함 |
| get_document (rag_queried) | docIds(복합키 문자열) | bukrs, belnr, gjahr 별도 필드 없음 → SAP 직접 이동 불가 |
| get_lineage (rag_queried) | caseId, source | belnr/gjahr 경로 시 belnr, gjahr, bukrs 미포함 |
| simulate/propose/execute/sap_* | caseId, actionId | 원인 전표(bukrs, belnr, gjahr) 없음 |

### Q2. metadata_json.evidence 내부에 SAP 원천 데이터로 바로 이동할 수 있는 식별 정보가 포함되어 있습니까?

**부분적.** docIds에 "bukrs/belnr/gjahr" 형태 문자열이 있을 수 있으나, **belnr**, **gjahr**, **bukrs** 단일 필드 및 **resource_key**가 없어 프론트/연동에서 SAP 화면 딥링크 등에 불리함. Phase 3에서 evidence에 `bukrs`, `belnr`, `gjahr`, `resource_key`(선택)를 누락 없이 포함하도록 보강함.

### Phase 3 보강 사항 (연결성)

- **synapse_finance_tool**: `_sap_document_evidence(bukrs, belnr, gjahr, from_context=True)`로 SAP 원천 식별자 수집 후 모든 감사 이벤트 evidence에 병합. `resource_key = "bukrs/belnr/gjahr"` 자동 생성.
- **get_case (detection_found)**: 케이스 응답(parsed)에서 bukrs, belnr, gjahr 추출해 evidence에 포함.
- **search_documents**: filters의 bukrs, gjahr, belnr를 evidence에 포함.
- **get_document**: 인자 bukrs, belnr, gjahr 및 resource_key를 evidence에 포함.
- **get_lineage**: belnr/gjahr 경로 사용 시 해당 값들 evidence에 포함; caseId만 사용 시 context에서 보강.
- **simulate/propose/execute/sap_***: request context에 bukrs, belnr, gjahr가 있으면 evidence에 포함(원인 전표–결과 케이스 연결).
- **core/context**: `set_request_context(..., bukrs=, belnr=, gjahr=)` 옵션 추가 — 트리거/라우트에서 케이스 조회 후 전표 키를 넣어 주면 이후 도구 로그에 자동 반영.

---

## 6. 참조

- 테이블 스키마: `docs/handoff/TEAM_SNAPSHOT_AGENT_STREAM_SOT.md`
- Audit 연동: `core/audit/writer.py`, `core/agent_stream/writer.py`
- stage/status 상수: `core/agent_stream/constants.py`
- 이벤트 생성: `core/audit/schemas.py` (AgentAuditEvent), `domains/finance/agents/hooks.py`, `tools/synapse_finance_tool.py`
