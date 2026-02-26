
우선순위 A (정확도 직결)
1. Policy/Regulation MCP
    * 규정 원문, 버전, 시행일, 폐기일, 예외조항을 표준 API로 제공
    * 분석 시점 기준 규정만 조회해서 “시점 오판” 제거
2. Business Calendar MCP
    * 국가 공휴일 + 사내 휴무 + 부서별 캘린더 조회
    * isHoliday를 BE 힌트에 의존하지 않고 에이전트가 독립 검증
3. Master Data MCP
    * MCC, 계정과목, 비용코드, vendor risk, 권한 체계 조회
    * 코드값 해석 오류/하드코딩 제거
4. RAG Index MCP
* 문서 활성버전, 인덱스 버전, 청크 품질상태를 조회
* “왜 0건인지”를 검색 엔진이 아니라 운영 메타까지 포함해 진단
우선순위 B (행동지능/Agentic 강화)5. Case Context MCP
* SAP 전표 헤더/아이템, 히스토리, 유사 케이스를 표준 툴로 호출
* get_case fallback 남발 없이 필요한 데이터만 단계적으로 수집
1. Evidence Verification MCP
    * 결론 문장별 citation 검증(조항 존재/문장 매핑)을 별도 툴로 강제
    * 환각 결론을 파이프라인 끝단에서 차단
2. Action Simulation MCP
* 결제차단/역분개/추가소명요청을 “시뮬레이션 모드”로 먼저 실행
* 운영 리스크 없이 정책 효과 테스트 가능
우선순위 C (엔터프라이즈 운영성)8. Audit Ledger MCP
* reasoning 요약, 사용 tool, 입력/출력 해시를 append-only로 적재
* 감사 대응, 사후분석, 책임추적 강화
1. Evaluation MCP
    * 골든셋 리플레이, hit@k, citation 정합률, 보류율 자동 산출
    * 배포 전/후 품질 게이트 자동화
2. Access Control MCP
* 툴별 권한(tenant, role, purpose)과 데이터 마스킹 정책 중앙화
* 멀티테넌트 누수/과다조회 차단
도입 원칙(중요)
1. 읽기 툴과 쓰기 툴을 분리하고, 쓰기는 Human 승인 게이트 필수
2. MCP 응답은 모두 version, effective_from/to, source 포함
3. tool timeout/실패 시 표준 강등응답(판정보류)으로 일관 처리
4. “근거 없는 결론 금지”를 MCP 검증 툴에서 기계적으로 enforce





Phase 1 (정확도 기반)
1. Policy/Regulation MCP
    * Aura: 규정조회 툴 어댑터, 시점판정 로직
    * BE: 규정 버전/시행일 API
    * KPI: 잘못된 조항 인용률 감소, RAG 0건률 감소
2. Business Calendar MCP
    * Aura: 휴일 독립검증 체인
    * BE/외부: 공휴일/사내휴무 데이터 소스
    * KPI: 휴일 분류 정확도, HOLIDAY_USAGE 오탐률 감소
3. Master Data MCP
    * Aura: 코드값 해석 툴 호출
    * BE: MCC/계정/권한 마스터 API
    * KPI: 코드 해석 오류율 감소
4. RAG Index MCP
* Aura: 인덱스 상태 진단 분기
* BE: active version/quality 상태 API
* KPI: “원인 미상 RAG 실패” 비율 감소
Phase 2 (검증/행동 지능)5. Case Context MCP
* Aura: 단계별 데이터 수집(필요 시만 호출)
* BE: 전표/히스토리/유사사례 API
* KPI: INPUT_PARTIAL 비율 감소
1. Evidence Verification MCP
    * Aura: 문장-인용 강제검증
    * BE(선택): 검증 결과 저장
    * KPI: SENTENCE_CITATION_MISSING 비율 감소
2. Action Simulation MCP
* Aura: 조치 시뮬레이션 플로우
* BE: 결제차단/역분개 시뮬레이션 API
* KPI: 조치 추천 신뢰도, 잘못된 자동조치 0
Phase 3 (운영/거버넌스)8. Audit Ledger MCP
* Aura: 실행해시/근거요약 적재
* BE/인프라: append-only 저장소
* KPI: 감사추적 완결성(누락 0)
1. Evaluation MCP
    * Aura: 리플레이/평가 실행
    * CI/BE: 배포게이트 및 결과 저장
    * KPI: gate 통과율, 회귀 탐지율
2. Access Control MCP
* Aura: 툴 호출 전 권한컨텍스트 전달
* BE/인증: tool-level RBAC/ABAC
* KPI: 권한 위반 호출 0, 테넌트 누수 0
난이도/의존도
1. Phase 1: 중~상, BE 의존 중간
2. Phase 2: 상, BE 의존 큼
3. Phase 3: 상~최상, BE+FE+CI 의존 큼
Aura 단독으로 먼저 가능한 시작점
1. Evidence Verification MCP 프로토타입
2. Evaluation MCP 로컬 실행 확장
3. RAG Index 진단 어댑터(임시 API/모의 응답 기반)







---

## MCP 도입 최종 로드맵 (확정안, 2026-02-26)

### 목적
- Aura 분석 정확도와 재현성을 엔터프라이즈 기준으로 끌어올리기 위해, LLM 추론과 사실판정(Fact/Rule)을 분리한다.
- MCP는 "정확도 자체"가 아니라 "데이터/툴 접근 표준화" 역할로 도입한다.

### 핵심 원칙
1. 판정 책임 분리: BE 정책엔진(결정론) = 위반/비위반 판정, Aura LLM = 설명/요약/예외 해석.
2. Payload-first: analysis-runs payload를 1차 신뢰소스로 사용, 누락 시에만 MCP/Tool fallback 호출.
3. 근거 강제: 문장별 citation_id 없는 결론 문장 금지.
4. 보수적 강등: RAG_ZERO, EVIDENCE_MISSING, POLICY_CONFLICT 발생 시 확정 위반 금지.
5. 추적 가능성: 모든 결과는 quality_gate_codes + sentence_citation_map + score_breakdown으로 남긴다.

### Phase 1 (P0) - Fact/Rule 정합성 고정
목표: 환각/임의문장 제거, 근거 없는 위반 결론 차단
- Policy/Regulation MCP(읽기)
  - 규정 조항, version, effective_from/to 조회 표준화
- Business Calendar MCP(읽기)
  - isHoliday 판단 근거를 표준 소스에서 조회(주말/휴무/법정공휴일)
- Master Data MCP(읽기)
  - mcc, expenseType, hrStatus 정규화/의미어 해석
- KPI
  - citation 누락률 감소
  - RAG 0건 이후 확정위반 출력 0건
  - HOLIDAY_USAGE 오탐률 감소

### Phase 2 (P1) - 증거 검증/시계열 강화
목표: "그럴듯한" 문장 대신 "검증된" 문장만 통과
- Case Context MCP(읽기)
  - window_10m_txn_count, 24h/30d 맥락, 유사케이스 통계
- Evidence Verification MCP(검증툴)
  - citation_id ↔ article 매핑 검증, 불일치 시 POLICY_CONFLICT
- RAG/Policy 충돌 재평가 루프
  - 재검색 1회 + 보류 코드화
- KPI
  - SENTENCE_CITATION_MISSING 감소
  - POLICY_CONFLICT 탐지 후 보류 전환율 100%
  - 동일입력 동일결론율(재현성) 상승

### Phase 3 (P2) - 거버넌스/운영 게이트
목표: 운영 중 품질 하락 자동 차단
- Evaluation MCP/Replay Gate
  - 골든셋 리플레이 점수 저장 및 배포 게이트 연동
- Audit Ledger
  - append-only 감사추적(결정 코드/근거 해시/모델버전)
- Access Control
  - tool-level RBAC/ABAC + tenant 경계 검증
- KPI
  - DEFAULT 유입률 안정화
  - 품질게이트 미달 배포 0건
  - 테넌트 누수 0건

### 구현 순서 (실행 권장)
1. Phase 1 먼저 완성 (가장 큰 정확도 개선 구간)
2. Phase 2로 근거 검증과 시계열 맥락 보강
3. Phase 3로 운영 게이트 자동화

### 비고
- FE는 신규 화면 없이 기존 화면에 문장-근거/게이트코드 위치만 확정해도 충분함.
- MCP는 점진 도입(기존 tool 계약 유지 + MCP 어댑터 병행)으로 리스크 최소화.

---

## 타 시스템 전달 프롬프트 파일
- BE 전달용: `docs/handoff/MCP_BACKEND_PROMPT_FINAL.md`
- FE 전달용: `docs/handoff/MCP_FRONTEND_PROMPT_FINAL.md`
- BE 1차 점검 보완: `docs/handoff/MCP_BACKEND_REVIEW_FIXES_P0_P1.md`


---

## PM 진행 현황 (MCP 고도화 트랙)

기준일: 2026-02-26
용어 통일: 기존 "대시보드"는 모두 "통합워크벤치"로 표기

### 1) 시스템별 상태
- AURA: 착수/진행 중
  - 완료: MCP adapter(payload-first) 도입
  - 완료: MCP hybrid 모드(dwp-mcp-server 실호출) 연동
  - 완료: Screening/Analysis에 fact context 연결
  - 완료: FACT_CONTEXT_PARTIAL 보수 게이트 추가
  - 완료: MCP fact context 운영 로그 추가
- BE: 착수(팀 진행 중)
  - 대기: Policy/Calendar/Master MCP Tool 계약 확정
  - 대기: sentence-citation 검증 API/저장 연동
- FE: 착수(팀 진행 중)
  - 대기: 기존 화면에 quality_gate_codes/sentence_citation_map/score_breakdown 위치 확정

### 2) Aura 이번 반영 상세
- 파일: `core/analysis/mcp_adapter.py`
  - payload 기반 표준 fact context 생성기 추가 (mode: payload_only)
- 파일: `core/config.py`
  - `mcp_enabled`, `mcp_mode`, `mcp_require_fact_for_violation` 추가
- 파일: `core/analysis/precheck_pipeline.py`
  - screening context에 `mcp_fact_context` 포함
  - 단건/배치 로그에 mcp missing 필드 요약 추가
- 파일: `core/analysis/analysis_pipeline.py`
  - 입력 정규화 직후 mcp fact context 생성/누락필드 보강
  - evidence에 `MCP_FACT_CONTEXT` 추가
  - `FACT_CONTEXT_PARTIAL` 품질게이트(확정 위반 보류) 추가

### 3) 크로스시스템 의존성(진행 필요)
1. BE에서 MCP Tool 응답 표준 필드 확정
2. FE에서 보류코드/문장근거 맵 렌더 위치 반영
3. 통합 E2E 테스트(동일 케이스 3회 재현성 + RAG_ZERO/POLICY_CONFLICT)

### 4) 다음 점검 포인트
- AURA 로그 확인 키워드
  - `audit_analysis mcp_fact_context`
  - `FACT_CONTEXT_PARTIAL`
- 기대 동작
  - 필수 fact 누락 시 확정 위반 문구 대신 보류 문구
  - sentence-citation, quality_gate_codes와 충돌 없이 함께 내려감

#프론트 작업결과 1차
변경 사항

통합 워크벤치(workbench-new) 반영
quality_gate_codes 배지 표시(우선순위 정렬 포함)
sentence_citation_map 표 렌더링 + 근거 미연결 경고
citation 클릭 시 하단 citation 목록으로 점프/하이라이트
score_breakdown(정책/근거/최종점수, 보류 사유) 카드 추가
POLICY_CONFLICT/RAG_ZERO 시 보류 안내 문구 표시
운영자 디버그 섹션 추가(raw quality_report, quality_gate_codes, mismatch_reasons, sentence_citation_map)
파일: workbench-new-case-panel.tsx, index.tsx
기존 관리자 분석 탭 디버그 확장
운영자 디버그에 raw quality_report, mismatch_reasons 추가
파일: case-analysis-tab.tsx
검증

yarn eslint 통과
yarn tsc --noEmit 통과
즉, “질문 없으면 바로 진행”으로 요청하신 작업은 이번에 반영 완료되었습니다.

---

## MCP PM 트래커 (최신, 2026-02-26)

### 현재 단계 요약
- 현재 상태: `Phase 1 (P0)` 구현 완료, 통합 테스트 진행 중
- 현재 우선순위: 휴일(HOLIDAY_USAGE) 케이스 정확도/근거 정합성 안정화
- 진행 원칙: `Payload-first` 유지 + MCP fact/tool 보강 + 보수적 판정보류 게이트

### 완료(확정)
- [x] Aura MCP adapter 도입 (`payload_only` + `hybrid` 구조)
- [x] Analysis/Screening에 fact context 연결
- [x] 사실 컨텍스트 누락 시 보류 게이트(`FACT_CONTEXT_PARTIAL`)
- [x] 문장-근거 매핑/분석 점수분해/신뢰신호(quality_gate_codes) 출력 강화
- [x] 스트림 중복 문구 억제 및 문장 표현 보정
- [x] Screening 점수/심각도 표준 가중치 로직 반영 (CRITICAL 포함)
- [x] FE/BE 전달 프롬프트 1차 배포 완료

### 진행 중(테스트/튜닝)
- [ ] MCP 실제 호출 경로 실증(로그 기준 `mode=hybrid`, `calls_ok>0` 확인)
  - 2026-02-26 반영: `X-Tenant-ID`/`X-User-ID` 누락 시 원격 MCP 호출을 스킵하고 `MCP_HEADERS_MISSING` 사유를 quality에 기록하도록 Aura 보강 완료
- [ ] 휴일 케이스 1건 확정 통과
  - 기준: caseType/score_breakdown/reasonText/근거매핑 정합
  - 2026-02-26 반영: 휴일+휴무 신호(`isHoliday=true` + `LEAVE/OFF/VACATION`)일 때 `PRIVATE_USE_RISK/UNUSUAL_PATTERN/LIMIT_EXCEED`를 `HOLIDAY_USAGE`로 승격하는 정렬 규칙 추가
- [ ] RAG 조항 정합(위험유형-조항 불일치 감소) 재검증
- [ ] SSE/agent_activity_log 문구 품질 회귀 확인

### Aura 즉시 반영(2026-02-26)
- MCP adapter
  - `X-User-ID` 누락 상태에서 `/master-data`를 호출해 400이 발생하던 흐름 제거
  - 헤더 누락 시 `mcp_skip_reason=MCP_HEADERS_MISSING`, `mcp_missing_headers=[...]` 로그/quality로 추적 가능
  - `business-calendar.userId`는 int 강제 캐스팅을 제거하고 문자열 그대로 전달
- Screening
  - 휴일/휴무 조합 케이스에서 `HOLIDAY_USAGE` 우선 승격 규칙 강화
- Analysis
  - Aura finalResult에 `analysis_quality_signals` 직접 포함(표시명 배열), BE fallback 의존도 축소

### 잔여 작업 (Phase 2 / P1)
- [ ] `Case Context MCP` 연계 강화
  - `window_10m_txn_count`, 24h/30d 맥락, 유사케이스 통계 활용
- [ ] `Evidence Verification MCP` 본격 적용
  - citation_id ↔ article 검증툴 강제, 불일치 시 보류 전환 일관화
- [ ] RAG/Policy 충돌 재평가 루프 표준화
  - 1회 재검색 + 보류 코드화 + 운영 집계 연동

### 잔여 작업 (Phase 3 / P2)
- [ ] `Evaluation MCP` / replay gate 운영 연동
  - 최신 eval-run 기반 배포 게이트(로컬/운영 공통 기준)
- [ ] `Audit Ledger`(append-only) 정식 적용
  - 판단 코드, 근거 해시, 모델/프롬프트 버전 추적
- [ ] `Access Control` 강화
  - tool-level RBAC/ABAC + tenant 경계 테스트 자동화

### 시스템별 대기/의존
- AURA
  - [ ] MCP hybrid 실호출 안정화 로그 검증
  - [ ] 분석 신뢰 신호 코드/표시명 계약 최종 반영
- BE
  - [ ] eval-run/latest 응답키 최종 고정 및 집계 API 정합성 확인
  - [ ] case_analysis_result 신뢰신호 필드 저장/집계 검증
- FE
  - [ ] `평가 데이터 없음` 상태 표기 통일
  - [ ] 신뢰지표/신뢰신호 용어 반영 및 맵핑키 최종 고정

### 다음 회의/테스트 때 확인할 로그 키워드
- `mcp_adapter resolved stage=... mode=hybrid ... calls_ok=...`
- `audit_analysis quality_gate ... codes=[...]`
- `analysis_pipeline: RAG summary ...`
- `SENTENCE_CITATION_MAP`
