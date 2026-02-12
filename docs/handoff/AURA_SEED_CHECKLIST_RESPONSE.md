# Aura 시드 등록 체크리스트 응답 (back.txt 기준)

백엔드 체크리스트 §2·§4에 맞춰, **에이전트 1건당** 채울 수 있는 값입니다.  
**system_instruction 전문**은 별도 파일 `ALL_SYSTEM_PROMPTS_DEFAULT.txt`에서 복사해 넣으면 됩니다.

---

## 전달 문서 2종

| 문서 | 용도 |
|------|------|
| **ALL_SYSTEM_PROMPTS_DEFAULT.txt** | 각 도메인별 system prompt **전문**. §2의 `system_instruction` 필드에 넣을 때 해당 구역 본문만 복사. |
| **본 문서 (AURA_SEED_CHECKLIST_RESPONSE.md)** | 에이전트별 agent_key, name, domain, model_name, tool_names 등 §4 형식 정리. |

두 문서를 함께 전달하면 시드 데이터 등록에 필요한 정보가 모두 포함됩니다.

---

## app_codes 매핑 (Aura ↔ 백엔드)

- **domain**: Aura의 system_prompt_key `finance` → 백엔드 **FINANCE**, `dev` → **DEV**, `hr` → **HR**. (back.txt §1.1)
- **model_name**: 백엔드 **LLM_MODEL** 3개만 사용 (gpt-4o / claude-3-5-sonnet / r1). (back.txt §1.2)

---

## 에이전트 1건: Finance 감사 (현재 Aura에서 사용 중)

| 구분 | 필드 | 값 |
|------|------|-----|
| 식별 | **agent_key** | `finance_aura` |
| 식별 | **name** | Finance 감사 에이전트 |
| 코드 | **domain** | **FINANCE** |
| 코드 | **model_name** | **gpt-4o** (또는 claude-3-5-sonnet / r1 중 선택) |
| 모델 | **temperature** | 0.2 |
| 모델 | **max_tokens** | 4096 |
| 프롬프트 | **system_instruction** | `ALL_SYSTEM_PROMPTS_DEFAULT.txt` 내 **# ============ BEGIN domain: finance ============** ~ **END domain: finance** 구역의 본문 전체 (주석 줄 제외) |
| 도구 | **tool_names** | 아래 목록과 동일하게 `agent_tool_inventory.tool_name`에 등록 후 매핑 |

**tool_names (순서 무관, 10개)**  
`get_case`, `search_documents`, `get_document`, `get_entity`, `get_open_items`, `get_lineage`, `web_search`, `simulate_action`, `propose_action`, `execute_action`

- **tenant_id**: 시드 시 `1` 사용 권장.

---

## 기타 도메인 (dev, hr) — 필요 시 등록

백엔드에 DEV/HR 에이전트를 시드로 넣는 경우:

- **agent_key**: 예) `dev_aura`, `hr_aura`  
- **name**: 예) 개발 에이전트, HR 에이전트  
- **domain**: **DEV** / **HR**  
- **system_instruction**: `ALL_SYSTEM_PROMPTS_DEFAULT.txt`에서 각각 **domain: dev**, **domain: hr** 구역 본문 사용  
- **tool_names**: 해당 에이전트에서 실제 사용하는 도구만 `agent_tool_inventory`와 동일한 이름으로 등록  

(base, code_review, issue_manager는 Aura 내부에서 용도별로 쓰는 프롬프트 키이며, 백엔드 agent_master 1건당 1:1로 등록하는 에이전트는 아님. 필요 시 별도 협의.)

---

## §3 사전 준비 확인

- **agent_tool_inventory**: 위 Finance **tool_names** 10개가 모두 `tool_name`으로 등록되어 있어야 함.  
  - **도구별 설명·파라미터**는 `docs/handoff/TOOL_INVENTORY_FOR_BACKEND.md`에 정리되어 있음 (시드/스튜디오 표시용).  
  - 이름만 필요하면 TOOL_NAMING_FOR_BACKEND.md 참고.
- **app_codes**: AGENT_DOMAIN(FINANCE/HR/DEV), LLM_MODEL(gpt-4o, claude-3-5-sonnet, r1) — V54 시드 기준 사용.

---

## 요약

- **ALL_SYSTEM_PROMPTS_DEFAULT.txt**만 주면: system_instruction **전문**만 채울 수 있고, agent_key·name·domain·model_name·tool_names 등은 비어 있음.  
- **ALL_SYSTEM_PROMPTS_DEFAULT.txt + 본 문서**를 함께 전달하면, back.txt §2·§4에 필요한 항목을 모두 채워 시드 등록 가능합니다.
