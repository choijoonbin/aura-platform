# 도구 명칭(Naming) 계약 — 백엔드 DB와 Aura 통일

## 원칙

- **백엔드 DB의 `tool_name`** 과 **Aura 코드의 `@tool` 함수명**은 **반드시 동일한 문자열**을 사용합니다.
- 별칭(예: "Google Search", "Web Search")은 사용하지 않고, 아래 **canonical name**만 사용합니다.

## Canonical Tool Names (Finance Agent)

| Aura 함수명 (@tool) | DB tool_name (동일) | 비고 |
|---------------------|---------------------|------|
| `get_case`          | `get_case`          | 케이스 상세 조회 |
| `search_documents`  | `search_documents`  | 문서/사내 규정 검색 |
| `get_document`      | `get_document`      | 단일 문서 조회 |
| `get_entity`        | `get_entity`        | 거래처/엔티티 조회 |
| `get_open_items`    | `get_open_items`    | 미결 항목 조회 |
| `get_lineage`       | `get_lineage`       | 전표 계보 |
| **`web_search`**    | **`web_search`**    | 외부 지능형 검색 (Tavily 등). "Google Search" 사용 금지 |
| `simulate_action`   | `simulate_action`   | 액션 시뮬레이션 |
| `propose_action`    | `propose_action`    | 조치 제안 (HITL) |
| `execute_action`    | `execute_action`   | 승인된 액션 실행 |

### Git (5개) / GitHub (4개) — DEV 에이전트 등 매핑 가능

`git_diff`, `git_log`, `git_status`, `git_show_file`, `git_branch_list`, `github_get_pr`, `github_list_prs`, `github_get_pr_diff`, `github_get_file` (함수명 = tool_name 동일).  
→ **전체 19개** 이름·설명·파라미터 및 에이전트별 매핑: `docs/handoff/TOOL_INVENTORY_FOR_BACKEND.md`

## Aura 쪽 참조

- 상수 정의: `tools/tool_names.py` — `FINANCE_TOOL_NAMES`, `TOOL_WEB_SEARCH` 등
- 실제 도구: `tools/synapse_finance_tool.py`, `tools/external_search_tool.py` — 위 표와 동일한 **함수명** 사용
- **도구 상세(설명·파라미터)**: `docs/handoff/TOOL_INVENTORY_FOR_BACKEND.md` — agent_tool_inventory 시드용 이름·설명·파라미터 전체

## 백엔드 권장 사항

- `agent_activity_log`, `case_analysis_result` 등에 도구 이름을 저장할 때 위 표의 **tool_name** 컬럼 값만 사용하세요.
- 신규 도구 추가 시 Aura의 `tools/tool_names.py`와 이 문서를 함께 반영하고, DB enum/제약이 있다면 동일 문자열로 맞추세요.

## 의사결정: DB에서 넘어온 인식 불가 tool_name 처리

- **엔진에서 인식하지 못하는 `tool_name`**이 DB(agent_tool_mapping)에서 넘어올 경우, **에러로 중단하지 않고** 해당 도구만 스킵합니다.
- **ThoughtStream(thought_chain)**에 알림을 남깁니다:  
  `"다음 도구는 스튜디오 설정에 있으나 엔진에 등록되지 않아 이번 실행에서 제외되었습니다: {도구명 목록}."`
- Aura 구현: `core/analysis/agent_factory.py` `get_tools_by_names()` → 스킵 목록 반환, FinanceAgent `_analyze_node`에서 위 문구로 thought 추가.
