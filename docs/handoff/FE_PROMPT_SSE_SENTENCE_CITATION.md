# FE 협의 프롬프트 (SSE 문장-근거 매핑 표시)

## 목적
분석 스트림에서 문장별 인용 근거를 실시간으로 보여주고, 최종 결과에서도 검증 가능하게 표시

## SSE 이벤트 계약
- event: `evidence`
- payload:
  - `type = "SENTENCE_CITATION_MAP"`
  - `items = [{ sentence_index, sentence, citation_ids: [C1...], grounded }]`
  - `thought_stream = "결론 문장별 인용 근거 매핑을 완료했습니다."`

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
  - `quality_gate_codes`

4. 사용자 친화 문구
- `SENTENCE_CITATION_MISSING`: "핵심 결론 문장에 인용 근거 연결이 부족합니다."
- `EVIDENCE_COVERAGE_LOW`: "문장별 근거 커버리지가 낮아 판단 신뢰도가 제한됩니다."
- `POLICY_REEVAL_APPLIED`: "정책 신호 충돌로 보수적 재평가가 적용되었습니다."

