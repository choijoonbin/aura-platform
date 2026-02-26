# FE 협의 프롬프트 (SSE 문장-근거 매핑 표시)

## 목적
분석 스트림에서 문장별 인용 근거를 실시간으로 보여주고, 최종 결과에서도 검증 가능하게 표시

## SSE 이벤트 계약
- event: `evidence`
- payload:
  - `type = "SENTENCE_CITATION_MAP"`
  - `items = [{ sentence_index, sentence, citation_ids: [C1...], grounded }]`
  - `thought_stream = "[결론] 문장별 인용 근거 매핑을 완료했습니다."`

## 용어 변경 (사용자 친화)
- 기존 `품질게이트코드` 용어는 화면에서 사용하지 않음
- 표시 용어:
  - 섹션명: `AI 분석 신뢰도 지표`
  - 코드 목록명: `분석 신뢰 신호`

## FE 구현 요청사항
1. 실시간 패널 추가
- SSE `evidence(type=SENTENCE_CITATION_MAP)` 수신 시 패널 즉시 렌더링
- `grounded=false` 문장을 경고 스타일로 표시

2. citation jump
- `citation_ids` 클릭 시 최종 citations 목록의 동일 `citation_id` 항목으로 스크롤/하이라이트

3. 최종결과 탭 연동
- 다음 필드를 결과 패널에서 표시:
  - `decision_reason.sentence_citation_map`
  - `analysis_score_breakdown`
  - `quality_gate_codes` (디버그/운영자용)
  - `analysis_quality_signals` (사용자 노출용, 있으면 우선 사용)

4. 코드 ↔ 표시문구 매핑
- `OK`: `정상`
- `EVIDENCE_MISSING`: `근거 데이터 없음`
- `RAG_ZERO`: `규정 검색 실패`
- `INPUT_PARTIAL`: `입력 데이터 일부 누락`
- `POLICY_CONFLICT`, `POLICY_CONFLICT_DETECTED`: `정책 신호 충돌`
- `POLICY_REEVAL_APPLIED`: `정책 재검토 적용`
- `RISK_ARTICLE_MISMATCH`: `위험유형-조항 불일치`
- `SENTENCE_CITATION_MISSING`: `문장 근거 미연결`
- `EVIDENCE_COVERAGE_LOW`: `근거 커버리지 낮음`
- `FACT_CONTEXT_PARTIAL`: `사실 컨텍스트 일부 누락`

5. AI 분석 신뢰도 지표(4개 KPI) 타이틀 고정
- `규정 검색 실패율` (`RAG_ZERO` 비율)
- `근거 부족률` (`EVIDENCE_COVERAGE_LOW` 비율)
- `문장 근거 미연결률` (`SENTENCE_CITATION_MISSING` 비율)
- `정책 재검토 적용률` (`POLICY_REEVAL_APPLIED` 비율)

6. eval-run 데이터 없음 표기 규칙
- `runKey 없음`, `-` 대신 아래 문구 사용:
  - `평가 데이터 없음`
  - `아직 평가 실행 결과가 없습니다.`
