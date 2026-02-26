# [BE 전달] MCP 도입 구현 요청 (최종본)

## 목적
Aura 분석 정확도 향상을 위해 MCP 기반 Fact/Rule 조회 및 검증 툴을 단계적으로 제공합니다.
핵심은 "LLM 자유추론"이 아니라 "결정론 정책 + 검증 가능한 근거"입니다.

## 범위
- 대상 시스템: synapsex-service (Spring Boot)
- 우선순위: P0 > P1 > P2
- 기능 성격에 맞춰 폴더 구성을 깔끔하게 하여 향후 유지보수에 문제 없도록 한다.

## P0 (필수, 즉시)
1. Policy/Regulation Resource/Tool
- 기능: 조항 조회 (article, clause, version, effective_from, effective_to, is_active)
- 계약: 조회 시 `effective_at`(전표시각) 기준으로 유효 조항만 반환 가능해야 함

2. Business Calendar Tool
- 기능: `occurredAt`, `userId`, `tenantId` 기준 휴일성 판단
- 반환: `isHoliday`, `holidayType`(WEEKEND|PUBLIC_HOLIDAY|NONE), `decision_source`

3. Master Data Tool
- 기능: mcc/expenseType/hrStatus 정규화 및 의미어 제공
- 반환: `normalized`, `raw`, `mapping_confidence`, `source`

4. 공통 응답 규격
- 필수 필드: `schema_version`, `source_system`, `evaluated_at`, `effective_from/to`(해당 시), `trace_id`
- 실패 시: 표준 코드 (`EVIDENCE_MISSING`, `POLICY_CONFLICT`, `INPUT_PARTIAL`)

## P1 (고도화)
5. Case Context Tool
- 기능: 시계열 지표 제공
- 최소 반환: `window_10m_txn_count`, `window_24h_same_merchant_count`, `user_30d_baseline_amount`

6. Evidence Verification Tool
- 기능: Aura가 전달한 `sentence_citation_map` 검증
- 입력: sentence, citation_id[], article
- 반환: `is_valid`, `mismatch_reasons[]`

7. RAG 충돌 지원
- 기능: 정책결과와 RAG 인용 불일치 시 재평가에 필요한 진단 데이터 제공

## P2 (운영 게이트)
8. Eval Run 저장/조회 강화
- 리플레이 평가 결과를 시계열 저장하고 latest 게이트 판정 제공

9. 감사 추적 강화
- append-only 저장 정책(결정코드/근거해시/모델버전)

10. 권한
- tool-level RBAC/ABAC + tenant 경계 강제

## DB/스키마 권장
- 규정 메타: `version`, `effective_from`, `effective_to`, `is_active`
- 평가 집계: eval run 테이블에 `rag_zero_rate`, `citation_error_rate`, `default_inflow_rate`, `reproducibility_rate`
- 검증 로그: sentence-citation 검증 결과 테이블(또는 감사 로그 확장)

## 수용 기준(AC)
1. Aura 요청 1건 기준, P0 Tool 응답이 모두 trace_id와 함께 수신됨
2. RAG_ZERO 상황에서 BE 검증결과가 `확정 위반`으로 내려가지 않음
3. sentence-citation 불일치 케이스가 `POLICY_CONFLICT`로 표준화됨
4. 동일 입력 재실행 시 결과 코드/판정 일치율 목표 달성(내부 기준)

## 확인 요청
- 기존 agent-tools 계약을 유지한 채 MCP 어댑터 경로를 병행 제공 가능한지
- tool timeout/재시도/서킷브레이커 기본값 제안

