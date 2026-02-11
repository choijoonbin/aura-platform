# Policy-Aware Reasoning & RAG Metadata (Phase 4)

## Pre-Check (MUST ANSWER BEFORE CODING)

### Q1. 현재 에이전트가 분석 시점에서 백엔드에 등록된 최신 정책 데이터를 실시간으로 가져오고 있습니까?

**아니오.**  
- Phase2/Phase3는 요청 body의 `body_evidence.policies` / `artifacts.policies` 또는 옵션의 `policyVersion`만 사용합니다.
- `dwp_aura.sys_monitoring_configs` 또는 `policy_profile` 테이블을 분석 시점에 실시간 조회하는 API/도구는 없습니다.
- **Phase 4 보강**: 요청 컨텍스트에 `policy_config_source`, `policy_profile`을 설정할 수 있게 하고, 분석 파이프라인/훅에서 이 값을 `metadata_json.reasoning` 및 `policy_reference`에 기록합니다. 실시간 DB 조회는 별도 도구/API 확장 시 연동합니다.

### Q2. metadata_json에 정책 참조 정보를 넣기 위한 추가 필드(`policy_reference`) 정의가 필요한가요?

**예.**  
- 기존 `metadata_json`은 `title`, `reasoning`, `evidence`, `status`만 강제합니다.
- 정책/임계치 참조를 필터링·표시하려면 **`policy_reference`** 구조화 필드가 필요합니다.
- **정의**: `evidence.policy_reference` (또는 metadata_json 최상위)에 `{ configSource?, profileName?, thresholdsReferenced? }` 형태로 저장합니다.

---

## 구현 요약

- **policy_reference**: `format_metadata` 및 Audit evidence에 선택적 포함. context의 `policy_config_source`, `policy_profile`을 기록.
- **reasoning**: 추론 완료 시 "dwp_aura.sys_monitoring_configs 임계치 및 policy_profile 가이드 참조" 문구를 reasoning에 명시.
- **RAG contribution trace**: RAG 검색 결과에서 문서별 위치 정보(location, title 등)를 추출해 `evidence.ragContributions` 배열로 기록.

백엔드 연동 시 RAG 참조 로그 형식은 **`docs/backend/RAG_REFERENCE_LOG_FORMAT_FOR_BACKEND.md`** 참고.
