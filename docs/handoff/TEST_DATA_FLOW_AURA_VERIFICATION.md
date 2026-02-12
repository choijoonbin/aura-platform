# 테스트 데이터 생성 플로우 — Aura 해당 부분 점검 결과

시나리오 생성(테스트 데이터 생성) 플로우 중 **Aura에 해당되는 3·4·5단계**가 구현·문서와 일치하는지 점검한 결과입니다.

---

## 3단계: [백엔드 → Aura] AI 분석 트리거 (자동 호출)

| 요구 | Aura 구현 | 상태 |
|------|-----------|------|
| 백엔드가 사람 버튼 없이 Aura 분석 API 즉시 호출 | `POST /aura/cases/{caseId}/analysis-runs` 수신 시 202 즉시 반환, 백그라운드에서 분석 시작 | ✅ |
| "Aura에 전표 데이터를 전송하나요?" → 전표·규정집 맥락 전달 | **Body**에 선택 필드 `evidence` (문서/라인/오픈아이템/거래처 등) 전달 가능. **또한** Aura가 caseId 기준으로 `get_case`(케이스/전표), `search_documents`(문서), `get_open_items`, `get_lineage` 호출로 전표·연관 데이터를 스스로 조회. 규정집 맥락은 **규정 Vector DB(hybrid_retrieve)** 로 자동 로드. | ✅ |

- **정리**: 백엔드는 `caseId`만 넘겨도 되고, 필요 시 `evidence`로 스냅샷을 함께 줄 수 있음. Aura는 전표·규정 맥락을 자동 수집·반영함.

---

## 4단계: [Aura → 백엔드] 실시간 사고 체인(Thought Chain) 전송

| 요구 | Aura 구현 | 상태 |
|------|-----------|------|
| "어떤 처리 후 어떤 값 전달?" | **처리**: 전표·문서 조회(`get_case`, `search_documents`) + **규정집 검색**(`hybrid_retrieve`, Vector DB)으로 규정 매칭 → 룰 스코어링 → LLM으로 위반 여부·근거·조치 생성. **전달**: 분석이 끝난 뒤 한 번이 아니라, **분석 도중** 이벤트를 SSE로 스트리밍. | ✅ |
| 규정집 뒤지고 전표와 대조하는 '추론' | **규정집**: `hybrid_retrieve`(RAG, doc_type=REGULATION). **전표·문서**: `search_documents`(백엔드 API). 둘을 합쳐 `doc_list`로 규정 인용·위반 조항·reasonText 생성. | ✅ |
| 분석 도중 '생각(Thought)' 스트리밍 | 이벤트: `started` → `step` → `evidence` → `confidence` → `proposal` → `completed`. **step**에 `label`/`detail`(예: "규정 제한 업종·금액 기준 위반 여부 검토 중") 포함. 백엔드는 **streamUrl**로 SSE 구독 시 위 이벤트를 실시간 수신 → THOUGHT_STREAM 등으로 프론트 전달 가능. | ✅ |

- **참고**: "규정집" 검색은 **hybrid_retrieve**(Vector DB RAG)가 담당. `search_documents`는 전표/문서 조회용. 둘 다 사용되며, Thought는 step/evidence/confidence 등 SSE로 전달됨.

---

## 5단계: [Aura → 백엔드] 최종 분석 결과 확정

| 요구 | Aura 구현 | 상태 |
|------|-----------|------|
| 위반 조항 | `finalResult.violation_clause` (예: "제11조 2항") | ✅ |
| 위험 점수 (Risk Score) | `finalResult.risk_score` (0~100) | ✅ |
| 판단 근거 | `finalResult.reasoning_summary` (및 `reasonText`) | ✅ |
| 액션 제안 | `finalResult.recommended_action`, `finalResult.proposals` (type, riskLevel, rationale, requiresApproval 등) | ✅ |
| 전달 시점 | 분석 완료 시 **콜백** `POST {CALLBACK_PATH}` (runId, caseId, status=COMPLETED, finalResult) | ✅ |

- **정리**: 6단계에서 말하는 **case_analysis_result** 저장은 백엔드가 이 콜백의 `finalResult`를 받아 저장하면 됨. **thought_chain_log**는 백엔드가 4단계에서 수신한 SSE 이벤트(step/evidence/confidence/proposal)를 그대로 또는 가공해 저장하면 됨.

---

## 요약

- **3단계**: 트리거(analysis-runs), 전표·규정 맥락 전달(evidence 선택 + Aura 자동 수집) — **구현·정리 완료**.
- **4단계**: 규정집(RAG) + 전표 대조 추론, 실시간 Thought Chain(SSE step/evidence/confidence/proposal) — **구현·정리 완료**.
- **5단계**: 위반 조항·risk_score·판단 근거·액션 제안을 콜백 finalResult로 전달 — **구현·정리 완료**.

추가로, **2단계 CASE_ACTION 알림**은 백엔드 발행 구간이며, **4단계 THOUGHT_STREAM**은 백엔드가 Aura SSE를 구독한 뒤 프론트로 넘기는 구간이므로 Aura는 SSE 제공만 담당합니다. **6단계** agent_case / case_analysis_result / action_proposal / thought_chain_log 인서트는 전부 백엔드 책임이며, Aura는 5단계 콜백과 4단계 스트림으로 필요한 데이터를 제공합니다.
