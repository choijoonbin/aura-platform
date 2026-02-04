# 백엔드 → Aura-Platform 업데이트 (2026-01-29)

> **출처**: DWP Backend 팀 공유 문서  
> **통합관제센터 Agent Execution Stream — audit_event_log 이벤트 규격**

---

## 배경

`GET /api/synapse/dashboard/agent-activity` API가 `audit_event_log`를 SoT로 사용합니다.  
Aura-Platform에서 에이전트 실행(스캔/탐지/조치/통합) 시 이벤트를 기록하면, **통합관제센터 "Agent Execution Stream"**에 표시됩니다.

---

## 권장 event_category / event_type

| event_category | event_type 예시 |
|----------------|-----------------|
| AGENT | SCAN_STARTED, SCAN_COMPLETED, DETECTION_FOUND, RAG_QUERIED, SIMULATION_RUN, DECISION_MADE |
| INTEGRATION | INGEST_RECEIVED, INGEST_FAILED, SAP_WRITE_SUCCESS, SAP_WRITE_FAILED |
| ACTION | ACTION_PROPOSED, ACTION_APPROVED, ACTION_EXECUTED, ACTION_ROLLED_BACK |

---

## 표시 품질을 위한 필드

| 필드 | 설명 |
|------|------|
| `resource_type` | CASE, AGENT_ACTION, INTEGRATION 등 |
| `resource_id` | case_id 또는 action_id (문자열) |
| `evidence_json.message` | 스트림에 표시할 메시지 (예: "Critical anomaly detected: Amount variance 3x") |
| `trace_id` | 요청 추적용 |
| `severity` | INFO, WARN, ERROR (표시 레벨 결정) |

---

## 참고

SynapseX의 `AuditWriter` 또는 동일 규격으로 `dwp_aura.audit_event_log`에 insert하면 됩니다.
