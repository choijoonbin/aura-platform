# 감사로그/에이전트 이벤트 대시보드 보강 — 시스템별 확인사항

> C-1/C-2/C-3 작업 완료 후, 각 시스템별로 확인·협의가 필요한 항목입니다.

---

## ✅ Aura-Platform 완료 사항

| 항목 | 구현 내용 |
|------|-----------|
| **C-1** | event_category: CASE 추가, SIMULATION_RUN→ACTION, case_created/case_status_changed/case_assigned 헬퍼 |
| **C-2** | evidence_json correlation 키(traceId, gatewayRequestId, caseId, caseKey, actionId) 보장, context에 case_id/case_key 추가 |
| **C-3** | DETECTION_FOUND tags(driverType, severity), ACTION_PROPOSED 승인대기 시점 기록 |

**참고 문서**: `docs/guides/AUDIT_EVENTS_SPEC.md`

---

## ✅ Synapse (백엔드) 확인 완료

> 백엔드 job.txt / `AURA_AUDIT_SYNAPSE_CONFIRMATION.md` 회신 반영

| Aura 발행 항목 | Synapse 처리 |
|----------------|-------------|
| event_category | CASE, ACTION, AGENT, INTEGRATION 모두 저장 |
| event_type | SIMULATION_RUN, SCAN_STARTED 등 저장 (prefix 제거 시) |
| evidence_json | traceId, gatewayRequestId, caseId, caseKey, actionId 포함 저장 |
| tags | driverType, severity 저장 (Top Risk Driver 집계용) |
| tenant_id | Long 또는 숫자 문자열 지원. **Gateway에서 숫자로 정규화됨** |

---

## ✅ Gateway / Backend — tenant_id 정규화 확인

> 백엔드 전달: X-Tenant-ID는 Gateway에서 숫자로 정규화됩니다.

- Auth Server JWT의 `tenant_id`가 숫자(예: `"1"`)이면, 클라이언트가 `"tenant1"`을 보내도 JWT에서 추출한 숫자로 교체됩니다.
- Aura는 Gateway를 통해 전달받은 `X-Tenant-ID`를 그대로 Audit 이벤트에 사용합니다.

---

## 🔍 Frontend (dwp-frontend) 확인사항

### 1. Agent Stream 표시

- evidence_json.message를 운영자 이해 가능 문장으로 표시
- trace_id, case_id, caseKey로 drill-down 링크 연결

### 2. 대시보드 API 연동

- `docs/handoff/FRONTEND_DASHBOARD_INTEGRATION_PROMPT.md` 참고
- team-snapshot, agent-stream API 경로 및 필터 파라미터 확인

### 3. Frontend 팀 문의

```
Aura-Platform Audit 이벤트가 evidence_json.message, tags(driverType, severity)를 포함합니다.

확인 요청:
1. Agent Execution Stream UI에서 message 표시
2. traceId/caseId/caseKey 기반 drill-down 라우팅
3. Top Risk Driver 집계 시 tags.driverType, tags.severity 사용
```

---

## 📌 Gateway / Backend — correlation 키 (선택 협의)

Aura가 evidence_json에 enrichment하려면 요청 시 다음 헤더/바디가 있으면 유리합니다:

| 키 | 출처 | 용도 |
|----|------|------|
| X-Trace-ID | Gateway/Backend | traceId (없으면 Aura가 UUID 생성) |
| X-Request-ID / X-Gateway-Request-ID | Gateway | gatewayRequestId |
| context.caseId | Request body | caseId |
| context.caseKey | Request body | caseKey (예: CS-2026-0001) |

---

## ✅ Frontend 대시보드 연동 완료

> Frontend 회신 반영 (2026-02)

| 항목 | 구현 내용 |
|------|-----------|
| Agent Stream | evidence_json.message 표시, traceId/caseId/caseKey/actionId drill-down |
| 대시보드 API | 5개 연동 (summary, top-risk-drivers, action-required, team-snapshot, agent-stream) |
| tenant_id | X-Tenant-ID 숫자형 사용 ("1", "200000"). 비숫자 시 BE null 처리 확인 |

---

## 📋 요약

| 시스템 | 상태 | 비고 |
|--------|------|------|
| **Synapse** | ✅ 확인 완료 | Redis 구독, event_category, evidence_json, tags 저장 |
| **Gateway/Backend** | ✅ 확인 완료 | tenant_id JWT 기반 숫자 정규화 |
| **Frontend** | ✅ 연동 완료 | Agent Stream, 대시보드 API 5개 |
