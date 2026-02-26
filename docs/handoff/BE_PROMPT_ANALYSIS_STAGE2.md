# BE 협의 프롬프트 (Analysis 2차 고도화 연동)

## 목적
Aura 분석 결과의 근거 정합성(문장-인용 매핑)과 분석 신뢰 지표를 백엔드에서 저장/집계 가능하도록 확장

## Aura에서 현재 전달되는 핵심 필드
- `finalResult.quality_gate_codes` (내부 코드)
- `finalResult.analysis_quality_signals` (권장: 사용자 친화 신호명 배열, Aura에서 동시 제공 예정)
- `finalResult.analysis_score_breakdown`
- `finalResult.sentence_citation_map`
- `finalResult.decision_reason.sentence_citation_map`
- `finalResult.decision_reason.analysis_score_breakdown`

## 코드 ↔ 표시명(사용자 친화) 매핑
- `OK` → `정상`
- `EVIDENCE_MISSING` → `근거 데이터 없음`
- `RAG_ZERO` → `규정 검색 실패`
- `INPUT_PARTIAL` → `입력 데이터 일부 누락`
- `POLICY_CONFLICT` → `정책 신호 충돌`
- `POLICY_CONFLICT_DETECTED` → `정책 신호 충돌`
- `POLICY_REEVAL_APPLIED` → `정책 재검토 적용`
- `RISK_ARTICLE_MISMATCH` → `위험유형-조항 불일치`
- `SENTENCE_CITATION_MISSING` → `문장 근거 미연결`
- `EVIDENCE_COVERAGE_LOW` → `근거 커버리지 낮음`
- `FACT_CONTEXT_PARTIAL` → `사실 컨텍스트 일부 누락`

## BE 요청사항
1. 저장 스키마 확장
- 대상: `case_analysis_result` 또는 동등 저장 테이블
- 권장 컬럼:
  - `quality_gate_codes` (`jsonb` or `text[]`, 내부 코드 저장)
  - `analysis_quality_signals` (`jsonb` or `text[]`, 표시용 신호명 저장)
  - `analysis_score_breakdown` (`jsonb`)
  - `sentence_citation_map` (`jsonb`)
  - `grounding_coverage_ratio` (`numeric`) [선택]
  - `ungrounded_claim_sentences` (`int`) [선택]

2. 운영 집계 API 제공
- 기간/tenant 기준 집계:
  - 규정 검색 실패율(`RAG_ZERO`)
  - 근거 부족률(`EVIDENCE_COVERAGE_LOW`)
  - 문장 근거 미연결률(`SENTENCE_CITATION_MISSING`)
  - 정책 재검토 적용률(`POLICY_REEVAL_APPLIED`)
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
  count(*) FILTER (WHERE quality_gate_codes ? 'SENTENCE_CITATION_MISSING') AS sentence_missing,
  count(*) FILTER (WHERE quality_gate_codes ? 'POLICY_REEVAL_APPLIED') AS policy_reeval
FROM dwp_aura.case_analysis_result
WHERE tenant_id = 1
  AND created_at >= now() - interval '7 days';
```

## 용어 표준(문서/화면/응답 공통)
- 기존 용어 `품질게이트코드` 대신 아래 용어를 사용:
  - 내부/개발: `quality_gate_codes`
  - 사용자 노출: `분석 신뢰 신호`
