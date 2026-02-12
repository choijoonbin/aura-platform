# 프론트엔드 크로스 체크 답변 (6.7 프롬프트 변수 가이드, 6.8 도구 key ↔ @tool 이름)

Aura 엔진 기준으로, 편집기 변수 가이드·도구 key와의 일치 여부를 정리했습니다.

---

## 6.7 프롬프트 변수 가이드 (편집기 우측 변수 가이드 ↔ 런타임 치환)

### Aura에서 실제로 치환하는 변수

| 프롬프트 내 플레이스홀더 | 런타임 치환 | 비고 |
|--------------------------|-------------|------|
| **{context}** | ✅ 치환됨 | 시스템 프롬프트 공통. 값은 아래 규칙으로 만든 **문자열** |
| **{code}** | ✅ 치환됨 | **code_review** 도메인에서만 사용 |

- **{case_json}**, **{user_id}** 등 Aura 코드에 없는 이름은 **엔진에서 치환하지 않습니다**.
- 편집기 변수 가이드에는 **{context}**, **{code}** 만 런타임 치환 변수로 안내하는 것이 Aura와 일치합니다.

### {context} 에 들어가는 내용 (context가 dict일 때)

Aura는 `get_system_prompt(domain=..., context=...)` 호출 시 **context**를 dict로 받으면, 아래 키들만 사용해 한 줄씩 이어 붙인 문자열로 치환합니다.

| context 키 (dict) | 치환 시 문구 예시 |
|-------------------|-------------------|
| activeApp | `현재 사용자가 보고 있는 화면: {activeApp}` |
| selectedItemIds | `선택된 항목 ID: {items_str}` |
| url | `현재 URL: {url}` |
| path | `경로: {path}` |
| title | `페이지 제목: {title}` |
| itemId | `항목 ID: {itemId}` |
| caseId | `케이스 ID: {caseId}` |
| documentIds | `문서 ID 목록: {documentIds}` |
| entityIds | `엔티티 ID 목록: {entityIds}` |
| openItemIds | `미결 항목 ID 목록: {openItemIds}` |
| metadata | `추가 정보: {k}: {v} ...` |

- 따라서 “케이스 정보”를 넣고 싶다면, 프롬프트 본문에 **{context}** 를 두고, 런타임에 넘기는 **context** dict에 **caseId**(및 필요 시 documentIds, entityIds 등)를 넣으면 됩니다.  
- **{case_json}** 같은 별도 변수는 Aura에 없으므로, 가이드 문구가 “실제 치환되는 변수”와 맞으려면 **{context}** / **{code}** 로 통일하는 것을 권장합니다.

### §4 의사결정과의 관계

- 동적 배포 시에도, 엔진이 치환하는 변수는 위와 동일합니다.  
- DB에서 받은 **system_instruction** 본문에 **{context}** / **{code}** 가 있으면 그대로 치환하고, 그 외 이름(예: {case_json})은 치환하지 않습니다.

---

## 6.8 도구 key ↔ @tool 이름 (카탈로그 key / BE tool_name ↔ Aura @tool)

### 규칙

- **카탈로그의 도구 key**(또는 백엔드 **tool_name**)와 Aura의 **@tool 함수명**은 **완전 동일**해야 합니다.
- 1건이라도 다르면, 해당 도구는 엔진에서 인식하지 못하고 스킵되며 ThoughtStream에 “엔진에 등록되지 않아 제외되었습니다” 알림이 남습니다.

### 검증용 목록 (Aura @tool 이름 = FE/BE 사용할 key)

**Finance / Synapse (10개)**  
`get_case`, `search_documents`, `get_document`, `get_entity`, `get_open_items`, `get_lineage`, `web_search`, `simulate_action`, `propose_action`, `execute_action`

**Git (5개)**  
`git_diff`, `git_log`, `git_status`, `git_show_file`, `git_branch_list`

**GitHub (4개)**  
`github_get_pr`, `github_list_prs`, `github_get_pr_diff`, `github_get_file`

- 위 문자열을 **그대로** 카탈로그 key / BE `tool_name` / config 응답 `tools[].toolName`으로 사용하면 Aura와 일치합니다.
- 상세: `docs/handoff/TOOL_NAMING_FOR_BACKEND.md`, `docs/handoff/TOOL_INVENTORY_FOR_BACKEND.md`.

### 1건 이상 검증 예시

- 카탈로그에 `get_case` 로 등록되어 있고, config 응답의 `tools[].toolName` 이 `get_case` 이면 → Aura `get_case` @tool과 일치.
- `Google Search` / `Web Search` 처럼 별칭을 key로 쓰면 Aura와 불일치 → **web_search** 만 사용.

---

## 요약

| 체크 항목 | Aura 측 답변 |
|-----------|--------------|
| **6.7** 변수 가이드 | 런타임 치환 변수는 **{context}**, **{code}** 뿐. 편집기 가이드는 이 두 이름·형식과 맞추면 됨. {case_json} 등은 Aura에 없음. |
| **6.8** 도구 key ↔ @tool | 카탈로그 key = BE tool_name = **tools[].toolName** = Aura @tool 함수명(위 목록). 동일 문자열 1건 이상 검증 시 위 표로 확인 가능. |
