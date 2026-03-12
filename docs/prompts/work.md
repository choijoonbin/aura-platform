
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

기준일: 2026-02-27

### 기준 원칙 (합의 고정)
1. Agentic 중심: `finance_aura_v2_agentic` 신규 경로 완성 후 점진 스위칭
2. 기존 안정성 유지: 기존 `analysis_pipeline`은 병행 유지
3. 스트림 무가공 원칙: 실제 이벤트만 노출(임의 진행 문구 금지)
4. 결정론 가드레일: 확정 위반은 근거/정책 검증 통과 시에만 허용

### 액션 4건 즉시 실행 상태
1. PM 트래커 1:1 재정렬: 완료
2. Aura `finance_aura_v2_agentic` 플래그 경로: 완료(플래그+fallback 적용)
3. FE `agent-events` 우선 전환 체크: 진행 중
4. Shadow Run(휴일 3건) 시작 준비: 진행 중

### Phase A - Agentic 실행 기반 (현재)
- [x] AGENT_EVENT 표준 스키마 적용 착수
  - 스키마: `event_type,node,tool,input_hash,output_ref,evidence_ids,decision_code,timestamp`
- [x] 이벤트 타입 정규화
  - `NODE_START/NODE_END/TOOL_CALL/TOOL_RESULT/EVIDENCE_ADDED/GATE_APPLIED/COMPLETED/FAILED`
- [x] Aura MCP payload-first + hybrid 병행
- [x] 품질 보류 게이트 유지 (`RAG_ZERO`, `POLICY_CONFLICT`, `FACT_CONTEXT_PARTIAL` 등)
- [x] `AGENT_EVENT` 영속 푸시 연결
  - Aura `run_store` 이벤트를 Synapse `/api/synapse/agent/events`로 즉시 push
  - 확인 로그: `AGENT_EVENT persisted push ok`
- [x] Shadow 비교 KPI 요약 로그 추가
  - `verdict_match`, `score_delta`, `citation_coverage_delta` 산출/로그
- [x] Optional Tool Plan (P2 선행)
  - `get_open_items` / `get_lineage` 고정 호출 제거
  - 케이스 위험유형 + payload 보유 데이터 기준으로 `REQUESTED/SKIPPED` 분기
  - 로그: `analysis_pipeline: optional_tool_plan ...`
- [x] Agentic v2 Tool Planner 적용 (Aura)
  - v2 경로에서 LLM이 `use_open_items/use_lineage/use_web_search` 계획 산출
  - 결정론 가드레일(payload 보유 데이터 재호출 금지) 유지
- [x] AGENT_EVENT debug 구분 메타 추가
  - `debug_only=true` for `TOOL_CALL/TOOL_RESULT`
- [x] v2 기본 스트림 정책 정리
  - `agentic_v2_emit_agent_stream=false` 기본값으로 AGENT_STREAM(설명형 문장) 억제
  - 표준 이벤트(AGENT_EVENT + step) 중심 운영 고정
- [ ] LangGraph v2 에이전트 실행 경로 완전 분리 (`finance_aura_v2_agentic` 전용 graph runner)

### Phase B - Shadow 비교/스위칭
- [ ] Shadow Run 동시 실행
  - 동일 입력에 대해 legacy vs v2를 병행 실행
  - 비교 지표: 정확도, citation 연결률, 보류율, 지연시간, 재현성
- [x] shadow 비교 요약 이벤트화 (Aura)
  - `node=SHADOW_COMPARE`, `decision_code=SHADOW_MATCH|SHADOW_MISMATCH|SHADOW_UNKNOWN`
  - AGENT_EVENT 영속 푸시 + run 기준 조회 추적 가능
- [ ] Go/No-Go 기준 고정
  - 예: 2주 연속 citation 누락률/오탐률 임계치 통과
- [ ] feature flag 점진 전환
  - 테넌트/케이스유형 단위 canary

### Phase C - MCP 고도화(빠짐없이 유지)
1. Policy/Regulation MCP
2. Business Calendar MCP
3. Master Data MCP
4. RAG Index MCP
5. Case Context MCP
6. Evidence Verification MCP
7. Action Simulation MCP
8. Audit Ledger MCP
9. Evaluation MCP
10. Access Control MCP

### 시스템별 진행/의존
- AURA
  - [x] AGENT_EVENT 표준화/로깅
  - [ ] v2 primary + shadow 실행 경로 고도화
- BE (`dwp-mcp-server`)
  - [ ] MCP v2 tool 응답/로그 표준 고정
  - [ ] shadow 비교 집계 API 안정화
- BE (`synapse`)
  - [ ] agent-events 저장/조회와 case 상세 연계 최종화
- FE
  - [ ] 분석단계 타임라인 소스를 `agent-events` 우선으로 전환
  - [ ] 새로고침 후에도 동일 이벤트 재현 보장

### E2E 검증 기준 (휴일 3건)
- [ ] 케이스별 `NODE_START→...→COMPLETED` 이벤트 체인 확인
- [ ] 문장별 citation 연결 및 근거 목록 일치 확인
- [ ] shadow 비교 로그(`shadow_compare summary`) 생성 확인
