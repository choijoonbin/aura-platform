# 이번 기능 개발 관련 Aura → 백엔드 전달 사항

백엔드 구현 내용(back.txt 기준)과 Aura 측 구현을 맞춘 전달 사항입니다.

---

## 1. 연동 정합성 확인

| 항목 | 백엔드 구현 | Aura 측 |
|------|-------------|--------|
| **트리거** | 케이스 생성 직후 `CaseAnalysisService.triggerAnalysis` → Aura `triggerAnalyze()` | `POST /aura/cases/{caseId}/analysis-runs` 수신 즉시 분석 개시(사용자 질문 불필요) |
| **202 응답** | runId, streamUrl 등 수신 | `status: ACCEPTED`, `runId`, `caseId`, `streamUrl: "/aura/analysis-runs/{runId}/stream"` 반환 |
| **분석 시작 알림** | `analysis_started` → Redis `workbench:case:action` → WebSocket | 트리거와 동시에 백그라운드 분석 시작, SSE 이벤트 발행 |
| **FE 스트림** | payload.run_id, stream_url로 `GET /api/synapse/analysis-runs/{runId}/stream` SSE 연결 | `GET /aura/analysis-runs/{runId}/stream` 에서 started → step → evidence → confidence → proposal → completed 순서로 이벤트 전송 |

**전달 요약**: 트리거·스트림 URL·알림 흐름은 현재 명세와 일치합니다. Authorization, X-User-ID 전달 시 Aura 호출 정상 동작합니다.

---

## 2. 콜백 finalResult — 신규 필드 (저장/API/UI 반영 권장)

분석 완료 시 Aura가 **기존과 동일한 콜백 URL**로 POST하며, `finalResult` 안에 아래 **4개 필드가 추가**되었습니다.  
케이스 종결·대시보드 표시용으로 저장·노출하시면 됩니다.

| 필드 | 타입 | 설명 |
|------|------|------|
| **risk_score** | number (0~100) | 위험 점수 (기존 score 0~1을 100 단위로 변환) |
| **violation_clause** | string | 위반 규정 조항 (예: "제11조 2항", 없으면 "") |
| **reasoning_summary** | string | 판단 근거 요약 (기존 reasonText와 동일 내용) |
| **recommended_action** | string | 권고 조치 요약 (proposals의 rationale을 "; "로 이어붙인 문자열) |

- **콜백 URL**: Aura 설정 `DWP_GATEWAY_URL` + `CALLBACK_PATH` (기본값: `{gateway}/api/synapse/internal/aura/callback`)
- **Body**: 기존과 동일하게 `runId`, `caseId`, `status`, `finalResult` (기존 score, reasonText, proposals 등 + 위 4필드)

---

## 3. SSE step 이벤트 — Thought Chain 문구 보강

FE에서 `GET .../analysis-runs/{runId}/stream` 구독 시, **step** 이벤트의 `detail`을 그대로 "Thought Chain" 문구로 노출할 수 있습니다.

| label | detail (예시) |
|-------|-------------------------------|
| INPUT_NORM | 케이스 입력 정규화 중 |
| EVIDENCE_GATHER | 케이스 전표 데이터 및 연관 증거 수집 중 |
| REGULATION_MATCH | 전표·가맹점 맥락을 바탕으로 사내 규정(Vector DB) 매칭 중입니다. |
| RULE_SCORING | 규정 제한 업종·금액·시간 기준 위반 여부 검토 중입니다. |
| LLM_REASONING | 규정 조문과 대조하여 위반 여부 판단 및 판단 근거 작성 중입니다. |
| PROPOSALS | 권고 조치(결제 보류·추가 확인 등) 생성 중입니다. |

- **이벤트 형식**: `event: step`, `data: {"label": "...", "detail": "...", "percent": N}`  
- Aura AI Workspace에 단계별 상태를 실시간으로 표시할 때 위 `detail`을 사용하시면 됩니다.

---

## 4. GET /aura/cases/{caseId}/analysis 응답 보강

분석 완료 후 **GET** `/aura/cases/{caseId}/analysis` 호출 시에도 위 4필드가 포함됩니다.  
(기존 reasonText, proposals, score, severity 등과 함께)

- `risk_score` (0~100)
- `violation_clause`
- `reasoning_summary`
- `recommended_action`

BE가 동일 케이스에 대해 자체 API로 결과를 캐시/저장했다면, 콜백 수신 시점에 위 필드를 함께 저장해 두고 FE에 그대로 전달하시면 됩니다.

---

## 5. 정리

- **이번 기능**: 자동 트리거 수신 즉시 분석, 단계별 상태(step) 문구 보강, 분석 결과에 risk_score·violation_clause·reasoning_summary·recommended_action 추가.
- **백엔드 권장 대응**:  
  1) 콜백 수신 시 `finalResult` 내 신규 4필드 저장·노출.  
  2) FE 스트림 구독 시 step 이벤트의 `detail`을 Thought Chain 문구로 표시.  
- **추가 계약 변경 없음**: 트리거 URL, 스트림 URL, 콜백 URL·메서드는 기존과 동일합니다.

문서: `docs/guides/AUTONOMOUS_AUDIT_PIPELINE.md` (Aura 내부 명세).

---

## 6. 추가 확인사항 (선택)

아래는 연동 검증 시 참고용입니다.

| # | 확인 항목 | Aura 동작 | 권장 확인 |
|---|-----------|-----------|-----------|
| 1 | **stream_url 형식** | 202 Body의 `streamUrl`은 **상대 경로** `"/aura/analysis-runs/{runId}/stream"` | FE에 내려줄 때 BE 프록시 경로(`/api/synapse/analysis-runs/{runId}/stream` 등)로 변환해 전달하는지 확인 |
| 2 | **콜백 엔드포인트** | 분석 완료 시 `POST {DWP_GATEWAY_URL}{CALLBACK_PATH}` 호출 (기본 `.../api/synapse/internal/aura/callback`) | BE가 해당 경로에서 POST 수신·**200** 반환하는지 확인 (Aura는 200 시 성공 처리) |
| 3 | **DEMO_OFF** | 환경변수 `DEMO_OFF=1`(또는 true/yes) 시 트리거가 **202가 아닌 200** + `{"status":"disabled","message":"..."}` 반환 | 해당 응답 시 분석 시작·콜백을 기대하지 않고, 필요 시 "분석 비활성" 처리 |
| 4 | **분석 실패 시 콜백** | 파이프라인 예외 시 `status: "FAILED"`, **finalResult 없음**, `partialEvents: [{ "stage": "callback", "errorMessage": "..." }]` | BE가 FAILED 수신 시 finalResult 미존재를 가정하고, partialEvents로 실패 사유 저장/노출 |
| 5 | **Authorization 전달** | 트리거 요청의 `Authorization` 헤더를 Aura가 백그라운드에서 get_case·search_documents 등 호출 시 재사용 | BE가 Aura 호출 시 동일 헤더를 그대로 전달하면 됨 (back.txt 반영됨) |

---

## 7. Synapse 스키마 코드 일치 (엔진 키값)

Aura 엔진이 사용하는 구분값은 **Synapse DB 코드와 동일**하게 유지합니다.

| 구분 | 코드값 (DB와 동일) | Aura 사용처 |
|------|--------------------|-------------|
| **DOC_TYPE** | `REGULATION`, `HIERARCHICAL`, `GENERAL` | RAG 청킹/필터: `core/synapse_schema.py` → `core/analysis/rag.py` |
| **model_name** | 백엔드 에이전트 설정의 `model_name` (예: `gpt-4o-mini`, `gpt-4o`) | 에이전트 빌드 시 LLM 엔진: `agent_config.model_name` → `get_llm_client(model_name)` |

- 단일 정의: `core/synapse_schema.py` (DOC_TYPE 상수, `resolve_model_name()`).
- 에이전트 설정 API에서 `model_name` 내려주면 해당 엔진으로 분석 실행.

---

## 8. 동적 프롬프트 주입 (system_instruction)

- 에이전트 설정 API 응답에 **`system_instruction`** (문자열)이 있으면, 엔진은 이를 **최우선**으로 system_message에 사용합니다. 없을 때만 `system_prompt_key`에 따라 Aura 내부 `get_system_prompt()` Fallback.
- **실행 시점마다** API로 설정을 조회하므로, 스튜디오(UI)에서 수정한 프롬프트는 **엔진 재시작 없이** 다음 Run부터 반영됩니다.
- Seed: Finance 감사 에이전트 페르소나를 DB로 이관하는 INSERT는 `docs/handoff/SEED_AGENT_PROMPT_FINANCE.sql` 참고. 백엔드가 `agent_prompt_history` 등에서 조회한 내용을 설정 API의 `system_instruction` 필드로 내려주면 됩니다.
- **“Aura 현재 사용 중인 프롬프트” 전부 디폴트로 등록**: `docs/handoff/ALL_SYSTEM_PROMPTS_DEFAULT.txt`에 **현재 등록된 6개 도메인(base, dev, finance, hr, code_review, issue_manager) 전문**을 모두 넣어 두었습니다. 각 구역(BEGIN/END domain: xxx) 안의 본문만 복사해 해당 `system_prompt_key`의 `system_instruction`으로 등록하면 됩니다.
- Finance만 쓰는 경우: `docs/handoff/FINANCE_SYSTEM_PROMPT_DEFAULT.txt`에서 finance 전문만 복사해 V55 등에 넣으면 됩니다.

---

## 9. Aura 호출 시 전달 방식 (에이전트 설정 API)

| 단계 | 주체 | 내용 |
|------|------|------|
| 1 | Aura | **GET /api/v1/agents/config?agent_key=finance_aura** (Header: X-Tenant-ID, Authorization 필수) |
| 2 | 백엔드 | Gateway → `/api/synapse/agents/config`, Query 유지. `AgentConfigQueryService.getAgentConfig()` |
| 3 | 백엔드 | 에이전트에 매핑된 도구를 **agent_tool_inventory**에서 조회 |
| 4 | 백엔드 | **ApiResponse** 래퍼, **data** 키에 설정 (camelCase). **tools[]**: toolName, description, schemaJson. **version** (Integer, agent_prompt_history 현재 버전) 포함 |

- Aura는 응답 **data**를 파싱해 **tools[].toolName**을 모아 **agent_tool_mapping**으로 사용하고, **systemInstruction**, **model.modelName**, **version** 등을 매핑합니다.
- agentId(Long) 없이 **agent_key**만으로 조회 가능. (agentId로 조회 시: GET /api/v1/agents/{id}/config)
- **agent_id ↔ agent_key**: Aura 호출 시 `agent_id` 파라미터가 그대로 **agent_key** 쿼리로 전달됨. BE에 `audit`이 없고 `finance_aura`만 있으면 호출부에서 `agent_id="finance_aura"` 사용 또는 BE에 `audit` 시드 추가.  
- 백엔드 측 반영 문서: `AURA_AGENT_API_QUESTIONS_RESPONSE.md`, `AURA_AGENT_API_SPEC.md` (Aura 반영 상태·요약 표 포함).
