# BE 협의 프롬프트 (Analysis 2차 고도화 연동)

## 목적
Aura 분석 결과의 근거 정합성(문장-인용 매핑)과 품질 게이트 지표를 백엔드에서 저장/집계 가능하도록 확장

## Aura에서 현재 전달되는 핵심 필드
- `finalResult.quality_gate_codes` (예: `RAG_ZERO`, `EVIDENCE_COVERAGE_LOW`, `SENTENCE_CITATION_MISSING`, `POLICY_REEVAL_APPLIED`)
- `finalResult.analysis_score_breakdown`
- `finalResult.sentence_citation_map`
- `finalResult.decision_reason.sentence_citation_map`
- `finalResult.decision_reason.analysis_score_breakdown`

## BE 요청사항
1. 저장 스키마 확장
- 대상: `case_analysis_result` 또는 동등 저장 테이블
- 권장 컬럼:
  - `quality_gate_codes` (`jsonb` or `text[]`)
  - `analysis_score_breakdown` (`jsonb`)
  - `sentence_citation_map` (`jsonb`)
  - `grounding_coverage_ratio` (`numeric`) [선택]
  - `ungrounded_claim_sentences` (`int`) [선택]

2. 운영 집계 API 제공
- 기간/tenant 기준 집계:
  - `RAG_ZERO` 비율
  - `EVIDENCE_COVERAGE_LOW` 비율
  - `SENTENCE_CITATION_MISSING` 비율
  - `POLICY_REEVAL_APPLIED` 비율
- 예시:
  - `GET /api/synapse/aura/quality-metrics?tenantId=1&from=...&to=...`

3. 콜백 수용 스키마 확인
- `decision_reason` 내 신규 json 필드가 누락/파기되지 않고 저장되는지 확인
- unknown field drop 정책이면 화이트리스트 갱신 필요

4. 검증 SQL (예시)
```sql
SELECT
  count(*) AS total,
  count(*) FILTER (WHERE quality_gate_codes ? 'RAG_ZERO') AS rag_zero,
  count(*) FILTER (WHERE quality_gate_codes ? 'EVIDENCE_COVERAGE_LOW') AS coverage_low,
  count(*) FILTER (WHERE quality_gate_codes ? 'SENTENCE_CITATION_MISSING') AS sentence_missing
FROM dwp_aura.case_analysis_result
WHERE tenant_id = 1
  AND created_at >= now() - interval '7 days';
```

