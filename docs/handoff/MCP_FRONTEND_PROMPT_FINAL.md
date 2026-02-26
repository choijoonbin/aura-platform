# [FE 전달] MCP 고도화 연동 요청 (최종본)

## 전제
- 신규 페이지는 만들지 않습니다.
- 기존 화면에 데이터 위치/표시 규칙만 보강합니다.

## 대상 화면
1. 통합워크벤치(분석 결과/추론 탭)
2. 관리자 디버그 섹션(기존 토글 활용)
3. RAG 문서 상세/리포트 영역(기존 컴포넌트 활용)

## 필수 표시 항목
1. quality_gate_codes
- 위치: 분석 결과 상단 배지/태그
- 표시 규칙:
  - `RAG_ZERO`, `EVIDENCE_MISSING`, `POLICY_CONFLICT`, `INPUT_PARTIAL` 우선 노출

2. sentence_citation_map
- 위치: reason 문장 리스트 하단
- 표시 규칙:
  - 각 문장 옆 `citation_id[]` 표시
  - citation_id 없으면 경고 아이콘 + 운영자 디버그에서 원문 확인 가능

3. score_breakdown
- 위치: 리스크 점수 카드
- 표시 규칙:
  - 정책점수/근거점수/최종점수 분리 표시
  - "확정 판단 보류"인 경우 이유 코드와 함께 표시

4. 보류/충돌 UX
- `POLICY_CONFLICT`, `RAG_ZERO`인 경우 확정 문구 대신 보류 안내 문구 표시

## 데이터 계약 확인 포인트
- `finalResult.decision_reason.quality_gate_codes`
- `finalResult.decision_reason.sentence_citation_map`
- `finalResult.decision_reason.score_breakdown`
- `finalResult.citations`

## 운영자 디버그(기존 확장)
- raw quality_report
- quality_gate_codes 원문 배열
- sentence-citation 검증 실패 사유(mismatch_reasons)

## 수용 기준(AC)
1. 신규 화면 없이 기존 화면에서 4개 핵심 데이터가 모두 노출됨
2. citation 누락 문장은 사용자 화면에서 "근거 미연결" 상태로 표시됨
3. quality_gate_codes가 있을 때 결과 상태 문구와 충돌하지 않음
4. SSE 수신 중 필드 누락에도 UI가 깨지지 않음(방어 렌더링)

## 확인 질문(필요 시)
- 문장별 citation 표시를 기본 노출로 할지, 접기/펼치기로 할지
- 운영자 디버그 권한 범위(SYNAPSEX_VIEWER 포함 여부)

