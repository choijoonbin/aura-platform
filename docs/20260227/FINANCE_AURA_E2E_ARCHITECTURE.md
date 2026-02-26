# Finance Aura Agentic AI E2E 아키텍처 (발표본)

> 대상: PM, 아키텍트, FE/BE 연동 개발자, 운영 담당자  
> 목적: "현재 우리 에이전트가 어떻게 동작하는지"와 "어디까지 고도화됐고, 다음에 무엇을 할지"를 명확히 설명

---

## 1. 한 장 요약

Finance Aura는 **2단 구조**로 동작한다.

1. **스크리닝(Precheck)**: 대량 전표를 빠르게 위험유형으로 1차 분류  
2. **분석(Analysis)**: 규정 근거(RAG) + 정책 신호 + 품질게이트를 결합해 최종 판정

핵심 포인트:
- 단순 프롬프트 응답이 아니라, **파이프라인 기반 Agentic 실행**
- 근거 부족 시 확정 위반을 막는 **보수적 게이트** 적용
- 결과는 SSE/콜백으로 추적 가능하게 제공

---

## 2. 용어 통일 (발표 시 필수)

- `트리거` → **스크리닝 요청 수신**
- `독백` → **에이전트 스트림(사고 과정 공개 메시지)**
- `품질게이트코드` → **분석 신뢰 신호(내부코드: quality_gate_codes)**
- `최종 판정` → **reasonText + score/severity + citation 맵 결과**

---

## 3. End-to-End 흐름

```text
[BE] /aura/detect/screen-batch
  -> 스크리닝(caseType/score/severity/reasonText)

[BE] /aura/cases/{id}/analysis-runs (202)
  -> 백그라운드 run 시작
  -> finance_aura 선택 + agent config(docIds/model/system instruction)
  -> analysis_pipeline 실행
  -> SSE(/aura/cases/{id}/analysis/stream)로 진행상태/스트림 전송
  -> callback으로 BE 저장(case_analysis_result)
```

---

## 4. 현재 구현된 에이전트 동작 (핵심)

### 4.1 스크리닝 단계

역할:
- 전표를 6개 위험유형 중 하나로 1차 분류
- 결과: `caseType`, `score`, `severity`, `reasonText`, `score_breakdown`

특징:
- LLM 결과를 그대로 쓰지 않고, **결정론 가중치 로직**으로 보정
- 휴무일/휴가 + 휴일 신호 조합일 때 `HOLIDAY_USAGE` 우선 정렬
- 입력 누락 시 보수적 분류(`INPUT_PARTIAL`) 처리

---

### 4.2 분석 단계 (analysis_pipeline)

분석 단계는 아래 순서로 고정 실행된다.

1. **INPUT_NORM**
- payload-first 정규화
- 부족할 때만 fallback 조회
- MCP fact context 결합

2. **EVIDENCE_GATHER**
- 케이스/문서 근거 수집
- 에이전트 스트림 메시지 생성

3. **RAG_SEARCH**
- doc_ids/tenant 경계 내 규정 검색
- 벡터+키워드 fallback
- 임계치 미달 시 신뢰 신호 반영

4. **LLM_REASONING**
- 정책 신호 + 스크리닝 신호 + RAG 근거 기반 최종 문장 생성
- 위반 단정 문장에 대해 게이트 재검증

5. **PROPOSALS / FINALIZE**
- `quality_gate_codes`
- `analysis_quality_signals`
- `sentence_citation_map`
- `analysis_score_breakdown`
- 최종 `reasonText`, `score`, `severity`

---

## 5. Agentic AI 관점에서의 구현 수준

### 이미 구현된 Agentic 요소

- 단계별 사고 흐름을 사용자에게 공개하는 **스트림 타임라인**
- 근거 부족/충돌 시 결론을 보류하는 **자가 제어(게이트)**
- 정책/사실 컨텍스트를 결합하는 **MCP 하이브리드 구조**
- 문장별 근거 연결(`sentence_citation_map`) 기반 **설명 가능성 확보**

### 아직 남은 과제

- 도구 호출 완전 자율화(ReAct형)보다, 현재는 **안정성 우선 오케스트레이션**
- 시계열 컨텍스트(10분/24h/30d) 강화
- 근거-결론 일치 자동 검증 고도화

---

## 6. 품질/안전 장치 (엔터프라이즈 핵심)

다음 신호가 발생하면 확정 위반을 제한하거나 보류한다.

- `RAG_ZERO`: 규정 검색 근거 부족
- `EVIDENCE_MISSING`: 핵심 증거 없음
- `INPUT_PARTIAL`: 입력 필드 일부 누락
- `POLICY_CONFLICT_DETECTED`: 신호 충돌
- `SENTENCE_CITATION_MISSING`: 문장-근거 연결 불충분
- `EVIDENCE_COVERAGE_LOW`: 근거 커버리지 낮음
- `FACT_CONTEXT_PARTIAL`: MCP 사실 컨텍스트 불완전

즉, 현재 구조는 "그럴듯한 답변"보다 **근거 기반 보수 판단**을 우선한다.

---

## 7. MCP 반영 현황과 방향

### 현재 반영
- MCP `hybrid` 모드 동작
- 헤더 누락 시 원격 호출 스킵 + 사유 기록(`MCP_HEADERS_MISSING`)
- payload-first 유지 + MCP 보강

### 다음 고도화 (Phase 2~3)
- **Case Context MCP**: 10분/24h/30d 맥락 점수화
- **Evidence Verification MCP**: 문장-조항 매핑 기계검증
- **Evaluation Gate**: 리플레이 결과 기반 품질게이트 자동화

---

## 8. 강점 / 한계 (발표용 비교)

### 강점
- 재현성 높은 단계형 파이프라인
- 감사 대응 가능한 근거 구조
- 근거 부족 시 오판을 줄이는 보수 제어
- FE/BE/Aura 분업이 가능한 표준 결과 스키마

### 한계
- 도구 호출 시점이 완전 자율은 아님
- RAG 인덱스 품질에 따라 품질 편차 발생 가능
- MCP/BE 데이터 품질이 낮으면 판정 신뢰도 하락

---

## 9. 발표 결론 문장 (권장)

"Finance Aura는 이미 단순 챗봇이 아니라, 스크리닝-분석-근거검증-보수게이트를 갖춘 엔터프라이즈형 Agentic AI 구조로 전환되었습니다. 다음 단계는 MCP 기반 사실/근거 검증을 더 강화해, 정확도와 감사 대응력을 동시에 높이는 것입니다."

---

## 10. 참고 코드 경로

- API 진입: `api/routes/aura_cases.py`
- 스크리닝: `core/analysis/precheck_pipeline.py`
- 분석 파이프라인: `core/analysis/analysis_pipeline.py`
- 스트림 생성: `core/analysis/thought_stream.py`
- MCP 어댑터: `core/analysis/mcp_adapter.py`
- 도구 연동: `tools/synapse_finance_tool.py`
