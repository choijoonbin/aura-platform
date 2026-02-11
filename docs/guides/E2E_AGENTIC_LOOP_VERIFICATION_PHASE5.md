# End-to-End Agentic Loop Validation (Phase 5)

## Pre-Check (MUST ANSWER BEFORE CODING)

### Q1. 특정 에이전트 단계에서 로그 생성이 누락되는 코너 케이스(Corner Case)를 모두 식별했습니까?

**식별된 코너 케이스:**

| 구간 | 조건 | 결과 |
|------|------|------|
| **get_case** | 응답 JSON 파싱 실패 또는 riskTypeKey/score 없음 | `detection_found` 감사 미발행 (try/except pass) |
| **search_documents / get_document / get_lineage / get_open_items** | `_emit_audit_event` 내 예외 | 해당 RAG/evidence 감사 미발행 (except pass) |
| **hooks (scan_started, scan_completed, reasoning_composed)** | `_emit_audit` 내 예외 또는 context에 case_id 없음(reasoning_composed) | 해당 Audit 미발행; reasoning은 case_id 있을 때만 발행 |
| **tools (simulate, propose, execute, sap_*)** | `_emit_audit_event` 내 예외 | 해당 액션 감사 미발행 |
| **AuditWriter.ingest_fire_and_forget** | Agent Stream `emit_from_audit` 예외 | Redis/HTTP는 시도되나 Agent Stream push만 스킵(debug 로그) |
| **트리거** | 중복(caseId+updated_at) 또는 auto-start 조건 미충족 | 에이전트 미실행 → 해당 케이스에 대한 로그 전부 없음 |
| **Phase2 분석** | `DEMO_OFF` 환경변수 | 분석 비활성 → Phase2 경로 로그 없음 |
| **HITL** | 사용자 거부/타임아웃 후 재개 없음 | execute/approval 관련 로그 없음 |

**권장:** 코너 케이스에서도 “실패” 이벤트를 남기려면, try/except에서 실패 시 `severity=ERROR`, `outcome=FAILED` 로 감사 발행을 추가하는 것을 검토.

---

### Q2. 실시간 스트리밍 시 백엔드 API 서버에 과도한 부하를 주지 않는 발행 주기인가요?

**현재 동작:**

- **SSE → 클라이언트**: 이벤트 간 `STREAMING_EVENT_DELAY = 0.05` (50ms). 이벤트 수가 많으면 초당 최대 약 20개 전송.
- **Audit → Synapse**: `ingest_fire_and_forget` 호출 시마다 1회 Redis publish + 1회 `POST /api/synapse/agent/events` (단일 이벤트). 배치 미사용.
- **Agent Stream Writer**: `_batch_max = 10`, `_flush_interval = 2.0` 정의되어 있으나, 현재 `emit_from_audit`는 이벤트 단위로 `push_one`만 호출하여 **배치가 사용되지 않음**.

**부하 관점:**

- 에이전트 1회 실행 시 도구 호출 수( get_case, search_documents, get_open_items, get_lineage, propose_action 등)만큼 Audit 이벤트 발생 → 동일 수만큼 HTTP POST 발생.
- 동시 실행이 많지 않으면 부하는 제한적이나, **이벤트 수가 많은 경우** Agent Stream 쪽 **배치 전송(batch push)** 도입 시 POST 횟수를 줄일 수 있음.

**권장:**  
- 현재 설정으로는 “과도한 부하”로 보기 어렵고, 트래픽 증가 시 Agent Stream Writer에서 배치 누적 후 주기적 flush(예: `_flush_interval`) 적용을 권장.

---

## 1. E2E Trace Audit (시퀀스 시뮬레이션)

전체 루프는 **외부(SAP/배치) → Synapse/BE → Aura → Synapse(로그/결과)** 로 이어집니다.

```
[sap_raw_events / 케이스 생성·갱신]
        ↓
[BE 배치] case_updated 웹훅 → Aura POST /api/synapse/triggers/case-updated (또는 동등 경로)
        ↓
[Aura] 중복 체크 → 조건 충족 시 _run_finance_agent_background (또는 Phase2 분석)
        ↓
set_request_context(tenant_id, case_id, case_key, policy_config_source, policy_profile)
        ↓
[Finance Agent] stream(context={caseId, caseKey}) → 노드: analyze → evidence_gather → plan → tools → reflect
        ↓
[도구 호출 시] get_case → detection_found 감사
                search_documents → rag_queried 감사 (ragContributions 포함)
                get_open_items, get_lineage → rag_queried 감사
                propose_action → action_proposed 감사
                (HITL 승인 후) execute_action → action_executed, sap_write_* 감사
        ↓
[Hooks] analyze 시작 → scan_started 감사
        tools 종료 / reflect → scan_completed, reasoning_composed 감사 (policy_reference 포함)
        ↓
[AuditWriter] ingest_fire_and_forget → Redis publish + Agent Stream emit_from_audit
        ↓
[Agent Stream Writer] _audit_event_to_agent_event → format_metadata(title, reasoning, evidence, status)
        ↓
POST /api/synapse/agent/events → [Synapse] agent_activity_log 적재 (payload_json = metadata_json)
        ↓
[Phase2 경로 시] run_phase2_analysis → get_case, search_documents, get_open_items, get_lineage
        → set_phase2_result → 콜백 send_callback(runId, caseId, COMPLETED, finalResult)
        ↓
[BE] finalResult 수신 → recon_result 등 도출 (BE/Synapse 책임)
```

**Aura 책임 구간:** 트리거 수신 ~ context 설정 ~ 에이전트 실행 ~ 도구 호출 ~ Audit 발행 ~ Agent Stream push ~ (Phase2 시) 콜백 전송.  
**sap_raw_events**는 Synapse/수집 파이프라인, **recon_result**는 BE가 finalResult 기반으로 생성하는 것으로 가정.

---

## 2. Status Accuracy (metadata_json.status)

**매핑 규칙** (`core/agent_stream/writer.py`):

- **outcome**  
  - `SUCCESS`, `PASS`, `PENDING`, `NOOP` → **SUCCESS**  
  - `FAIL`, `FAILED`, `ERROR`, `DENIED` → **ERROR**
- **severity** (outcome이 ERROR가 아닐 때만 적용)  
  - `WARN` → **WARNING**  
  - `ERROR` → **ERROR**  
  - 그 외 → **SUCCESS**

**프론트 색상 권장:**

- `SUCCESS` → 정상(녹색)
- `WARNING` → 주의(노란/주황)
- `ERROR` → 실패(빨강)

**검증 포인트:**  
Audit 이벤트의 `outcome`/`severity`가 위 규칙대로 설정되는지 확인.  
(예: `AgentAuditEvent.action_executed(..., outcome="FAIL")`, `action_failed(..., severity="ERROR")` → status **ERROR**.)

---

## 3. Log Verbosity (Reasoning 프롬프트 조정)

고객이 이해할 수 있는 **설명 가능한 문장**으로 reasoning/reasonText를 만들기 위해, Phase2/Phase3 LLM 호출부에 사용할 **공통 가이드**를 두고, 프롬프트를 아래와 같이 미세 조정하는 것을 제안합니다.

- **원칙:** 전문 용어 최소화, “무엇을 보고 / 왜 그렇게 판단했는지” 2~3문장으로 서술.
- **Phase2:**  
  - 기존: `"한국어로 2~3문장으로 사람이 이해할 수 있는 이유(reasonText)를 작성."`  
  - 보강: `"고객이 읽어도 이해할 수 있도록, 전문 용어를 피하고 '어떤 증거를 바탕으로 어떤 결론인지' 2~3문장으로 설명 가능한 문장으로 작성."`
- **Phase3:**  
  - 기존: `"한국어로 2~3문장 reasonText 작성."`  
  - 보강: 동일한 “설명 가능한 문장” 원칙 추가.

구체적 수정안은 아래 “4. 로그 프롬프트 조정안” 참고.

---

## 4. 로그 프롬프트 조정안 (설명 가능한 문장)

- **파일:** `core/analysis/phase2_pipeline.py`, `core/analysis/phase3_pipeline.py`
- **내용:** reasonText 생성용 LLM prompt에 다음 지시를 반영.

**Phase2 (phase2_pipeline.py):**

```text
"한국어로 2~3문장으로 사람이 이해할 수 있는 이유(reasonText)를 작성. "
"전문 용어는 최소화하고, 어떤 증거(케이스·문서·미결항목 등)를 바탕으로 어떤 결론(위험도·권고)에 이르렀는지 고객이 읽고 이해할 수 있는 설명 가능한 문장으로 작성."
```

**Phase3 (phase3_pipeline.py):**

```text
"한국어로 2~3문장 reasonText 작성. "
"고객이 이해할 수 있도록, 참고한 증거와 그에 따른 판단을 설명 가능한 문장으로 작성."
```

이렇게 하면 대시보드에 노출되는 reasoning 로그가 “설명 가능한 문장”에 가깝게 생성됩니다.

---

## 5. 요약

| 항목 | 상태 | 비고 |
|------|------|------|
| E2E 시퀀스 | 문서화 완료 | 트리거 → context → 에이전트 → 도구 → Audit → Agent Stream → 콜백; sap_raw_events·recon_result는 경계 외부 |
| 코너 케이스 | 식별 완료 | 파싱/예외/조건 미충족 시 로그 누락 구간 정리; 필요 시 실패 이벤트 추가 검토 |
| 스트리밍 부하 | 현재 무리 없음 | 배치 미사용; 트래픽 증가 시 Agent Stream 배치 flush 권장 |
| metadata_json.status | 규칙 명확 | SUCCESS/WARNING/ERROR 매핑 및 FE 색상 권장 정리 |
| Reasoning 프롬프트 | 조정안 제시 | Phase2/Phase3에 “설명 가능한 문장” 지시 추가 |
