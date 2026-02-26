# Aura Shadow Run 실행 가이드 (휴일 3건)

## 목적
- 기존 `finance_aura`와 신규 Agentic 경로를 동일 입력으로 비교해 전환 가능성을 검증한다.

## 사전 설정(.env)
- `AGENTIC_V2_ENABLED=true`
- `AGENTIC_V2_PRIMARY_AGENT_KEY=finance_aura_v2_agentic`
- `AGENTIC_SHADOW_RUN_ENABLED=true`
- `AGENTIC_SHADOW_AGENT_KEY=finance_aura`
- `AGENTIC_SHADOW_SAMPLE_RATIO=1.0`
- `AGENTIC_SHADOW_CASE_TYPES=HOLIDAY_USAGE`

## 실행 케이스
- 휴일 케이스 3건 (동일 테넌트, 동일 모델 정책)

## 성공 조건
- 각 run에서 `analysis_background agentic_v2 primary enabled` 로그 확인
- 각 run에서 `shadow_run scheduled` 로그 확인
- 각 run 완료 후 `shadow_compare summary` 로그 확인
- 확정 위반 금지 조건 유지
  - `RAG_ZERO`/`POLICY_CONFLICT`/`FACT_CONTEXT_PARTIAL` 존재 시 보류

## 수집 로그 키워드
- `analysis_background agentic_v2 primary enabled`
- `shadow_run scheduled`
- `shadow_compare summary`
- `audit_analysis quality_gate`
