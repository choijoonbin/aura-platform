# Finance Aura Agentic AI E2E 아키텍처 (현행화, 발표본)

> 대상: PM, 아키텍트, FE/BE 개발자, 운영 담당자  
> 목적: "지금 우리 에이전트가 어떻게 동작하는지"와 "왜 이 구조가 엔터프라이즈에 맞는지"를 한 번에 설명

---

## 1. 한 줄 정의

Finance Aura는 **규정 근거 중심 판단 시스템**입니다.  
LLM이 문장을 만들지만, 판정은 **RAG 근거 + 정책 신호 + 품질 게이트**를 통과해야 확정됩니다.

---

## 2. 에이전트 사상 (왜 이렇게 설계했는가)

### 2.1 핵심 철학

1. **근거 없는 확정 금지**
- 그럴듯한 문장보다 근거 연결(citation)을 우선합니다.

2. **자율성 + 안전성 동시 확보**
- 도구 선택/추론은 Agentic하게,
- 확정 판정은 결정론 가드레일로 통제합니다.

3. **Payload-first 원칙**
- BE가 준 사실(payload)을 1차 신뢰소스로 사용하고,
- 부족한 것만 MCP/Tool로 보강합니다.

4. **감사 가능성 우선**
- 결과는 점수, 근거, 문장-근거 매핑, 신뢰 신호로 남겨
- 사후 추적이 가능해야 합니다.

### 2.2 왜 "완전 자유형"이 아닌가

엔터프라이즈 환경에서 완전 자유형 추론만 허용하면 환각/오판 리스크가 큽니다.  
그래서 현재는 **"자율 탐색" + "보수 게이트"**의 하이브리드가 정석입니다.

---

## 3. 현재 E2E 프로세스

```text
[1] 스크리닝 요청 수신
POST /aura/detect/screen-batch
  -> caseType/score/severity/reasonText 1차 분류

[2] 분석 실행 요청 수신
POST /aura/cases/{caseId}/analysis-runs
  -> 202 반환 + 백그라운드 실행 시작

[3] 분석 파이프라인 실행
  INPUT_NORM -> EVIDENCE_GATHER -> REGULATION_MATCH -> RULE_SCORING -> LLM_REASONING -> PROPOSALS

[4] 스트림/저장
  - SSE: 진행 상태(step) + 핵심 근거 이벤트
  - AGENT_EVENT: 영속 이벤트 저장/조회 소스

[5] 최종 콜백
  -> finalResult(reasonText, score, severity, citations, sentence_citation_map, quality signals)
```

---

## 4. LangGraph 설명 (발표 핵심)

## 4.1 이번에 생성한 LangGraph 이미지의 의미

생성 파일:
- `docs/20260227/finance_agent_graph_langgraph.mmd`
- `docs/20260227/finance_agent_graph_langgraph.png`

노드 구조:
- `analyze` -> `evidence_gather` -> `plan` -> `execute` -> `reflect`
- 필요 시 `execute -> tools -> reflect`로 분기

설명 포인트:
1. **analyze**: 케이스 목표/맥락 해석
2. **evidence_gather**: 증거 수집
3. **plan**: 판단 계획 수립
4. **execute**: 규정 대조 및 판정 실행
5. **tools**: 필요 시 외부 도구 호출
6. **reflect**: 자기 검증 및 결론 정리

## 4.2 반드시 함께 말해야 할 점

현재 운영 분석(`analysis-runs`)은 **analysis_pipeline 기반 실행**이 메인입니다.  
LangGraph는 다음 전환 단계(자율형 v2 본체)의 기준 구조이며, 이미 그래프/이벤트 스키마 기반으로 점진 반영 중입니다.

즉, 지금은:
- 실행 본체: `analysis_pipeline`
- 목표 아키텍처: LangGraph형 Agentic 오케스트레이션
- 전환 방식: shadow/점진 전환

---

## 5. 현재 구현된 아키텍처 (컴포넌트)

### 5.1 Screening (Precheck)
- 파일: `core/analysis/precheck_pipeline.py`
- 역할: 대량 전표의 1차 리스크 분류
- 출력: `caseType`, `score`, `severity`, `reasonText`, `score_breakdown`

### 5.2 Analysis Pipeline
- 파일: `core/analysis/analysis_pipeline.py`
- 역할: 정밀 분석/근거 결합/최종 판정
- 출력: `reasonText`, `risk_score`, `severity`, `citations`, `sentence_citation_map`, `analysis_score_breakdown`

### 5.3 Thought/Stream
- 파일: `core/analysis/thought_stream.py`, `api/routes/aura_cases.py`
- 원칙: 임의 문구 최소화, 실제 이벤트 중심
- 현행 기본: `AGENT_EVENT + step` 중심 (디버그는 옵션)

### 5.4 MCP Adapter
- 파일: `core/analysis/mcp_adapter.py`
- 역할: 사실 컨텍스트(휴일/코드 정규화/정책 정보) 보강
- 현행: hybrid 모드, payload-first 유지

### 5.5 RAG / 근거 품질
- 파일: `core/analysis/rag.py`, `core/analysis/rag_quality.py`
- 역할: 규정 검색 + 재랭킹 + 근거맵 연결
- 최근 개선: 휴일 케이스에서 경과조치 고정 인용 제거, 위험유형 정합 재랭킹 강화

---

## 6. 분석 결과 데이터 모델 (발표에서 강조)

최종 결과는 단순 텍스트가 아니라 구조화됩니다.

1. `reasonText`
- 사용자에게 보여줄 최종 판단 문장

2. `citations`
- 인용 근거 목록(C1..)

3. `sentence_citation_map`
- 문장별로 어떤 citation이 연결되는지

4. `analysis_score_breakdown`
- 정책점수/근거점수/최종점수 + KPI 비율

5. `quality_gate_codes` + `analysis_quality_signals`
- 내부 코드 + 사용자 친화 신호

이 구조가 있어야 FE/운영/감사에서 같은 데이터를 서로 다른 레벨로 해석할 수 있습니다.

---

## 7. 품질 게이트 (신뢰도 통제)

주요 신호:
- `RAG_ZERO`
- `EVIDENCE_MISSING`
- `INPUT_PARTIAL`
- `POLICY_CONFLICT_DETECTED`
- `SENTENCE_CITATION_MISSING`
- `EVIDENCE_COVERAGE_LOW`
- `FACT_CONTEXT_PARTIAL`

설명 문구:
- "모델이 맞다고 말했기 때문에 통과"가 아니라,
- "근거/입력/정합 조건을 통과했기 때문에 통과"입니다.

---

## 8. 오늘 기준 현행 상태 요약

1. 휴일 케이스 인용 정합성
- 과거: 경과조치(무관 조항) 고정 인용 문제
- 현재: 휴일/주말/식대 조항 중심으로 정렬 개선

2. 이벤트 스트림
- 기본 모드: compact(핵심 이벤트 중심)
- 디버그 모드: 전체 이벤트 가능(`debugEvents=true`)

3. Shadow Run
- 현재 설정: OFF (`AGENTIC_SHADOW_RUN_ENABLED=false`)
- 단일 run 기준 분석 중

4. v2 agent key
- `finance_aura_v2_agentic` 등록/연동 작업 진행됨

---

## 9. 남은 고도화 방향 (발표용 로드맵)

### 9.1 단기 (정확도 안정화)
1. 문장-근거 연결 정밀도 추가 보정
2. 운영/메타 조항 인용 후순위화 강화
3. 케이스별 점수 근거 설명 문구 표준화

### 9.2 중기 (진짜 Agentic 전환)
1. `finance_aura_v2_agentic`를 LangGraph 실행 본체로 전환
2. 노드/툴 선택을 그래프 상태 기반으로 자율화
3. 기존 파이프라인은 fallback으로 병행

### 9.3 장기 (엔터프라이즈 완성)
1. Evaluation gate 자동화(CI 연동)
2. Audit ledger 강화(append-only)
3. 권한/테넌트 격리 검증 자동화

---

## 10. 발표 결론 멘트(권장)

"Finance Aura는 이미 단순 챗봇이 아니라, 스크리닝-정밀분석-근거검증-품질게이트를 갖춘 엔터프라이즈형 Agentic AI로 전환 중입니다. 오늘 보여드린 LangGraph 구조는 다음 단계의 실행 본체이며, 우리는 정확도와 감사 대응력을 동시에 만족하는 방향으로 점진 전환하고 있습니다."

---

## 11. 참고 코드 경로

- 분석 API: `api/routes/aura_cases.py`
- 스크리닝: `core/analysis/precheck_pipeline.py`
- 정밀분석: `core/analysis/analysis_pipeline.py`
- 스트림 문장: `core/analysis/thought_stream.py`
- MCP 어댑터: `core/analysis/mcp_adapter.py`
- RAG 품질: `core/analysis/rag_quality.py`
- LangGraph 라우트: `api/routes/finance_agent.py`
