# FE Agent Events 전환 체크리스트 (분석단계 탭)

## 목적
- 타임라인 데이터 소스를 `aiThoughts`(휘발) 중심에서 `agent-events API`(영속) 중심으로 전환한다.

## 소스 우선순위
1. `GET /api/synapse/cases/{caseId}/agent-events?runId={runId}`
2. (fallback) 기존 `aiThoughts`

## 이벤트 표시 규칙
- 표준 `event_type`만 UI 배지/아이콘 매핑
  - `NODE_START`, `NODE_END`, `TOOL_CALL`, `TOOL_RESULT`, `EVIDENCE_ADDED`, `EVIDENCE_REJECTED`, `GATE_APPLIED`, `COMPLETED`, `FAILED`
- `AGENT_STREAM`은 레거시 fallback 표기로만 유지
- 정렬: `timestamp` 오름차순

## 완료 조건
- 새로고침 후에도 타임라인이 동일하게 재구성된다.
- `runId`가 같으면 동일 이벤트 순서/개수가 보장된다.
- `FAILED` 또는 `COMPLETED`가 마지막 이벤트로 확인된다.

## 검증 로그 요청(공통)
- caseId/runId
- FE에서 호출한 agent-events API 응답 건수
- 화면 렌더된 이벤트 건수/마지막 event_type
