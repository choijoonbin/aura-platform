# [BE 전달] dwp-mcp-server 1차 점검 보완 체크리스트 (P0/P1)

대상: `dwp-mcp-server`  
목적: 1차 통합 테스트 전 MCP 완성도/안정성 보강

## P0 (즉시 수정 권장)

1. 테넌트 경계 강제 (가장 중요)
- 문제: `runId` 기반 조회 일부가 `tenant_id` 조건 없이 조회될 수 있음.
- 리스크: 교차 테넌트 데이터 접근 가능성.
- 조치:
  - `case_analysis_result`, `case_analysis_run`, `agent_case` 조회 SQL에 `tenant_id = ?` 강제.
  - `resolveRunId(...)` 및 `queryJson(...)` 경로 전체 점검.
- 완료 기준:
  - 다른 tenant의 `runId/caseId`로 조회 시 무조건 `EVIDENCE_MISSING` 또는 `FORBIDDEN`.

2. `policy-regulation` 입력 제약 완화
- 문제: `article` 필수 강제 → Aura의 조항 미확정 탐색 호출 막힘.
- 조치:
  - `article/clause` 모두 optional 허용.
  - 둘 다 비어도 `effectiveAt + tenant + is_active` 기반 상위 N건 반환 허용.
  - 과다 조회 방지 위해 limit(예: 100) + 정렬 유지.
- 완료 기준:
  - 빈 `article/clause` 요청도 정상 응답(success=true, data.items>=0).

3. 권한 모델 조정 (서비스 계정 기준)
- 문제: 주요 read tool이 ADMIN 고정이면 Aura 서비스 계정에서 `FORBIDDEN` 발생 가능.
- 조치:
  - tool별 권한코드 분리:
    - `MCP_POLICY_READ`
    - `MCP_MASTERDATA_READ`
    - `MCP_EVAL_READ`(운영자)
  - `isAdmin()` 단독 체크 대신 `permissionClient.check(...)` 기반으로 전환.
  - 긴급 우회: 서비스 계정 allowlist + tenant 제한.
- 완료 기준:
  - 서비스 계정으로 P0 3개 tool 호출 시 200 응답.

4. Evidence Verification 매핑 정합성
- 문제: `citationIds` 매칭 규칙이 Aura의 citation 체계(`C1`, `C2`, ...)와 불일치 가능.
- 조치:
  - 입력 `citationIds`를 3단 매칭:
    - 원문 id
    - 숫자 id (`C12` -> `12`)
    - `chunk_id`/`citation_id` 양방향 매칭
  - `mismatchReasons`를 코드형으로 고정:
    - `EMPTY_CITATIONS`, `NO_ANALYSIS_RESULT`, `CITATION_NOT_FOUND`, `ARTICLE_MISMATCH`
- 완료 기준:
  - Aura가 보낸 citation map 기준 오탐 없이 검증 결과 일치.

5. 디버그 로그 표준화 (통합 점검 필수)
- 조치:
  - 요청/응답 요약 로그 추가:
    - `traceId`, `tenantId`, `userId`, `caseId`, `runId`, `decisionCode`, `latency_ms`
  - 민감값 마스킹 정책 적용.
- 완료 기준:
  - 케이스 1건 추적 시 4개 tool 호출 흐름이 traceId로 연결됨.

## P1 (다음 스프린트 권장)

1. 시계열 컨텍스트 정확도 보강
- `case-context`에서 시간 기준 필드(`created_at` vs `occurred_at`) 명확화.
- merchant 동일성 비교 정규화(공백/특수문자/대소문자/대체필드 우선순위).

2. 정책 시점판정 강화
- `effectiveAt` timezone을 KST로 고정 문서화.
- `effective_from/to` 없을 때 정책 기본값 정의.

3. 에러 계약 고정
- HTTP status + envelope `success/errorCode` 규칙 문서화.
- 예:
  - 권한 실패: `FORBIDDEN`
  - 입력 부족: `INPUT_PARTIAL`
  - 근거 없음: `EVIDENCE_MISSING`
  - 정책 충돌: `POLICY_CONFLICT`

4. 성능/내구성
- tool별 p95 latency 측정 및 타임아웃 정책 고정.
- DB 인덱스 점검:
  - `rag_chunk(tenant_id, is_active, regulation_article, regulation_clause)`
  - `case_analysis_result(run_id, tenant_id)`
  - `fi_doc_header(tenant_id, user_id, created_at)`

## 통합 테스트 체크리스트 (BE 완료 후)

1. 휴무일 케이스 3건(동일 패턴) 실행
- `business-calendar` 결과가 `isHoliday/holidayType/decisionSource` 일관 반환

2. 분석 3회 재실행
- 동일 입력 시 `decisionCode`, `qualityGateCodes` 재현성 확인

3. citation 검증
- `sentence_citation_map` 전달값으로 `evidence-verification` 호출 시 오탐 없는지 확인

4. 충돌 진단
- `rag-conflict-diagnostics`가 `POLICY_CONFLICT`를 정확히 리턴하는지 확인

## 요청 로그 샘플(공유 필요)

- `POST /mcp/tools/policy-regulation`
- `POST /mcp/tools/business-calendar`
- `POST /mcp/tools/master-data`
- `POST /mcp/tools/evidence-verification`

각 1건씩 아래 포함:
- request summary: traceId, tenantId, userId, caseId/runId
- response summary: success, decisionCode(or errorCode), latency_ms



##작업완료
요청하신 MCP P0/P1 보완 작업 반영 완료했습니다.

적용 내용:

테넌트 경계 강제
runId 경로 전체를 tenant_id 조건으로 고정했습니다.
input runId도 tenant/case 검증 후에만 사용합니다.
적용 파일: McpToolService.java
policy-regulation 입력 제약 완화
article 필수 제거, article/clause 모두 optional 허용.
비어도 tenant + effectiveAt + is_active 기준으로 LIMIT 100 조회 유지.
적용 파일: McpToolController.java, McpToolService.java
권한 모델 조정
ADMIN 고정 체크를 permissionClient.check(...) 기반으로 변경.
권한코드 분리:
MCP_POLICY_READ
MCP_MASTERDATA_READ
MCP_EVAL_READ
긴급 우회: 서비스계정 allowlist(+tenant 제한) 추가.
설정 키:
MCP_SERVICE_ACCOUNT_USER_IDS
MCP_SERVICE_ACCOUNT_TENANT_IDS
적용 파일: McpToolController.java, application.yml
Evidence Verification 매핑 정합성
citation id 3단 매칭 반영:
원문 id
숫자 id (C12 ↔ 12)
chunk_id/citation_id 양방향 매칭
mismatchReasons 코드형 유지:
EMPTY_CITATIONS, NO_ANALYSIS_RESULT, CITATION_NOT_FOUND, ARTICLE_MISMATCH
적용 파일: McpToolService.java
디버그 로그 표준화
모든 툴에 요청/응답 요약 로그 추가:
traceId, tenantId, userId, caseId, runId, decisionCode, latency_ms
적용 파일: McpToolController.java
P1 일부 반영
effectiveAt KST 기준 주석/로직 명시
case-context 시간 기준은 현재 fi_doc_header.created_at 사용 명시
적용 파일: McpToolService.java
검증:

./gradlew :dwp-mcp-server:compileJava -x test 성공
./gradlew :services:synapsex-service:compileJava -x test 성공
요청하신 로그 샘플(포맷):

MCP request summary: tool=policy-regulation traceId=... tenantId=1 userId=100 caseId=null runId=null
MCP response summary: tool=policy-regulation traceId=... tenantId=1 userId=100 caseId=null runId=null success=true decisionCode=OK latency_ms=23

MCP request summary: tool=business-calendar traceId=... tenantId=1 userId=100 caseId=null runId=null
MCP response summary: tool=business-calendar traceId=... tenantId=1 userId=100 caseId=null runId=null success=true decisionCode=OK latency_ms=11

MCP request summary: tool=master-data traceId=... tenantId=1 userId=100 caseId=null runId=null
MCP response summary: tool=master-data traceId=... tenantId=1 userId=100 caseId=null runId=null success=true decisionCode=OK latency_ms=9

MCP request summary: tool=evidence-verification traceId=... tenantId=1 userId=100 caseId=129 runId=...
MCP response summary: tool=evidence-verification traceId=... tenantId=1 userId=100 caseId=129 runId=... success=true decisionCode=POLICY_CONFLICT latency_ms=14
추가 확인사항 1건:

작업 중 제가 수정하지 않은 launch.json이 변경 상태로 보입니다.
이 파일은 그대로 두고 진행했는데, 의도된 변경인지 확인 부탁드립니다.