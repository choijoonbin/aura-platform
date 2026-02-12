# agent_tool_inventory 시드용 도구 정보 (Aura → 백엔드)

Aura에 **등록되어 있는 모든 도구**의 이름·설명·파라미터를 정리했습니다.  
현재 사용하지 않는 도구도 포함되어 있으므로, 백엔드에서 에이전트별로 골라 매핑(agent_tool_mapping)할 수 있습니다.  
`tool_name`은 Aura 코드의 함수명과 **완전 동일**해야 합니다.

---

## 에이전트별 도구 매핑 (agent_tool_mapping 등록 참고)

| 에이전트(agent_key) | domain | 사용 도구 목록 (tool_names) |
|---------------------|--------|-----------------------------|
| **finance_aura** | FINANCE | get_case, search_documents, get_document, get_entity, get_open_items, get_lineage, web_search, simulate_action, propose_action, execute_action |
| **dev_aura** (선택) | DEV | git_diff, git_log, git_status, git_show_file, git_branch_list, github_get_pr, github_list_prs, github_get_pr_diff, github_get_file |

- 위 목록은 **선택 가능 풀**. 스튜디오에서 에이전트별로 일부만 활성화해 매핑해도 됨.
- **agent_tool_inventory**에는 아래 **전체 19개**를 먼저 등록한 뒤, 에이전트마다 위 표를 참고해 agent_tool_mapping에 넣으면 됨.

---

## A. Finance / Synapse 도구 (10개)

### 1. get_case

| 항목 | 값 |
|------|-----|
| **tool_name** | `get_case` |
| **description** | 케이스 상세 정보를 조회합니다. Synapse 백엔드 Tool API를 통해 중복송장 의심 케이스 등의 상세를 가져옵니다. |

**parameters**: caseId (string, ✅)

### 2. search_documents

| 항목 | 값 |
|------|-----|
| **tool_name** | `search_documents` |
| **description** | 문서를 검색합니다. Synapse GET /documents (query: bukrs, gjahr, page, size 등). caseId만 있으면 get_case로 case 조회 후 bukrs/gjahr 추출하여 documents 호출. |

**parameters**: filters (object, ⭕) — 검색 필터 (caseId, bukrs, gjahr, page, size 등)

### 3. get_document

| 항목 | 값 |
|------|-----|
| **tool_name** | `get_document` |
| **description** | 단일 문서를 조회합니다. |

**parameters**: bukrs (string, ✅), belnr (string, ✅), gjahr (string, ✅)

### 4. get_lineage

| 항목 | 값 |
|------|-----|
| **tool_name** | `get_lineage` |
| **description** | 전표/문서의 라인리지(Lineage)를 조회합니다. caseId 우선, 없으면 belnr+gjahr(+bukrs) 사용. |

**parameters**: caseId (string, ⭕), belnr (string, ⭕), gjahr (string, ⭕), bukrs (string, ⭕)

### 5. get_entity

| 항목 | 값 |
|------|-----|
| **tool_name** | `get_entity` |
| **description** | 엔티티 정보를 조회합니다. |

**parameters**: entityId (string, ✅)

### 6. get_open_items

| 항목 | 값 |
|------|-----|
| **tool_name** | `get_open_items` |
| **description** | 미결 항목(Open Items)을 조회합니다. Synapse GET /open-items (query: type, overdueBucket, page, size). |

**parameters**: filters (object, ⭕) — type: AR|AP, overdueBucket, page, size 등

### 7. web_search

| 항목 | 값 |
|------|-----|
| **tool_name** | `web_search` |
| **description** | 외부 지능형 웹 검색을 실행합니다. 회계/세무 기준, 국세청 가이드라인, 업종별 지출 관행 등을 검색할 때 사용합니다. 검색 결과에는 원문 URL이 포함되며, 답변 작성 시 [설명](URL) 마크다운 형식으로 인용합니다. |

**parameters**: query (string, ✅)

### 8. simulate_action

| 항목 | 값 |
|------|-----|
| **tool_name** | `simulate_action` |
| **description** | 액션을 시뮬레이션합니다. 실제 실행 없이 결과를 미리 확인합니다. X-Idempotency-Key로 중복 호출 방지. |

**parameters**: caseId (string, ✅), actionType (string, ✅), payload (object, ⭕), idempotency_key (string, ⭕)

### 9. propose_action

| 항목 | 값 |
|------|-----|
| **tool_name** | `propose_action` |
| **description** | 액션을 제안합니다. 위험도가 높거나 Guardrail에 걸리면 HITL 승인이 필요합니다. 승인 필요 시 에이전트가 interrupt되고, 사용자 승인 후 execute_action으로 실행됩니다. |

**parameters**: caseId (string, ✅), actionType (string, ✅), payload (object, ⭕)

### 10. execute_action

| 항목 | 값 |
|------|-----|
| **tool_name** | `execute_action` |
| **description** | 승인 완료된 액션을 실행합니다. HITL 승인 후 Synapse 백엔드에서 전달한 actionId로 호출합니다. X-Idempotency-Key로 중복 실행 방지. |

**parameters**: actionId (string, ✅), idempotency_key (string, ⭕)

---

## B. Git 도구 (5개) — DEV 에이전트 등에서 사용 가능

### 11. git_diff

| 항목 | 값 |
|------|-----|
| **tool_name** | `git_diff` |
| **description** | Git diff를 조회합니다. 로컬 Git 저장소의 변경사항을 확인할 때 사용합니다. |

**parameters**: repo_path (string, ✅), branch (string, ⭕ default HEAD), file_path (string, ⭕)

### 12. git_log

| 항목 | 값 |
|------|-----|
| **tool_name** | `git_log` |
| **description** | Git 커밋 로그를 조회합니다. 최근 커밋 히스토리를 확인할 때 사용합니다. |

**parameters**: repo_path (string, ✅), limit (integer, ⭕ default 10), branch (string, ⭕ default HEAD)

### 13. git_status

| 항목 | 값 |
|------|-----|
| **tool_name** | `git_status` |
| **description** | Git 상태를 조회합니다. 현재 작업 디렉토리의 변경사항을 확인할 때 사용합니다. |

**parameters**: repo_path (string, ✅)

### 14. git_show_file

| 항목 | 값 |
|------|-----|
| **tool_name** | `git_show_file` |
| **description** | 특정 커밋의 파일 내용을 조회합니다. 과거 버전의 파일을 확인할 때 사용합니다. |

**parameters**: repo_path (string, ✅), file_path (string, ✅), commit (string, ⭕ default HEAD)

### 15. git_branch_list

| 항목 | 값 |
|------|-----|
| **tool_name** | `git_branch_list` |
| **description** | Git 브랜치 목록을 조회합니다. 저장소의 모든 브랜치를 확인할 때 사용합니다. |

**parameters**: repo_path (string, ✅), remote (boolean, ⭕ default false)

---

## C. GitHub 도구 (4개) — DEV 에이전트 등에서 사용 가능

### 16. github_get_pr

| 항목 | 값 |
|------|-----|
| **tool_name** | `github_get_pr` |
| **description** | GitHub Pull Request 정보를 조회합니다. PR의 제목, 설명, 상태 등을 확인할 때 사용합니다. |

**parameters**: owner (string, ✅), repo (string, ✅), pr_number (integer, ✅)

### 17. github_list_prs

| 항목 | 값 |
|------|-----|
| **tool_name** | `github_list_prs` |
| **description** | GitHub Pull Request 목록을 조회합니다. 저장소의 PR 목록을 확인할 때 사용합니다. |

**parameters**: owner (string, ✅), repo (string, ✅), state (string, ⭕ default open), limit (integer, ⭕ default 10)

### 18. github_get_pr_diff

| 항목 | 값 |
|------|-----|
| **tool_name** | `github_get_pr_diff` |
| **description** | GitHub Pull Request의 변경된 파일 목록을 조회합니다. PR에서 어떤 파일이 변경되었는지 확인할 때 사용합니다. |

**parameters**: owner (string, ✅), repo (string, ✅), pr_number (integer, ✅)

### 19. github_get_file

| 항목 | 값 |
|------|-----|
| **tool_name** | `github_get_file` |
| **description** | GitHub 저장소의 파일 내용을 조회합니다. 특정 파일의 코드를 확인할 때 사용합니다. |

**parameters**: owner (string, ✅), repo (string, ✅), path (string, ✅), ref (string, ⭕ default main)

---

## 요약

| 구분 | tool_name 목록 (19개 전체) |
|------|----------------------------|
| **Finance/Synapse** | get_case, search_documents, get_document, get_entity, get_open_items, get_lineage, web_search, simulate_action, propose_action, execute_action |
| **Git** | git_diff, git_log, git_status, git_show_file, git_branch_list |
| **GitHub** | github_get_pr, github_list_prs, github_get_pr_diff, github_get_file |

- **agent_tool_inventory**: 위 19개를 모두 `tool_name`으로 등록.
- **agent_tool_mapping**: 에이전트별로 위 "에이전트별 도구 매핑" 표를 참고해 필요한 tool만 매핑 (Finance만 쓸 경우 10개, DEV 추가 시 Git+GitHub 9개 등).
- Aura 코드: `tools/synapse_finance_tool.py`, `tools/external_search_tool.py`, `tools/integrations/git_tool.py`, `tools/integrations/github_tool.py`
