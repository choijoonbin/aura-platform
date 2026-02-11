# Phase3 마무리 작업 — 시스템별 확인·의사결정·질문

> 기준: aura.txt (Phase3 구현 지시서), work.txt (2주 MVP + 4주 고도화 로드맵)  
> **추가 확인사항 답변**: docs/job/PHASE3_FOLLOWUP_PROMPT_BE_AURA_SCHEMA_TRACE_TESTFLAG.txt (BE), docs/job/PHASE3_FOLLOWUP_PROMPT_FE_AURA_SCHEMA_UI_UPDATES.txt (FE)

---

## 0. BE/FE 팔로업 프롬프트 반영 요약

- **BE** (`PHASE3_FOLLOWUP_PROMPT_BE_AURA_SCHEMA_TRACE_TESTFLAG.txt`): error 객체 저장/반환, trace 저장/조회, requiresApproval·checklist 저장/조회, 테스트 플래그 비운영 패스스루 등 **정책·DoD**가 정리되어 있음. Aura는 해당 스키마에 맞춰 콜백 전송 중.
- **FE** (`PHASE3_FOLLOWUP_PROMPT_FE_AURA_SCHEMA_UI_UPDATES.txt`): step 라벨 서버 기준 표시, failed 시 error 객체(message·stage) 처리, requiresApproval 뱃지·checklist 영역 등 **UI/처리 규칙**이 정리되어 있음. Aura는 스트림에서 동일 스키마(failed 시 error: { message, stage }) 전송.

**Aura 정합 사항**
- **콜백**: FAILED 시 `error: { message, stage }`, `trace: { auraTraceId, policyVersion }`, proposals에 `requiresApproval`, `checklist` 포함.
- **스트림 failed**: `event: failed` 의 data에 **error: { message, stage }** 로 전송 (FE에서 message 표시·stage로 재시도 안내 가능). stage 값: **rag**, **llm**, **pipeline**, **background** (BE 문서의 "callback"|"unknown"은 콜백 전송 실패 등 BE 측 매핑용).
- **테스트 플래그**: Header `X-Aura-Test-Fail: rag|llm` 또는 query `?test_fail_query=rag|llm`. BE는 비운영에서만 패스스루 권장.

---

## 1. Aura 측 반영 완료 사항 (aura.txt 기준)

| 항목 | 반영 내용 |
|------|-----------|
| **스트림 이벤트** | started → step(Normalize evidence 20%) → step(RAG retrieve 45%) → agent(PolicyAgent) → step(Scoring 70%) → agent → step(Propose actions 80%) → step(Callback sending 95%) → completed / failed |
| **RAG** | ragRefs 최소 2건(청크 2개 이상 시), refId/sourceType/sourceKey/excerpt/score 스키마 |
| **콜백 스키마** | analysis.confidenceBreakdown, evidence[].key·detail, error: { message, stage }(FAILED 시), trace: { auraTraceId, policyVersion } |
| **proposals** | requiresApproval, checklist(빈 배열) 추가 |
| **테스트 플래그** | **X-Aura-Test-Fail: rag \| llm** (header) 또는 **?test_fail_query=rag \| llm** (query) — 해당 단계에서 의도적 실패 → failed 이벤트 + FAILED callback(error 객체 포함) |

---

## 2. 각 시스템 확인 사항 (팔로업 프롬프트 답변 반영)

BE·FE 팔로업 프롬프트에 **정책·DoD·UI 규칙**이 답변으로 반영된 상태입니다. 아래는 Aura 관점 정리입니다.

### 2.1 BE (dwp-backend)

| 항목 | Aura 전송 | BE 팔로업 답변 (참고) |
|------|-----------|------------------------|
| **error 스키마** | FAILED 시 **error: { message, stage }** (콜백·스트림 동일) | 객체 저장/반환 표준 채택, 레거시 시 errorMessage 병행 가능 |
| **trace** | **trace: { auraTraceId, policyVersion }** | 저장/조회 반영, 감사로그 연계 권장 |
| **proposals** | **requiresApproval**, **checklist**(빈 배열) | 저장/조회 반영 |
| **테스트 플래그** | Header/query로 rag\|llm 수신 | 비운영에서만 패스스루, prod 차단/권한 제어 |
| **stage 값** | rag, llm, pipeline, background | BE 문서의 "callback"\|"unknown"은 BE 측 매핑용 |

### 2.2 FE (dwp_frontend)

| 항목 | Aura 전송 | FE 팔로업 답변 (참고) |
|------|-----------|------------------------|
| **step 라벨** | 서버에서 label 그대로 전달 (고정 리스트 없음) | 서버 label 그대로 렌더, 하드코딩 금지 |
| **failed error** | **error: { message, stage }** (스트림·콜백 동일) | message 기본 표시, stage는 보조/재시도 안내, string 호환 유지 |
| **proposals** | requiresApproval, checklist | requiresApproval 뱃지, checklist 1개 이상 시 "추가 확인사항" 표시, 빈 배열 시 숨김 |

---

## 3. 기타 의사결정 (팔로업에서 정리된 항목)

| 구분 | BE/FE 팔로업 답변 |
|------|-------------------|
| **테스트 플래그** | BE: 비운영에서만 패스스루, prod 무시 또는 403. FE: 운영 비노출, dev/test에서만 "실패 시나리오" 전달(BE 경유). |
| **trace 연계** | BE: RUN_COMPLETED/RUN_FAILED 감사 이벤트에 auraTraceId 포함 권장. |
| **checklist** | 현재 빈 배열 유지, 고도화에서 채우기. |

---

## 4. Aura 구현 체크리스트 (BE/FE 프롬프트 정합)

| 구분 | Aura 동작 | 참조 |
|------|-----------|------|
| 콜백 FAILED | error: { message, stage }, trace, proposals: [] | BE §1-1, aura.txt §4 |
| 콜백 COMPLETED | analysis.confidenceBreakdown, evidence[].key·detail, trace, proposals[].requiresApproval·checklist, error: null | aura.txt §4 |
| 스트림 failed | data.error: { message, stage }, stage ∈ rag|llm|pipeline|background | FE §1-2 |
| 스트림 step | label 서버 발행 그대로 (Normalize evidence, RAG retrieve, Propose actions, Callback sending 등) | FE §1-1 |
| 테스트 플래그 | X-Aura-Test-Fail (header) 또는 test_fail_query (query), rag\|llm | BE §3, aura.txt §5 |

---

## 5. work.txt 로드맵 참고 (이번 개발 종료 후)

- **Week 3**: 재시도/중복/비교 UX, latest=true 조회, proposal versioning
- **Week 4**: 권한 분리, 멀티 에이전트, "왜 이 제안인가" 근거 탐색, run 디버그 패널

Phase3 마무리 작업은 2주 MVP Gate(시나리오 1·2·3) 기준으로 반영 완료. BE/FE 팔로업 프롬프트(추가 확인사항 답변) 반영 및 Aura 정합 검증 완료.
