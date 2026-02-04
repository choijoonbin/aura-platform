# Team Snapshot / Agent Stream 데이터 SoT 확립

> **목표**: 대시보드 "운영 현황(Team/Agent)" 데이터를 mock이 아닌 DB 기반으로 제공

---

## 1. agent_activity_log (신규 테이블)

**스키마**: `dwp_aura.agent_activity_log`

| 컬럼 | 타입 | 설명 |
|------|------|------|
| log_id | bigserial | PK |
| tenant_id | bigint | not null |
| occurred_at | timestamptz | not null default now() |
| stage | text | not null (SCAN/DETECT/EXECUTE/SIMULATE/ANALYZE/MATCH) |
| level | text | not null (INFO/WARN/ERROR) |
| message | text | not null |
| resource_type | text | null (CASE/ACTION/DOCUMENT 등) |
| resource_id | text | null |
| trace_id | text | null |
| payload_json | jsonb | not null default '{}' |

**인덱스**: (tenant_id, occurred_at desc), (tenant_id, resource_type, resource_id)

**동기화 규칙**: agent_activity_log insert 시 audit_event_log에도 1줄 insert
- event_category='AGENT', event_type=stage, severity=level
- resource_type, resource_id, evidence_json=payload_json

---

## 2. Team Snapshot 산출

**입력**: auth_db.com_users, dwp_aura.agent_case  
**결과**: user_id, display_name, open_cases, sla_risk, avg_lead_time_hours

---

## 3. API

| API | 설명 |
|-----|------|
| GET /aura/dashboard/team-snapshot | Team Snapshot |
| GET /aura/dashboard/agent-stream | Agent Execution Stream |

게이트웨이: 위 API를 /api/synapse/dashboard/*로 프록시 or 합성

---

## 4. Aura 이벤트 → stage 매핑

| Aura event_type | agent_activity_log stage |
|-----------------|--------------------------|
| SCAN_STARTED, SCAN_COMPLETED | SCAN |
| DETECTION_FOUND | DETECT |
| RAG_QUERIED, REASONING_COMPOSED, DECISION_MADE | ANALYZE |
| SIMULATION_RUN | SIMULATE |
| ACTION_PROPOSED, ACTION_APPROVED, ACTION_EXECUTED, ACTION_ROLLED_BACK | EXECUTE |
| SAP_WRITE_SUCCESS, SAP_WRITE_FAILED | (INTEGRATION 또는 별도 stage) |
