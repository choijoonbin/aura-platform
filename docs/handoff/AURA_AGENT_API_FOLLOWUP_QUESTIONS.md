# Aura → 백엔드 추가 질문 (에이전트·도구 API 명세 검토 후)

백엔드 전달 문서 **Aura 전달 에이전트 관련 API 명세서 (BE ↔ Aura 규격)** 및 **Agent Studio 계약** 확인했습니다.

**→ 백엔드 답변 반영 완료 (2026-02-12)**  
- Config: `GET /api/v1/agents/config?agent_key=...` (X-Tenant-ID 필수), ApiResponse.data(camelCase) 파싱, tools[].toolName → agent_tool_mapping.  
- Aura 반영: `core/analysis/agent_factory.py` (fetch_agent_config, _parse_config_response), config 기본 경로 `api/v1/agents/config`.

**→ 백엔드 문서 반영 완료 (공유)**  
- 백엔드 레포에 Aura 측 반영 요약이 반영됨: `docs/integration/AURA_AGENT_API_QUESTIONS_RESPONSE.md` (Aura 반영 완료 섹션·요약 표), `docs/integration/AURA_AGENT_API_SPEC.md` (Aura 반영 상태). agent_id ↔ agent_key 사용 방식 안내 포함.

---

## (아래는 질문 원문)

---

## 1. Config API 호출 방식 (에이전트 식별자)

**명세**: `GET /api/v1/agents/{id}/config`, Path `id` = **agentId (Long)**.

**Aura 현행**: `GET {gateway}/{agent_config_path}` + **Query** `agent_id`, `tenant_id`, `version` (예: `agent_id=audit` 또는 `agent_id=finance_aura`). Aura는 **숫자 PK(agentId)를 알 수 없는** 상태에서 호출합니다.

**질문**:
- **(1-1)** Aura가 **agent_key**(예: `finance_aura`)만으로 설정을 받을 수 있나요?  
  - 가능하다면: `GET /api/v1/agents/config?agent_key=finance_aura&X-Tenant-ID=1` 같은 **Query 기반** API를 지원해 주실 수 있을까요?  
  - 또는 **agent_key → agentId(Long) 조회 API**(예: `GET /api/synapse/agents/by-key?agent_key=finance_aura&tenant_id=1`)가 있다면 경로와 응답 형식을 알려주세요.
- **(1-2)** Query 기반을 쓰지 않는다면, Aura가 **최초 1회** agent_key로 조회해 agentId를 캐시한 뒤 `GET /api/v1/agents/{id}/config`만 사용하는 방식으로 맞출 수 있습니다. 그 경우 “by-key” 조회 API 스펙(경로·파라미터·응답에 포함되는 agentId)을 알려주세요.

---

## 2. Config 응답 필드명·매핑

**명세**: `agentId`, `agentKey`, `name`, `domain`, `model`, `systemInstruction`, `tools[]` (각 항목: `toolName`, `description`, `schemaJson`).

**Aura AgentConfig**에서 사용하는 이름: `agent_id`, `version`, `system_instruction`, `model_name`, `agent_tool_mapping`(도구 이름 목록), `tools`(선택).

**질문**:
- **(2-1)** 응답에 **version** 필드가 포함되나요? (Aura는 콜백 시 `agent_id`·`version`을 함께 전달합니다. `agent_prompt_history` 버전 또는 agent_master 버전 등이 있으면 필드명과 의미를 알려주세요.)
- **(2-2)** Aura는 **agent_tool_mapping**으로 도구 이름 목록을 사용합니다. 백엔드가 **tools[]**만 내려주는 경우, Aura는 `tools[].toolName`을 모아서 agent_tool_mapping으로 사용해도 될까요? (그렇다면 별도 필드 `agent_tool_mapping`은 없어도 됩니다.)

---

## 3. ApiResponse 래퍼 및 data 추출

**명세**: Content-Type application/json, **ApiResponse&lt;T&gt; 래퍼**, 실제 설정은 **data** 필드.

**질문**:
- **(3-1)** ApiResponse의 **data** 필드 키는 정확히 `"data"`인가요? (예: `{ "success": true, "data": { "agentId": 1, "agentKey": "finance_aura", ... } }`)  
- **(3-2)** Aura는 응답 JSON에서 `data`를 꺼낸 뒤 `AgentConfig`로 매핑할 예정입니다. **data 안의 필드명**이 명세와 동일하게 camelCase(agentKey, systemInstruction, model.modelName 등)로만 내려오면, Aura에서 snake_case로 변환해 수신하겠습니다.

---

## 4. Agent-Tools Base URL (도구 실행)

**명세**: Base URL `http://{gateway}:8080/api/synapse/agent-tools`, 예: `GET .../agent-tools/cases/123`.

**Aura 현행**: `synapse_base_url`(설정값)을 Base로 두고, 그 뒤에 `/cases/{caseId}`, `/documents`, `/documents/{bukrs}/{belnr}/{gjahr}` 등 경로를 붙여 호출합니다. `synapse_base_url`에 `agent-tools`가 포함되어 있으면 경로를 그대로 붙이고, 없으면 구 경로 `/tools/finance/...`를 사용합니다.

**질문**:
- **(4-1)** 명세의 **경로 (Base 제외)**가 `/cases/{caseId}`, `/documents`, `/documents/{bukrs}/{belnr}/{gjahr}` 등으로 맞나요? (즉, Base가 `.../agent-tools`일 때 전체 URL이 `.../agent-tools/cases/123` 형태인지 확인 부탁드립니다.)

---

## 5. web_search 도구

**명세**: `web_search` — “(Aura 내부 또는 외부 Tavily 등)”, BE agent-tools 아님.

**확인**: Aura는 web_search를 **엔진 내부**에서 실행하며, Synapse agent-tools API를 호출하지 않습니다. config의 **tools[]**에 `toolName: web_search`가 포함되어 있으면, Aura는 자체 구현 도구만 바인딩합니다. 이 점만 확인해 두시면 됩니다.

---

정리하면, **(1) config 호출 시 agent_key만으로 조회 가능한지(또는 by-key API 스펙)**, **(2) version 필드 여부 및 tools[]만으로 도구 목록 사용 가능 여부**, **(3) ApiResponse data 키 및 camelCase 필드명**, **(4) agent-tools 경로 확인**만 답변해 주시면 Aura 쪽에서 경로·파싱·필드 매핑을 최종 반영하겠습니다.
