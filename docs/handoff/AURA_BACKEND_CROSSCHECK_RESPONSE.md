# Aura → 백엔드 추가 확인 사항 답변

백엔드 체크리스트 7개 항목에 대한 Aura 측 확인 결과입니다.

---

## 1. agent-tools 메서드·파라미터

| 항목 | Aura 구현 상태 |
|------|----------------|
| **search_documents** | ✅ **GET** `/agent-tools/documents` + query (bukrs, gjahr, page, size 등) |
| **get_open_items** | ✅ **GET** `/agent-tools/open-items` + query (type, overdueBucket, page, size) |
| **caseId만 있을 때** | ✅ `search_documents`에서 caseId만 있으면 `get_case`로 case 조회 후 bukrs/gjahr 추출해 documents 호출 (`tools/synapse_finance_tool.py` line 300-309) |

**확인**: POST+body가 아닌 **GET+query**로 호출합니다.

---

## 2. agent-tools 헤더

| 헤더 | Aura 전달 여부 |
|------|----------------|
| **X-Tenant-ID** | ✅ 필수 (`get_synapse_headers()` → `core/context.py`) |
| **Authorization** | ✅ 필수 (`get_synapse_headers()` → context의 auth_token) |
| **X-Agent-ID** | ⭕ 선택 (현재 미전달. 필요 시 추가 가능) |

**확인**: `tools/synapse_finance_tool.py`의 `_get_headers()` → `get_synapse_headers()` 사용. config 호출과 동일하게 **X-Tenant-ID, Authorization** 전달합니다.

---

## 3. get_lineage

| 항목 | Aura 구현 상태 |
|------|----------------|
| **caseId 쿼리 지원** | ✅ 지원 (`/lineage?caseId={caseId}`) |
| **belnr/gjahr/bukrs 직접 전달** | ⚠️ 현재 지원하나, 백엔드 명세와 불일치. **caseId만 사용하도록 수정 예정** |

**수정 필요**: `tools/synapse_finance_tool.py` `get_lineage()`에서 belnr+gjahr 지원 로직 제거, **caseId만 사용**하도록 변경.

---

## 4. 인식 불가 tool_name

| 항목 | Aura 구현 상태 |
|------|----------------|
| **스킵 (에러 없음)** | ✅ `get_tools_by_names()` → `(tools, skipped)` 반환. 레지스트리에 없으면 스킵 |
| **ThoughtStream 알림** | ✅ `FinanceAgent._analyze_node()`에서 `_skipped_tool_names` 있을 때 thought 추가: `"다음 도구는 스튜디오 설정에 있으나 엔진에 등록되지 않아 이번 실행에서 제외되었습니다: {도구명 목록}."` |

**확인**: 이미 구현되어 있습니다. (`core/analysis/agent_factory.py`, `domains/finance/agents/finance_agent.py`)

---

## 5. X-Sandbox: true

| 항목 | Aura 구현 상태 |
|------|----------------|
| **헤더 수신** | ✅ `api/routes/aura_cases.py`, `api/routes/aura_internal.py`에서 `X-Sandbox` 헤더 수신 |
| **context 저장** | ✅ `set_request_context(x_sandbox=...)`로 context에 저장 |
| **콜백에 is_sandbox 포함** | ✅ `send_callback()`에서 `is_sandbox` 플래그 포함 (BE가 DB 저장 생략용) |

**확인**: 헤더 수신 → context 저장 → 콜백에 `is_sandbox` 포함까지 반영했습니다. BE가 콜백 수신 시 `is_sandbox: true`면 DB 저장을 생략하면 됩니다.

---

## 6. 에러 시 폴백

| 항목 | Aura 구현 상태 |
|------|----------------|
| **404 시 _default_config** | ✅ `fetch_agent_config()`에서 404(또는 기타 예외) 시 `_default_config(agent_id, version)` 반환 |
| **400/404 구분 로그** | ⚠️ 현재는 `logger.debug()`로만 기록. 400/404 구분해 로그 남기도록 개선 예정 |

**확인**: 폴백은 동작합니다. 400/404 구분 로그는 추가하겠습니다.

---

## 7. X-Tenant-ID 타입

| 항목 | Aura 구현 상태 |
|------|----------------|
| **헤더 값** | ✅ 문자열 `"1"` 또는 context의 `tenant_id` (문자열)로 전달 |
| **일관성** | ✅ config 호출과 agent-tools 호출 모두 동일하게 문자열로 전달 |

**확인**: 숫자(Long)가 아닌 **문자열**로 전달합니다. 백엔드가 문자열 파싱 가능하면 문제없습니다.

---

## 수정 완료 항목

1. ✅ **get_lineage**: belnr+gjahr 지원 제거, **caseId만 사용**하도록 변경 (`tools/synapse_finance_tool.py`).
2. ✅ **fetch_agent_config**: 400/404 구분 로그 추가 (`core/analysis/agent_factory.py`).
3. ✅ **X-Sandbox**: 헤더 수신 → context 저장 → 콜백에 `is_sandbox` 포함 (`api/routes/aura_cases.py`, `core/context.py`, `core/analysis/callback.py`).

**모든 항목 반영 완료.** 백엔드 체크리스트와 일치합니다.
