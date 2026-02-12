# Autonomous Audit Pipeline — 자동 호출 수신 및 즉각 분석

백엔드 [전표 생성 → 케이스 생성 → Aura 자동 호출] 연동 시 Aura의 동작 명세 및 Thought Chain(사고 체인) 보장 사항입니다.

---

## 1. [Trigger Readiness] 자동 호출 수신 및 즉각 분석

- **진입점**: `POST /aura/cases/{caseId}/analysis-runs` (Body: `runId`, `caseId`, 선택 `evidence`)
- **동작**: `caseId` 수신 즉시, **사용자 수동 질문 없이** 다음을 자율 수행합니다.
  - 해당 케이스 **전표·증거** 로드: `get_case`, `search_documents`, `get_open_items`, `get_lineage`
  - **사내 규정(Vector DB)** 로드: `hybrid_retrieve` (pgvector/Chroma, 전표 맥락 bukrs/belnr 반영)
  - **Thought Chain** 개시: 분석 파이프라인이 `started` → `step` → `evidence` → `confidence` → `proposal` → `completed` 이벤트를 SSE로 발행

백엔드가 위 POST를 호출하면 202와 `streamUrl`을 받고, 동시에 백그라운드에서 분석이 시작되며 **사고 과정이 누락 없이** 스트림으로 전달됩니다.

---

## 2. [Real-time Status Update] 분석 단계별 상태 공유

분석의 각 단계마다 **step** 이벤트로 현재 상태를 전송하며, 프론트엔드 'Aura AI Workspace'에 실시간 노출할 수 있습니다.

| label            | detail (예시) |
|------------------|------------------------------------------|
| INPUT_NORM       | 케이스 입력 정규화 중 |
| EVIDENCE_GATHER  | 케이스 전표 데이터 및 연관 증거 수집 중 |
| REGULATION_MATCH | 전표·가맹점 맥락을 바탕으로 사내 규정(Vector DB) 매칭 중입니다. |
| RULE_SCORING     | 규정 제한 업종·금액·시간 기준 위반 여부 검토 중입니다. |
| LLM_REASONING    | 규정 조문과 대조하여 위반 여부 판단 및 판단 근거 작성 중입니다. |
| PROPOSALS        | 권고 조치(결제 보류·추가 확인 등) 생성 중입니다. |

- **SSE**: `event: step`, `data: {"label","detail","percent"}`  
- **스트림 URL**: 202 응답의 `streamUrl` (`GET /aura/analysis-runs/{runId}/stream`) 또는 `GET /aura/cases/{caseId}/analysis/stream?runId={runId}`

---

## 3. [Autonomous Conclusion] 분석 결과 반환

분석 완료 시 백엔드 콜백 및 GET `/aura/cases/{caseId}/analysis` 응답에 아래 구조화 필드를 포함합니다.

| 필드 | 타입 | 설명 |
|------|------|------|
| **risk_score** | 0~100 | 위험 점수 (기존 score 0~1 × 100) |
| **violation_clause** | string | 위반된 규정 조항 (예: "제11조 2항") |
| **reasoning_summary** | string | 판단 근거 요약 (reasonText와 동일) |
| **recommended_action** | string | 권고 조치 요약 (proposals의 rationale 결합) |

- **콜백**: `send_callback(runId, caseId, "COMPLETED", final_result)` 시 `finalResult` 내에 위 필드 포함.
- **GET analysis**: Phase2 결과가 있으면 동일 필드 포함하여 반환.

---

## 4. 자동 트리거 시 Thought Process 누락 없음 점검

- **트리거**: `POST .../analysis-runs`만 호출하면 곧바로 `run_phase2_analysis`가 실행되며, **첫 이벤트(started)** 부터 **completed/failed** 까지 모든 이벤트가 `put_event(run_id, ...)` 로 큐에 적재됩니다.
- **스트림 소비**: FE가 `streamUrl`로 SSE 연결 시 `get_event(run_id, ...)` 로 동일 runId의 이벤트를 순서대로 수신하므로, **자동 트리거에서도 Thought Process(step/evidence/confidence/proposal)가 누락 없이 화면에 기록**됩니다.
- **동기화**: 완료 시 2초 대기 후 큐 제거하여, 스트림이 `completed`를 수신한 뒤 정상 종료되도록 합니다.

---

## 5. 참고 코드

| 구분 | 경로 |
|------|------|
| 트리거·백그라운드 | `api/routes/aura_cases.py` — `case_analysis_runs`, `_run_analysis_background` |
| 파이프라인·step 발행 | `core/analysis/phase2_pipeline.py` — `run_phase2_analysis` |
| 콜백 finalResult | `core/analysis/callback.py` — `_build_final_result`, `send_callback` |
| 스트림 소비 | `api/routes/aura_analysis_runs.py` — `GET /aura/analysis-runs/{runId}/stream` |
